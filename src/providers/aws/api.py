import asyncio
import logging
import time
from typing import Any, Self

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from .exceptions import AwsTransportError, AwsVMNotFoundError
from .settings import AwsSettings

logger = logging.getLogger(__name__)

_RUN_TO_IP_TIMEOUT_SECONDS = 480
_RUN_TO_IP_POLL_SECONDS = 5.0


def _to_tag_list(tags: dict[str, str]) -> list[dict[str, str]]:
    return [{"Key": k, "Value": v} for k, v in tags.items()]


async def _find_sg_by_name(ec2: Any, *, name: str, vpc_id: str | None) -> str | None:
    filters = [{"Name": "group-name", "Values": [name]}]
    if vpc_id:
        filters.append({"Name": "vpc-id", "Values": [vpc_id]})
    try:
        response = await ec2.describe_security_groups(Filters=filters)
    except (ClientError, BotoCoreError) as exc:
        raise AwsTransportError(f"DescribeSecurityGroups failed: {exc}") from exc
    if groups := response.get("SecurityGroups"):
        return str(groups[0]["GroupId"])
    return None


def _ssh_permission(cidrs: set[str]) -> dict[str, Any]:
    # Sorted so the API call (and test assertions) are deterministic.
    return {
        "IpProtocol": "tcp",
        "FromPort": 22,
        "ToPort": 22,
        "IpRanges": [{"CidrIp": cidr} for cidr in sorted(cidrs)],
    }


async def _current_ssh_cidrs(ec2: Any, sg_id: str) -> set[str]:
    try:
        response = await ec2.describe_security_groups(GroupIds=[sg_id])
    except (ClientError, BotoCoreError) as exc:
        raise AwsTransportError(f"DescribeSecurityGroups failed: {exc}") from exc
    groups = response.get("SecurityGroups") or []
    if not groups:
        return set()
    cidrs: set[str] = set()
    for perm in groups[0].get("IpPermissions") or []:
        if (
            perm.get("IpProtocol") == "tcp"
            and perm.get("FromPort") == 22
            and perm.get("ToPort") == 22
        ):
            for ip_range in perm.get("IpRanges") or []:
                cidr = ip_range.get("CidrIp")
                if cidr:
                    cidrs.add(cidr)
    return cidrs


async def _reconcile_ssh_ingress(ec2: Any, sg_id: str, cidrs: tuple[str, ...]) -> None:
    # Make tcp/22 IPv4 ingress on the drukbox-managed SG match `cidrs` exactly:
    # add what's missing, revoke what's stale. Without the revoke, tightening
    # AWS_SSH_CIDRS (e.g. away from the 0.0.0.0/0 fallback) would silently leave
    # the broader rule open. drukbox owns this SG, so it reclaims any tcp/22 rule
    # not in the desired set.
    desired = set(cidrs)
    current = await _current_ssh_cidrs(ec2, sg_id)
    to_add = desired - current
    to_revoke = current - desired

    if to_add:
        try:
            await ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[_ssh_permission(to_add)],
            )
        except (ClientError, BotoCoreError) as exc:
            if (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                != "InvalidPermission.Duplicate"
            ):
                raise AwsTransportError(f"AuthorizeSecurityGroupIngress failed: {exc}") from exc

    if to_revoke:
        try:
            await ec2.revoke_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[_ssh_permission(to_revoke)],
            )
        except (ClientError, BotoCoreError) as exc:
            if (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                != "InvalidPermission.NotFound"
            ):
                raise AwsTransportError(f"RevokeSecurityGroupIngress failed: {exc}") from exc


class AwsAPI:
    def __init__(self, session: aioboto3.Session, *, region: str) -> None:
        self._session: Any = session
        self._region = region

    @classmethod
    def from_settings(cls, settings: AwsSettings) -> Self:
        return cls(aioboto3.Session(region_name=settings.region), region=settings.region)

    async def run_instance(
        self,
        *,
        client_token: str,
        ami_id: str,
        instance_type: str,
        key_name: str | None,
        root_gb: int,
        tags: dict[str, str],
        user_data: str,
        associate_public_ip: bool,
        subnet_id: str | None,
        security_group_id: str | None,
        instance_profile: str | None,
    ) -> str:
        tag_specs = [
            {"ResourceType": "instance", "Tags": _to_tag_list(tags)},
            {"ResourceType": "volume", "Tags": _to_tag_list(tags)},
        ]
        kwargs: dict[str, Any] = {
            "ClientToken": client_token,
            "ImageId": ami_id,
            "InstanceType": instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "TagSpecifications": tag_specs,
            # Raw script: botocore base64-encodes UserData for RunInstances itself.
            # Pre-encoding here would double-encode and leave cloud-init with b64 text.
            "UserData": user_data,
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "Encrypted": True,
                        "VolumeSize": root_gb,
                        "VolumeType": "gp3",
                    },
                }
            ],
            # Untrusted workloads: force IMDSv2, hop limit 1. See docs/security.md.
            "MetadataOptions": {
                "HttpTokens": "required",
                "HttpEndpoint": "enabled",
                "HttpPutResponseHopLimit": 1,
            },
        }
        if key_name:
            kwargs["KeyName"] = key_name
        if instance_profile:
            kwargs["IamInstanceProfile"] = {"Name": instance_profile}
        nic: dict[str, Any] = {
            "AssociatePublicIpAddress": associate_public_ip,
            "DeleteOnTermination": True,
            "DeviceIndex": 0,
        }
        if subnet_id:
            nic["SubnetId"] = subnet_id
        if security_group_id:
            nic["Groups"] = [security_group_id]
        kwargs["NetworkInterfaces"] = [nic]

        async with self._session.client("ec2") as ec2:
            try:
                response = await ec2.run_instances(**kwargs)
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"RunInstances failed: {exc}") from exc
        instances = response.get("Instances") or []
        if not instances:
            raise AwsTransportError("RunInstances returned no instances")
        return str(instances[0]["InstanceId"])

    async def wait_for_running_with_ip(self, instance_id: str) -> str:
        deadline = time.monotonic() + _RUN_TO_IP_TIMEOUT_SECONDS
        async with self._session.client("ec2") as ec2:
            while True:
                try:
                    response = await ec2.describe_instances(InstanceIds=[instance_id])
                except (ClientError, BotoCoreError) as exc:
                    raise AwsTransportError(f"DescribeInstances failed: {exc}") from exc
                reservations = response.get("Reservations") or []
                instances = reservations[0]["Instances"] if reservations else []
                instance = instances[0] if instances else None
                if (
                    instance
                    and instance["State"]["Name"] == "running"
                    and (public_ip := instance.get("PublicIpAddress"))
                ):
                    return public_ip
                if time.monotonic() >= deadline:
                    raise AwsTransportError(
                        f"instance {instance_id} did not reach running with a "
                        f"public IP within {_RUN_TO_IP_TIMEOUT_SECONDS}s",
                    )
                await asyncio.sleep(_RUN_TO_IP_POLL_SECONDS)

    async def find_instance_id_by_tag_name(self, name: str, *, managed_by: str) -> str | None:
        async with self._session.client("ec2") as ec2:
            try:
                response = await ec2.describe_instances(
                    Filters=[
                        {"Name": "tag:Name", "Values": [name]},
                        {"Name": "tag:managed-by", "Values": [managed_by]},
                        {
                            "Name": "instance-state-name",
                            "Values": ["pending", "running", "stopping", "stopped"],
                        },
                    ]
                )
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"DescribeInstances failed: {exc}") from exc
        for reservation in response.get("Reservations") or []:
            for instance in reservation.get("Instances") or []:
                return str(instance["InstanceId"])
        return None

    async def terminate_instance(self, instance_id: str) -> None:
        async with self._session.client("ec2") as ec2:
            try:
                await ec2.terminate_instances(InstanceIds=[instance_id])
            except (ClientError, BotoCoreError) as exc:
                if (
                    getattr(exc, "response", {}).get("Error", {}).get("Code")
                    == "InvalidInstanceID.NotFound"
                ):
                    raise AwsVMNotFoundError(instance_id) from exc
                raise AwsTransportError(f"TerminateInstances failed: {exc}") from exc

    async def import_key_pair(
        self,
        *,
        key_name: str,
        public_key_openssh: str,
        tags: dict[str, str],
    ) -> None:
        async with self._session.client("ec2") as ec2:
            try:
                await ec2.import_key_pair(
                    KeyName=key_name,
                    PublicKeyMaterial=public_key_openssh.encode("utf-8"),
                    TagSpecifications=[
                        {"ResourceType": "key-pair", "Tags": _to_tag_list(tags)},
                    ],
                )
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"ImportKeyPair failed: {exc}") from exc

    async def delete_key_pair(self, key_name: str) -> None:
        async with self._session.client("ec2") as ec2:
            try:
                await ec2.delete_key_pair(KeyName=key_name)
            except (ClientError, BotoCoreError) as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if code == "InvalidKeyPair.NotFound":
                    return
                logger.warning("delete_key_pair %s failed: %s", key_name, exc)

    async def resolve_ssm_parameter(self, name: str) -> str:
        # Resolve every call, never cache: an SSM "current" path rotates to a
        # fresh AMI every few weeks, and a long-lived process must follow it.
        # GetParameter is cheap next to the EC2 launch this feeds.
        async with self._session.client("ssm") as ssm:
            try:
                response = await ssm.get_parameter(Name=name)
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"SSM GetParameter failed: {exc}") from exc
        return str(response["Parameter"]["Value"])

    async def get_caller_identity(self) -> dict[str, str]:
        async with self._session.client("sts") as sts:
            try:
                response = await sts.get_caller_identity()
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"GetCallerIdentity failed: {exc}") from exc
        return {
            "account": str(response.get("Account", "")),
            "arn": str(response.get("Arn", "")),
        }

    async def resolve_subnet_vpc(self, subnet_id: str) -> str:
        async with self._session.client("ec2") as ec2:
            try:
                response = await ec2.describe_subnets(SubnetIds=[subnet_id])
            except (ClientError, BotoCoreError) as exc:
                raise AwsTransportError(f"DescribeSubnets failed: {exc}") from exc
        subnets = response.get("Subnets") or []
        if not subnets:
            raise AwsTransportError(f"subnet not found: {subnet_id}")
        return str(subnets[0]["VpcId"])

    async def ensure_managed_security_group(
        self,
        *,
        name: str,
        description: str,
        vpc_id: str | None,
        ingress_cidrs: tuple[str, ...],
        tags: dict[str, str],
    ) -> str:
        async with self._session.client("ec2") as ec2:
            sg_id = await _find_sg_by_name(ec2, name=name, vpc_id=vpc_id)
            if sg_id is None:
                create_kwargs: dict[str, Any] = {
                    "GroupName": name,
                    "Description": description,
                    "TagSpecifications": [
                        {"ResourceType": "security-group", "Tags": _to_tag_list(tags)},
                    ],
                }
                if vpc_id:
                    create_kwargs["VpcId"] = vpc_id
                try:
                    created = await ec2.create_security_group(**create_kwargs)
                    sg_id = str(created["GroupId"])
                except (ClientError, BotoCoreError) as exc:
                    # A concurrent first launch can create the group between our
                    # describe and create; re-describe and continue. Same
                    # idempotent treatment as duplicate ingress rules below.
                    if (
                        getattr(exc, "response", {}).get("Error", {}).get("Code")
                        == "InvalidGroup.Duplicate"
                    ):
                        sg_id = await _find_sg_by_name(ec2, name=name, vpc_id=vpc_id)
                    if sg_id is None:
                        raise AwsTransportError(f"CreateSecurityGroup failed: {exc}") from exc
            if ingress_cidrs:
                await _reconcile_ssh_ingress(ec2, sg_id, ingress_cidrs)
            return sg_id
