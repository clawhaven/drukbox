import asyncio
import contextlib
import time
from typing import Any, Self

import httpx

from .exceptions import HetznerTransportError, HetznerVMNotFoundError
from .settings import HetznerSettings

_RUN_TO_IP_TIMEOUT_SECONDS = 300
_RUN_TO_IP_POLL_SECONDS = 3.0


class HetznerAPI:
    base_url = "https://api.hetzner.cloud/v1"

    def __init__(
        self,
        *,
        token: str,
        default_image: str,
        location: str,
        server_type: str,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.token = token
        self.default_image = default_image
        self.location = location
        self.server_type = server_type
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, settings: HetznerSettings) -> Self:
        return cls(
            token=settings.api_token,
            default_image=settings.default_image,
            location=settings.location,
            server_type=settings.server_type,
            timeout=settings.api_timeout,
        )

    async def ensure_ssh_key(self, *, name: str, public_key: str, labels: dict[str, str]) -> None:
        # Hetzner's name filter is exact, so a non-empty result means the key
        # already exists and can be reused.
        existing = await self._request("GET", "/ssh_keys", params={"name": name})
        if existing["ssh_keys"]:
            return
        await self._request(
            "POST",
            "/ssh_keys",
            json={"name": name, "public_key": public_key, "labels": labels},
        )

    async def delete_ssh_key(self, name: str) -> None:
        existing = await self._request("GET", "/ssh_keys", params={"name": name})
        keys = existing["ssh_keys"]
        if keys:
            with contextlib.suppress(HetznerVMNotFoundError):
                # A list/delete race (the key was removed between GET and DELETE)
                # makes DELETE 404; treat it as success, like delete_server, so a
                # race can't abort the rest of VM teardown.
                await self._request("DELETE", f"/ssh_keys/{keys[0]['id']}")

    async def create_server(
        self,
        *,
        name: str,
        image: str,
        ssh_key_name: str,
        user_data: str,
        labels: dict[str, str],
        server_type: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "name": name,
            "server_type": server_type or self.server_type,
            "image": image,
            "location": self.location,
            "ssh_keys": [ssh_key_name],
            "labels": labels,
            "start_after_create": True,
            "public_net": {"enable_ipv4": True, "enable_ipv6": False},
        }
        if user_data:
            body["user_data"] = user_data
        response = await self._request("POST", "/servers", json=body)
        return str(response["server"]["id"])

    async def wait_for_running_with_ip(self, server_id: str) -> str:
        deadline = time.monotonic() + _RUN_TO_IP_TIMEOUT_SECONDS
        while True:
            server = (await self._request("GET", f"/servers/{server_id}"))["server"]
            if server["status"] == "running":
                # A running server can briefly lack IPv4 (missing key, or a JSON
                # null mid-path). Suppress KeyError and TypeError so a structural
                # gap means "not ready" and we keep waiting, rather than raising
                # past the provider's neutral-error boundary.
                ip = None
                with contextlib.suppress(KeyError, TypeError):
                    ip = server["public_net"]["ipv4"]["ip"]
                if ip:
                    return ip
            if time.monotonic() >= deadline:
                raise HetznerTransportError(
                    f"server {server_id} did not reach running with a public IP "
                    f"within {_RUN_TO_IP_TIMEOUT_SECONDS}s",
                )
            await asyncio.sleep(_RUN_TO_IP_POLL_SECONDS)

    async def find_server_id_by_name(self, name: str) -> str | None:
        response = await self._request("GET", "/servers", params={"name": name})
        servers = response["servers"]
        if not servers:
            return None
        return str(servers[0]["id"])

    async def delete_server(self, server_id: str) -> None:
        try:
            await self._request("DELETE", f"/servers/{server_id}")
        except HetznerVMNotFoundError:
            # Idempotent teardown: a 404 means the server is already gone, which
            # is the caller's intent. Operator cleanup can also race us.
            return

    async def count_servers(self) -> int:
        response = await self._request("GET", "/servers", params={"per_page": "1"})
        return int(response["meta"]["pagination"]["total_entries"])

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
            raise HetznerTransportError(f"Hetzner API transport failed: {exc}") from exc

        if response.status_code == 404:
            raise HetznerVMNotFoundError(_error_message(response))

        if response.status_code >= 400:
            raise HetznerTransportError(
                f"Hetzner API request failed with status {response.status_code}: "
                f"{_error_message(response)}"
            )

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise HetznerTransportError("Hetzner API returned non-JSON output") from exc

    def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return response.text.strip() or f"status {response.status_code}"
