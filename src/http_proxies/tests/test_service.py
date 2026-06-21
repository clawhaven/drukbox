import uuid
from unittest.mock import AsyncMock

import pytest
from uuid6 import uuid7

from core.database import async_session_factory
from hosts.exceptions import HostStateError
from hosts.models import Host, HostStatus
from hosts.service import HostService, utc_now
from http_proxies.exceptions import HTTPProxyExistsError, HTTPProxyNotFoundError
from http_proxies.service import HTTPProxyService
from providers.exceptions import (
    ProviderHttpProxyExistsError,
    ProviderHttpProxyNotFoundError,
    ProviderTargetVMNotFoundError,
)
from providers.exe.settings import ExeSettings


async def test_create_http_proxy_calls_exe_without_attachment(monkeypatch):
    mocked_create = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.create_http_proxy", mocked_create)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)
        await service.create_http_proxy(
            name="gmail-mcp",
            target="https://gmailmcp.googleapis.com",
            headers={"Authorization": "Bearer token"},
        )

    mocked_create.assert_awaited_once_with(
        name="gmail-mcp",
        target="https://gmailmcp.googleapis.com",
        headers={"Authorization": "Bearer token"},
    )


async def test_create_http_proxy_maps_already_exists(monkeypatch):
    monkeypatch.setattr(
        "providers.exe.provider.ExeProvider.create_http_proxy",
        AsyncMock(side_effect=ProviderHttpProxyExistsError("exists")),
    )

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HTTPProxyExistsError):
            await service.create_http_proxy(
                name="gmail-mcp",
                target="https://gmailmcp.googleapis.com",
                headers={"Authorization": "Bearer token"},
            )


async def test_attach_http_proxy_uses_host_vm_name(monkeypatch):
    mocked_attach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", mocked_attach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)
        await service.attach_http_proxy("gmail-mcp", host.id)

    mocked_attach.assert_awaited_once_with("gmail-mcp", attach_vm="lb-sandbox-test")


async def test_detach_http_proxy_uses_host_vm_name(monkeypatch):
    mocked_detach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.detach_http_proxy", mocked_detach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)
        await service.detach_http_proxy("gmail-mcp", host.id)

    mocked_detach.assert_awaited_once_with("gmail-mcp", attach_vm="lb-sandbox-test")


async def test_detach_http_proxy_maps_not_found(monkeypatch):
    monkeypatch.setattr(
        "providers.exe.provider.ExeProvider.detach_http_proxy",
        AsyncMock(side_effect=ProviderHttpProxyNotFoundError("missing")),
    )
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HTTPProxyNotFoundError):
            await service.detach_http_proxy("gmail-mcp", host.id)


async def test_attach_http_proxy_rejects_non_vm_host_state(monkeypatch):
    mocked_attach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", mocked_attach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.CREATING_VM.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HostStateError, match="host does not have a backing VM"):
            await service.attach_http_proxy("gmail-mcp", host.id)

    mocked_attach.assert_not_awaited()


async def test_attach_http_proxy_rejects_error_state(monkeypatch):
    mocked_attach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", mocked_attach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ERROR.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HostStateError, match="host does not have a backing VM"):
            await service.attach_http_proxy("gmail-mcp", host.id)

    mocked_attach.assert_not_awaited()


async def test_attach_http_proxy_maps_missing_vm_to_host_state(monkeypatch):
    monkeypatch.setattr(
        "providers.exe.provider.ExeProvider.attach_http_proxy",
        AsyncMock(side_effect=ProviderTargetVMNotFoundError("missing vm")),
    )
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HostStateError, match="host does not have a backing VM"):
            await service.attach_http_proxy("gmail-mcp", host.id)


async def test_detach_http_proxy_maps_missing_vm_to_host_state(monkeypatch):
    monkeypatch.setattr(
        "providers.exe.provider.ExeProvider.detach_http_proxy",
        AsyncMock(side_effect=ProviderTargetVMNotFoundError("missing vm")),
    )
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    async with async_session_factory() as session:
        service = HTTPProxyService(session)

        with pytest.raises(HostStateError, match="host does not have a backing VM"):
            await service.detach_http_proxy("gmail-mcp", host.id)


async def test_delete_host_does_not_call_proxy_cleanup(monkeypatch):
    mocked_delete_proxy = AsyncMock()
    mocked_delete_device = AsyncMock()
    mocked_delete_vm = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.delete_http_proxy", mocked_delete_proxy)
    monkeypatch.setattr("networking.tailscale.Tailscale.release_device", mocked_delete_device)
    monkeypatch.setattr("providers.exe.provider.ExeProvider.delete_vm", mocked_delete_vm)
    host = await create_host_record(
        name="lb-sandbox-test",
        status=HostStatus.ACTIVE.value,
        tailscale_device_id="n123CNTRL",
    )

    async with async_session_factory() as session:
        service = HostService(session)
        await service.delete_host(host.id)

    mocked_delete_proxy.assert_not_awaited()
    mocked_delete_device.assert_awaited_once_with("n123CNTRL")
    mocked_delete_vm.assert_awaited_once_with("lb-sandbox-test")


async def create_host_record(
    *,
    id: uuid.UUID | None = None,
    name: str,
    status: str,
    tailscale_device_id: str | None = None,
) -> Host:
    now = utc_now()
    host = Host(
        id=id or uuid7(),
        name=name,
        status=status,
        provider="exe",
        image=ExeSettings().default_image,  # pyright: ignore[reportCallIssue]
        env={},
        internal_ssh_host=f"{name}.example.ts.net",
        external_ssh_host="",
        external_ssh_port=22,
        known_hosts="",
        tailscale_device_id=tailscale_device_id,
        created_at=now,
        updated_at=now,
        activated_at=now if status == HostStatus.ACTIVE.value else None,
        last_error="provider error" if status == HostStatus.ERROR.value else "",
    )

    async with async_session_factory() as session:
        session.add(host)
        await session.commit()

    return host
