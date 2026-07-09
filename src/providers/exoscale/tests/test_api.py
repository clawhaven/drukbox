import base64
import json

import httpx
import pytest
import respx

from providers.exoscale.api import ExoscaleAPI
from providers.exoscale.exceptions import ExoscaleTransportError, ExoscaleVMNotFoundError

ZONE = "ch-gva-2"
BASE_URL = f"https://api-{ZONE}.exoscale.com/v2"


def _api() -> ExoscaleAPI:
    return ExoscaleAPI(
        api_key="EXO123",
        api_secret="secret-value",
        zone=ZONE,
        default_image="Linux Ubuntu 24.04 LTS 64-bit",
        instance_type="standard.medium",
        disk_gb=50,
    )


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_ensure_ssh_key_creates_when_absent(respx_mock):
    respx_mock.get("/ssh-key/drukbox-sb").mock(
        return_value=httpx.Response(404, json={"message": "not found"}),
    )
    create = respx_mock.post("/ssh-key").mock(
        return_value=httpx.Response(201, json={"id": "key-1", "name": "drukbox-sb"}),
    )

    await _api().ensure_ssh_key(
        name="drukbox-sb",
        public_key="ssh-ed25519 AAAA",
        labels={"managed-by": "drukbox"},
    )

    body = json.loads(create.calls.last.request.read())
    assert body == {
        "name": "drukbox-sb",
        "public-key": "ssh-ed25519 AAAA",
        "labels": {"managed-by": "drukbox"},
    }
    assert create.calls.last.request.headers["authorization"].startswith(
        "EXO2-HMAC-SHA256 credential="
    )


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL, assert_all_called=False)
async def test_ensure_ssh_key_reuses_existing(respx_mock):
    respx_mock.get("/ssh-key/drukbox-sb").mock(
        return_value=httpx.Response(200, json={"id": "key-1", "name": "drukbox-sb"}),
    )
    create = respx_mock.post("/ssh-key")

    await _api().ensure_ssh_key(name="drukbox-sb", public_key="ssh-ed25519 AAAA", labels={})

    assert not create.called


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_posts_body_and_returns_id(respx_mock):
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(202, json={"reference": {"id": "i-12345"}}),
    )

    instance_id = await _api().create_instance(
        name="sb-test",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="drukbox-sb-test",
        user_data="#!/bin/sh\necho hi",
        labels={"managed-by": "drukbox"},
    )

    assert instance_id == "i-12345"
    body = json.loads(route.calls.last.request.read())
    assert body["name"] == "sb-test"
    assert body["disk-size"] == 50
    assert body["template"] == {"name": "Linux Ubuntu 24.04 LTS 64-bit"}
    assert body["instance-type"] == {"name": "standard.medium"}
    assert body["zone"] == ZONE
    assert body["ssh-key"] == {"name": "drukbox-sb-test"}
    assert body["labels"] == {"managed-by": "drukbox"}
    assert base64.standard_b64decode(body["user-data"]).decode("utf-8") == "#!/bin/sh\necho hi"


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_prefers_explicit_instance_type(respx_mock):
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(202, json={"reference": {"id": "i-1"}}),
    )

    await _api().create_instance(
        name="sb",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="k",
        user_data="",
        labels={},
        instance_type="standard.large",
    )

    body = json.loads(route.calls.last.request.read())
    assert body["instance-type"] == {"name": "standard.large"}


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_prefers_explicit_disk_gb(respx_mock):
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(202, json={"reference": {"id": "i-1"}}),
    )

    await _api().create_instance(
        name="sb",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="k",
        user_data="",
        labels={},
        disk_gb=80,
    )

    body = json.loads(route.calls.last.request.read())
    assert body["disk-size"] == 80


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_omits_user_data_when_empty(respx_mock):
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(202, json={"reference": {"id": "i-1"}}),
    )

    await _api().create_instance(
        name="sb",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="k",
        user_data="",
        labels={},
    )

    body = json.loads(route.calls.last.request.read())
    assert "user-data" not in body


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_wait_for_running_with_ip_polls_until_running(respx_mock):
    respx_mock.get("/instance/i-5").mock(
        side_effect=[
            httpx.Response(200, json={"state": "initializing"}),
            httpx.Response(200, json={"state": "running", "public-ip": "203.0.113.9"}),
        ],
    )

    assert await _api().wait_for_running_with_ip("i-5") == "203.0.113.9"


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_find_instance_id_by_name_returns_none_when_absent(respx_mock):
    respx_mock.get("/instance").mock(return_value=httpx.Response(200, json={"instances": []}))
    assert await _api().find_instance_id_by_name("sb-missing") is None


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_delete_instance_swallows_404(respx_mock):
    respx_mock.delete("/instance/i-7").mock(
        return_value=httpx.Response(404, json={"message": "gone"}),
    )
    await _api().delete_instance("i-7")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_delete_ssh_key_swallows_404_delete_race(respx_mock):
    respx_mock.delete("/ssh-key/drukbox-sb").mock(
        return_value=httpx.Response(404, json={"message": "gone"}),
    )

    await _api().delete_ssh_key("drukbox-sb")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_request_maps_4xx_to_transport_error(respx_mock):
    respx_mock.get("/instance").mock(
        return_value=httpx.Response(401, json={"message": "bad credentials"}),
    )
    with pytest.raises(ExoscaleTransportError, match="bad credentials"):
        await _api().find_instance_id_by_name("sb")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_request_maps_404_to_not_found(respx_mock):
    respx_mock.get("/instance/i-3").mock(
        return_value=httpx.Response(404, json={"message": "missing"}),
    )
    with pytest.raises(ExoscaleVMNotFoundError):
        await _api().wait_for_running_with_ip("i-3")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_list_instances_count_reads_total(respx_mock):
    respx_mock.get("/instance").mock(
        return_value=httpx.Response(200, json={"instances": [], "total": 4}),
    )
    assert await _api().list_instances_count() == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("public_ip", [{}, None, {"public-ip": None}])
@respx.mock(base_url=BASE_URL)
async def test_wait_for_running_with_ip_raises_when_running_without_ipv4(
    respx_mock, monkeypatch, public_ip
):
    monkeypatch.setattr("providers.exoscale.api._RUN_TO_IP_TIMEOUT_SECONDS", 0)
    body = {"state": "running"}
    if isinstance(public_ip, dict):
        body.update(public_ip)
    respx_mock.get("/instance/i-5").mock(return_value=httpx.Response(200, json=body))

    with pytest.raises(ExoscaleTransportError, match="public IP"):
        await _api().wait_for_running_with_ip("i-5")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_authorization_header_matches_reference_fixture(respx_mock, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1_699_999_400.0)
    expected = (
        "EXO2-HMAC-SHA256 credential=EXO123,expires=1700000000,"
        "signature=1GojVvs6vYrqytp/HhhjEmCKgOtSmUp2ObCJNfTizAI="
    )
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(202, json={"reference": {"id": "i-12345"}}),
    )

    await _api().create_instance(
        name="sb-test",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="drukbox-sb-test",
        user_data="#!/bin/sh\necho hi",
        labels={"managed-by": "drukbox"},
    )

    header = route.calls.last.request.headers["authorization"]
    assert header.startswith("EXO2-HMAC-SHA256 ")
    assert header == expected


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_authorization_header_matches_reference_fixture_with_query_args(
    respx_mock, monkeypatch
):
    monkeypatch.setattr("time.time", lambda: 1_699_999_400.0)
    expected = (
        "EXO2-HMAC-SHA256 credential=EXO123,signed-query-args=name;zone,"
        "expires=1700000000,signature=LdrDqX3RL8WKrHOSxqZ3ueR5PcwwEzjtwlOXWUThvUc="
    )
    route = respx_mock.get("/instance").mock(
        return_value=httpx.Response(200, json={"instances": [], "total": 0}),
    )

    await _api()._request("GET", "/instance", params={"zone": ZONE, "name": "sb-test"})

    header = route.calls.last.request.headers["authorization"]
    assert "signed-query-args=name;zone" in header
    assert header == expected
