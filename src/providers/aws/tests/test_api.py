from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from providers.aws.api import AwsAPI, _reconcile_ssh_ingress
from providers.aws.exceptions import AwsTransportError


def _sg_with_ssh_cidrs(*cidrs: str) -> MagicMock:
    ec2 = MagicMock()
    ec2.describe_security_groups = AsyncMock(
        return_value={
            "SecurityGroups": [
                {
                    "IpPermissions": [
                        {
                            "IpProtocol": "tcp",
                            "FromPort": 22,
                            "ToPort": 22,
                            "IpRanges": [{"CidrIp": cidr} for cidr in cidrs],
                        }
                    ]
                }
            ]
        }
    )
    ec2.authorize_security_group_ingress = AsyncMock()
    ec2.revoke_security_group_ingress = AsyncMock()
    return ec2


def _session_for(ec2: object) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=ec2)
    cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client.return_value = cm
    return session


async def test_ensure_security_group_resolves_concurrent_duplicate() -> None:
    # First describe misses, so we try to create — but a concurrent launch beat
    # us to it, so EC2 raises InvalidGroup.Duplicate. We must re-describe and
    # return the now-existing group instead of failing the provision.
    duplicate = ClientError(
        {"Error": {"Code": "InvalidGroup.Duplicate", "Message": "exists"}},
        "CreateSecurityGroup",
    )
    ec2 = MagicMock()
    ec2.describe_security_groups = AsyncMock(
        side_effect=[
            {"SecurityGroups": []},
            {"SecurityGroups": [{"GroupId": "sg-123"}]},
        ]
    )
    ec2.create_security_group = AsyncMock(side_effect=duplicate)

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    sg_id = await api.ensure_managed_security_group(
        name="drukbox-managed",
        description="ssh",
        vpc_id=None,
        ingress_cidrs=(),
        tags={"managed-by": "drukbox"},
    )

    assert sg_id == "sg-123"
    assert ec2.describe_security_groups.await_count == 2


async def test_run_instance_passes_raw_user_data() -> None:
    # botocore base64-encodes UserData for RunInstances itself, so AwsAPI must
    # hand it the raw script. Pre-encoding would double-encode and break cloud-init.
    script = "#!/bin/sh\nexport FOO=bar\n"
    ec2 = MagicMock()
    ec2.run_instances = AsyncMock(return_value={"Instances": [{"InstanceId": "i-abc"}]})

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    await api.run_instance(
        client_token="sb-1",
        ami_id="ami-1",
        instance_type="t3.medium",
        key_name=None,
        root_gb=20,
        tags={"managed-by": "drukbox"},
        user_data=script,
        associate_public_ip=False,
        subnet_id=None,
        security_group_id=None,
        instance_profile=None,
    )

    assert ec2.run_instances.await_args.kwargs["UserData"] == script


async def test_resolve_subnet_vpc_returns_vpc_id() -> None:
    ec2 = MagicMock()
    ec2.describe_subnets = AsyncMock(return_value={"Subnets": [{"VpcId": "vpc-abc"}]})

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    assert await api.resolve_subnet_vpc("subnet-xyz") == "vpc-abc"
    ec2.describe_subnets.assert_awaited_once_with(SubnetIds=["subnet-xyz"])


async def test_resolve_subnet_vpc_raises_when_subnet_missing() -> None:
    ec2 = MagicMock()
    ec2.describe_subnets = AsyncMock(return_value={"Subnets": []})

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    with pytest.raises(AwsTransportError, match="subnet not found"):
        await api.resolve_subnet_vpc("subnet-gone")


async def test_reconcile_revokes_stale_and_adds_missing() -> None:
    # The SG was created with the world-open fallback; tightening to a /8 must
    # add the new rule AND revoke the stale 0.0.0.0/0, or SSH stays world-open.
    ec2 = _sg_with_ssh_cidrs("0.0.0.0/0")

    await _reconcile_ssh_ingress(ec2, "sg-1", ("10.0.0.0/8",))

    added = ec2.authorize_security_group_ingress.await_args.kwargs["IpPermissions"][0]
    assert added["IpRanges"] == [{"CidrIp": "10.0.0.0/8"}]
    revoked = ec2.revoke_security_group_ingress.await_args.kwargs["IpPermissions"][0]
    assert revoked["IpRanges"] == [{"CidrIp": "0.0.0.0/0"}]


async def test_reconcile_is_noop_when_ingress_already_matches() -> None:
    ec2 = _sg_with_ssh_cidrs("10.0.0.0/8")

    await _reconcile_ssh_ingress(ec2, "sg-1", ("10.0.0.0/8",))

    ec2.authorize_security_group_ingress.assert_not_called()
    ec2.revoke_security_group_ingress.assert_not_called()


async def test_wait_for_running_with_ip_waits_for_public_ip(monkeypatch) -> None:
    # Running with no PublicIpAddress yet is intermediate: keep polling rather
    # than returning an empty ssh_host that bootstrap can't use.
    monkeypatch.setattr("providers.aws.api.asyncio.sleep", AsyncMock())
    ec2 = MagicMock()
    ec2.describe_instances = AsyncMock(
        side_effect=[
            {"Reservations": [{"Instances": [{"State": {"Name": "pending"}}]}]},
            {"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]},
            {
                "Reservations": [
                    {
                        "Instances": [
                            {"State": {"Name": "running"}, "PublicIpAddress": "203.0.113.7"}
                        ]
                    }
                ]
            },
        ]
    )

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    assert await api.wait_for_running_with_ip("i-1") == "203.0.113.7"
    assert ec2.describe_instances.await_count == 3


async def test_wait_for_running_with_ip_times_out_without_public_ip(monkeypatch) -> None:
    monkeypatch.setattr("providers.aws.api._RUN_TO_IP_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr("providers.aws.api.asyncio.sleep", AsyncMock())
    ec2 = MagicMock()
    ec2.describe_instances = AsyncMock(
        return_value={"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]}
    )

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    with pytest.raises(AwsTransportError, match="public IP"):
        await api.wait_for_running_with_ip("i-1")


async def test_run_instance_wraps_non_client_botocore_errors() -> None:
    # NoCredentialsError is a BotoCoreError, not a ClientError; it must still be
    # translated to AwsTransportError instead of escaping the provider boundary.
    from botocore.exceptions import NoCredentialsError

    ec2 = MagicMock()
    ec2.run_instances = AsyncMock(side_effect=NoCredentialsError())

    api = AwsAPI(_session_for(ec2), region="us-east-1")
    with pytest.raises(AwsTransportError, match="RunInstances failed"):
        await api.run_instance(
            client_token="sb-1",
            ami_id="ami-1",
            instance_type="t3.medium",
            key_name=None,
            root_gb=20,
            tags={"managed-by": "drukbox"},
            user_data="x",
            associate_public_ip=False,
            subnet_id=None,
            security_group_id=None,
            instance_profile=None,
        )
