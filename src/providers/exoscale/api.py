import asyncio
import base64
import contextlib
import hashlib
import hmac
import time
from collections.abc import Generator
from typing import Any, Self
from urllib.parse import parse_qs

import httpx

from .exceptions import ExoscaleTransportError, ExoscaleVMNotFoundError
from .settings import ExoscaleSettings

_RUN_TO_IP_TIMEOUT_SECONDS = 300
_RUN_TO_IP_POLL_SECONDS = 3.0
_SIGNATURE_TTL_SECONDS = 600


class ExoscaleAuth(httpx.Auth):
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        expires = int(time.time()) + _SIGNATURE_TTL_SECONDS
        auth_header = f"EXO2-HMAC-SHA256 credential={self.api_key}"
        message_parts = [
            f"{request.method} {request.url.path}".encode(),
            _request_body(request),
        ]

        params = parse_qs(_query_string(request))
        signed_params = sorted(params)
        param_values = []
        for param in signed_params:
            if len(params[param]) != 1:
                continue
            param_values.append(params[param][0])
        message_parts.append("".join(param_values).encode("utf-8"))
        if signed_params:
            auth_header += f",signed-query-args={';'.join(signed_params)}"

        message_parts.append(b"")
        message_parts.append(str(expires).encode("utf-8"))
        auth_header += f",expires={expires}"

        signature = hmac.HMAC(
            self.api_secret,
            msg=b"\n".join(message_parts),
            digestmod=hashlib.sha256,
        ).digest()
        auth_header += f",signature={base64.standard_b64encode(signature).decode('utf-8')}"
        request.headers["Authorization"] = auth_header
        yield request


class ExoscaleAPI:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        zone: str,
        default_image: str,
        instance_type: str,
        disk_gb: int,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.zone = zone
        self.default_image = default_image
        self.instance_type = instance_type
        self.disk_gb = disk_gb
        self.base_url = f"https://api-{zone}.exoscale.com/v2"
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, settings: ExoscaleSettings) -> Self:
        return cls(
            api_key=settings.api_key,
            api_secret=settings.api_secret,
            zone=settings.zone,
            default_image=settings.default_image,
            instance_type=settings.instance_type,
            disk_gb=settings.disk_gb,
            timeout=settings.api_timeout,
        )

    async def ensure_ssh_key(self, *, name: str, public_key: str, labels: dict[str, str]) -> None:
        try:
            await self._request("GET", f"/ssh-key/{name}")
        except ExoscaleVMNotFoundError:
            await self._request(
                "POST",
                "/ssh-key",
                json={"name": name, "public-key": public_key},
            )

    async def delete_ssh_key(self, name: str) -> None:
        try:
            await self._request("DELETE", f"/ssh-key/{name}")
        except ExoscaleVMNotFoundError:
            return

    async def create_instance(
        self,
        *,
        name: str,
        image: str,
        ssh_key_name: str,
        user_data: str,
        labels: dict[str, str],
        instance_type: str | None = None,
        disk_gb: int | None = None,
        zone: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "name": name,
            "template": {"name": image},
            "instance-type": {"name": instance_type or self.instance_type},
            "zone": zone or self.zone,
            "disk-size": disk_gb or self.disk_gb,
            "ssh-key": {"name": ssh_key_name},
            "labels": labels,
        }
        if user_data:
            body["user-data"] = base64.standard_b64encode(user_data.encode("utf-8")).decode("utf-8")
        response = await self._request("POST", "/instance", json=body)
        return str(response["reference"]["id"])

    async def wait_for_running_with_ip(self, instance_id: str) -> str:
        deadline = time.monotonic() + _RUN_TO_IP_TIMEOUT_SECONDS
        while True:
            instance = await self._request("GET", f"/instance/{instance_id}")
            if instance["state"] == "running":
                ip = None
                with contextlib.suppress(KeyError, TypeError):
                    ip = instance["public-ip"]
                if ip:
                    return ip
            if time.monotonic() >= deadline:
                raise ExoscaleTransportError(
                    f"instance {instance_id} did not reach running with a public IP "
                    f"within {_RUN_TO_IP_TIMEOUT_SECONDS}s",
                )
            await asyncio.sleep(_RUN_TO_IP_POLL_SECONDS)

    async def find_instance_id_by_name(self, name: str) -> str | None:
        response = await self._request("GET", "/instance")
        for instance in response["instances"]:
            if instance.get("name") == name:
                return str(instance["id"])
        return None

    async def delete_instance(self, instance_id: str) -> None:
        try:
            await self._request("DELETE", f"/instance/{instance_id}")
        except ExoscaleVMNotFoundError:
            return

    async def list_instances_count(self) -> int:
        response = await self._request("GET", "/instance")
        return len(response["instances"])

    async def aclose(self) -> None:
        if not self._client:
            return
        await self._client.aclose()
        self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._get_client().request(method, path, params=params, json=json)
        except httpx.RequestError as exc:
            raise ExoscaleTransportError(f"Exoscale API transport failed: {exc}") from exc

        if response.status_code == 404:
            raise ExoscaleVMNotFoundError(_error_message(response))

        if response.status_code >= 400:
            raise ExoscaleTransportError(
                f"Exoscale API request failed with status {response.status_code}: "
                f"{_error_message(response)}"
            )

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ExoscaleTransportError("Exoscale API returned non-JSON output") from exc

    def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                auth=ExoscaleAuth(self.api_key, self.api_secret),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client


def _request_body(request: httpx.Request) -> bytes:
    try:
        return request.content
    except httpx.RequestNotRead:
        return request.read()


def _query_string(request: httpx.Request) -> str:
    query = request.url.query
    if isinstance(query, bytes):
        return query.decode("utf-8")
    return query


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json()["message"]
        return str(error)
    except (ValueError, KeyError, TypeError):
        return response.text.strip() or f"status {response.status_code}"
