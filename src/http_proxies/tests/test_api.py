import uuid
from unittest.mock import AsyncMock

from uuid6 import uuid7

from core.database import async_session_factory
from core.settings import get_settings
from hosts.models import Host, HostStatus
from hosts.service import utc_now
from providers.exe.settings import ExeSettings


async def test_create_http_proxy_returns_created(client, monkeypatch):
    mocked_create = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.create_http_proxy", mocked_create)

    response = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://gmailmcp.googleapis.com",
            "headers": {"Authorization": "Bearer token"},
        },
    )

    assert response.status_code == 201
    assert response.json() == {"name": "gmail-mcp", "status": "created"}
    mocked_create.assert_awaited_once_with(
        name="gmail-mcp",
        target="https://gmailmcp.googleapis.com/",
        headers={"Authorization": "Bearer token"},
    )


async def test_http_proxy_returns_501_when_default_provider_lacks_capability(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "default_host_provider", "docker")

    response = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://gmailmcp.googleapis.com",
            "headers": {"Authorization": "Bearer token"},
        },
    )

    assert response.status_code == 501
    assert response.json()["error_code"] == "HTTP_PROXY_UNSUPPORTED"


async def test_attach_returns_501_when_host_provider_lacks_capability(client):
    host = await create_host_record(
        name="lb-sandbox-test",
        status=HostStatus.ACTIVE.value,
        provider="docker",
    )

    response = await client.post(
        f"/http-proxies/gmail-mcp/hosts/{host.id}",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 501
    assert response.json()["error_code"] == "HTTP_PROXY_UNSUPPORTED"


async def test_http_proxy_rejects_option_like_names(client, monkeypatch):
    # Leading-hyphen names could be parsed as exe.dev CLI options, so they must be
    # rejected (422) at every boundary before reaching the provider.
    blocked = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.create_http_proxy", blocked)
    monkeypatch.setattr("providers.exe.provider.ExeProvider.delete_http_proxy", blocked)
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", blocked)
    headers = {"Authorization": "Bearer service-token"}

    create = await client.post(
        "/http-proxies",
        headers=headers,
        json={"name": "--all", "target": "https://t.example.com", "headers": {"H": "v"}},
    )
    delete = await client.delete("/http-proxies/--all", headers=headers)
    attach = await client.post(f"/http-proxies/--all/hosts/{uuid.uuid4()}", headers=headers)

    assert create.status_code == 422
    assert delete.status_code == 422
    assert attach.status_code == 422
    blocked.assert_not_awaited()


async def test_create_http_proxy_rejects_invalid_payload(client):
    invalid_target = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "not-a-url",
            "headers": {"Authorization": "Bearer token"},
        },
    )
    invalid_headers_shape = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://gmailmcp.googleapis.com",
            "headers": ["Authorization: Bearer token"],
        },
    )
    invalid_target_path = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://gmailmcp.googleapis.com/mcp/v1",
            "headers": {"Authorization": "Bearer token"},
        },
    )

    invalid_target_userinfo = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer service-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://user:pass@gmailmcp.googleapis.com",
            "headers": {"Authorization": "Bearer token"},
        },
    )

    assert invalid_target.status_code == 422
    assert invalid_headers_shape.status_code == 422
    assert invalid_target_path.status_code == 422
    assert invalid_target_userinfo.status_code == 422
    detail = invalid_headers_shape.json()["detail"]
    assert detail[0]["loc"] == ["body", "headers"]
    assert invalid_target_path.json()["detail"][0]["loc"] == ["body", "target"]
    assert invalid_target_userinfo.json()["detail"][0]["loc"] == ["body", "target"]


async def test_create_http_proxy_rejects_missing_or_bad_service_auth(client):
    missing_response = await client.post("/http-proxies")
    bad_response = await client.post(
        "/http-proxies",
        headers={"Authorization": "Bearer wrong-token"},
        json={
            "name": "gmail-mcp",
            "target": "https://gmailmcp.googleapis.com",
            "headers": {"Authorization": "Bearer token"},
        },
    )

    assert missing_response.status_code == 401
    assert bad_response.status_code == 403


async def test_delete_http_proxy_returns_no_content(client, monkeypatch):
    mocked_delete = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.delete_http_proxy", mocked_delete)

    response = await client.delete(
        "/http-proxies/gmail-mcp",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 204
    assert response.content == b""
    mocked_delete.assert_awaited_once_with("gmail-mcp")


async def test_attach_http_proxy_to_host_returns_attached(client, monkeypatch):
    mocked_attach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", mocked_attach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    response = await client.post(
        f"/http-proxies/gmail-mcp/hosts/{host.id}",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "gmail-mcp",
        "host_id": str(host.id),
        "status": "attached",
    }
    mocked_attach.assert_awaited_once_with("gmail-mcp", attach_vm="lb-sandbox-test")


async def test_detach_http_proxy_from_host_returns_no_content(client, monkeypatch):
    mocked_detach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.detach_http_proxy", mocked_detach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ACTIVE.value)

    response = await client.delete(
        f"/http-proxies/gmail-mcp/hosts/{host.id}",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 204
    assert response.content == b""
    mocked_detach.assert_awaited_once_with("gmail-mcp", attach_vm="lb-sandbox-test")


async def test_attach_http_proxy_rejects_missing_host(client):
    host_id = uuid.UUID("00000000-0000-0000-0000-000000000141")

    response = await client.post(
        f"/http-proxies/gmail-mcp/hosts/{host_id}",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "host not found"


async def test_attach_http_proxy_rejects_non_vm_host_states(client):
    for index, host_status in enumerate(
        (
            HostStatus.PROVISIONING.value,
            HostStatus.CREATING_NETWORK.value,
            HostStatus.CREATING_VM.value,
        ),
        start=1,
    ):
        host = await create_host_record(name=f"lb-sandbox-test-{index}", status=host_status)

        response = await client.post(
            f"/http-proxies/gmail-mcp/hosts/{host.id}",
            headers={"Authorization": "Bearer service-token"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "host does not have a backing VM"


async def test_attach_http_proxy_rejects_error_state_host(client, monkeypatch):
    mocked_attach = AsyncMock()
    monkeypatch.setattr("providers.exe.provider.ExeProvider.attach_http_proxy", mocked_attach)
    host = await create_host_record(name="lb-sandbox-test", status=HostStatus.ERROR.value)

    response = await client.post(
        f"/http-proxies/gmail-mcp/hosts/{host.id}",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "host does not have a backing VM"
    mocked_attach.assert_not_awaited()


async def create_host_record(
    *,
    id: uuid.UUID | None = None,
    name: str,
    status: str,
    provider: str = "exe",
    tailscale_device_id: str | None = None,
) -> Host:
    now = utc_now()
    host = Host(
        id=id or uuid7(),
        name=name,
        status=status,
        provider=provider,
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
