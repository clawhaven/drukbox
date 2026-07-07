import httpx
import pytest
import respx

from providers.hetzner.api import HetznerAPI
from providers.hetzner.exceptions import HetznerTransportError, HetznerVMNotFoundError

BASE_URL = "https://api.hetzner.cloud/v1"


def _api() -> HetznerAPI:
    return HetznerAPI(
        token="token",
        default_image="ubuntu-24.04",
        location="nbg1",
        server_type="cx23",
    )


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_ensure_ssh_key_creates_when_absent(respx_mock):
    respx_mock.get("/ssh_keys").mock(return_value=httpx.Response(200, json={"ssh_keys": []}))
    create = respx_mock.post("/ssh_keys").mock(
        return_value=httpx.Response(201, json={"ssh_key": {"id": 1, "name": "drukbox-sb"}}),
    )

    await _api().ensure_ssh_key(name="drukbox-sb", public_key="ssh-ed25519 AAAA", labels={})

    assert create.called
    assert create.calls.last.request.headers["authorization"] == "Bearer token"


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL, assert_all_called=False)
async def test_ensure_ssh_key_reuses_existing(respx_mock):
    respx_mock.get("/ssh_keys").mock(
        return_value=httpx.Response(200, json={"ssh_keys": [{"id": 1, "name": "drukbox-sb"}]}),
    )
    create = respx_mock.post("/ssh_keys")

    await _api().ensure_ssh_key(name="drukbox-sb", public_key="ssh-ed25519 AAAA", labels={})

    assert not create.called


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_server_posts_body_and_returns_id(respx_mock):
    route = respx_mock.post("/servers").mock(
        return_value=httpx.Response(201, json={"server": {"id": 999}}),
    )

    server_id = await _api().create_server(
        name="sb-test",
        image="ubuntu-24.04",
        ssh_key_name="drukbox-sb-test",
        user_data="#!/bin/sh\necho hi",
        labels={"managed-by": "drukbox"},
    )

    assert server_id == "999"
    body = route.calls.last.request.read()
    assert b'"server_type":"cx23"' in body
    assert b'"location":"nbg1"' in body
    assert b'"image":"ubuntu-24.04"' in body


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_server_prefers_explicit_server_type(respx_mock):
    route = respx_mock.post("/servers").mock(
        return_value=httpx.Response(201, json={"server": {"id": 1}}),
    )

    await _api().create_server(
        name="sb",
        image="ubuntu-24.04",
        ssh_key_name="k",
        user_data="",
        labels={},
        server_type="cx33",
    )

    assert b'"server_type":"cx33"' in route.calls.last.request.read()


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_server_omits_user_data_when_empty(respx_mock):
    route = respx_mock.post("/servers").mock(
        return_value=httpx.Response(201, json={"server": {"id": 1}}),
    )

    await _api().create_server(
        name="sb", image="ubuntu-24.04", ssh_key_name="k", user_data="", labels={}
    )
    assert b"user_data" not in route.calls.last.request.read()


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_wait_for_running_with_ip_polls_until_running(respx_mock):
    respx_mock.get("/servers/5").mock(
        side_effect=[
            httpx.Response(200, json={"server": {"status": "initializing", "public_net": {}}}),
            httpx.Response(
                200,
                json={
                    "server": {"status": "running", "public_net": {"ipv4": {"ip": "203.0.113.9"}}},
                },
            ),
        ],
    )

    assert await _api().wait_for_running_with_ip("5") == "203.0.113.9"


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_find_server_id_by_name_returns_none_when_absent(respx_mock):
    respx_mock.get("/servers").mock(return_value=httpx.Response(200, json={"servers": []}))
    assert await _api().find_server_id_by_name("sb-missing") is None


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_delete_server_swallows_404(respx_mock):
    respx_mock.delete("/servers/7").mock(
        return_value=httpx.Response(404, json={"error": {"code": "not_found", "message": "gone"}}),
    )
    await _api().delete_server("7")  # must not raise


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_request_maps_4xx_to_transport_error(respx_mock):
    respx_mock.get("/servers").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "bad token"}}
        ),
    )
    with pytest.raises(HetznerTransportError, match="bad token"):
        await _api().find_server_id_by_name("sb")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_request_maps_404_to_not_found(respx_mock):
    respx_mock.get("/servers/3").mock(
        return_value=httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}}),
    )
    with pytest.raises(HetznerVMNotFoundError):
        await _api().wait_for_running_with_ip("3")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_count_servers_reads_total_entries(respx_mock):
    respx_mock.get("/servers").mock(
        return_value=httpx.Response(
            200, json={"servers": [], "meta": {"pagination": {"total_entries": 4}}}
        ),
    )
    assert await _api().count_servers() == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("public_net", [{}, None, {"ipv4": None}, {"ipv4": {"ip": None}}])
@respx.mock(base_url=BASE_URL)
async def test_wait_for_running_with_ip_raises_when_running_without_ipv4(
    respx_mock, monkeypatch, public_net
):
    # A running server can lack IPv4 via a missing key (KeyError) or a JSON null
    # mid-path (TypeError); both must surface as a neutral HetznerTransportError.
    monkeypatch.setattr("providers.hetzner.api._RUN_TO_IP_TIMEOUT_SECONDS", 0)
    respx_mock.get("/servers/5").mock(
        return_value=httpx.Response(
            200, json={"server": {"status": "running", "public_net": public_net}}
        ),
    )

    with pytest.raises(HetznerTransportError, match="public IP"):
        await _api().wait_for_running_with_ip("5")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_delete_ssh_key_swallows_404_delete_race(respx_mock):
    # The key is listed by GET but already gone by DELETE (404 race); that must
    # not raise, so a teardown race can't abort the rest of VM deletion.
    respx_mock.get("/ssh_keys").mock(
        return_value=httpx.Response(200, json={"ssh_keys": [{"id": 7, "name": "drukbox-sb"}]}),
    )
    respx_mock.delete("/ssh_keys/7").mock(
        return_value=httpx.Response(404, json={"error": {"code": "not_found", "message": "gone"}}),
    )

    await _api().delete_ssh_key("drukbox-sb")  # must not raise
