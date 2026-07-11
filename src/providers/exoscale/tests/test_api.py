import base64
import json

import httpx
import pytest
import respx

from providers.exoscale.api import ExoscaleAPI
from providers.exoscale.exceptions import (
    ExoscaleProviderError,
    ExoscaleTransportError,
    ExoscaleVMNotFoundError,
)

ZONE = "ch-gva-2"
BASE_URL = f"https://api-{ZONE}.exoscale.com/v2"

UBUNTU_TEMPLATE_ID = "45e849e9-bee9-4a4a-b995-cae4e21a8c50"
MEDIUM_TYPE_ID = "b6e9d1e4-3c65-4c2e-8b0a-2f0f1d9c4a11"
LARGE_TYPE_ID = "350716c4-1770-4b9e-a4a1-7dd4e0a1cbcd"
CREATED_INSTANCE_ID = "0f6e9c26-6f2f-4a4b-8f0a-4c3f7b1d2e3c"


def _api() -> ExoscaleAPI:
    return ExoscaleAPI(
        api_key="EXO123",
        api_secret="secret-value",
        zone=ZONE,
        default_image="Linux Ubuntu 24.04 LTS 64-bit",
        instance_type="standard.medium",
        disk_gb=50,
    )


def _mock_resolver_lists(respx_mock) -> None:
    respx_mock.get("/template").mock(
        return_value=httpx.Response(
            200,
            json={
                "templates": [
                    {
                        "id": UBUNTU_TEMPLATE_ID,
                        "name": "Linux Ubuntu 24.04 LTS 64-bit",
                        "created-at": "2025-04-01T09:00:00Z",
                        "visibility": "public",
                    },
                ],
            },
        ),
    )
    _mock_instance_type_list(respx_mock)


def _mock_instance_type_list(respx_mock) -> None:
    respx_mock.get("/instance-type").mock(
        return_value=httpx.Response(
            200,
            json={
                "instance-types": [
                    {"id": MEDIUM_TYPE_ID, "family": "standard", "size": "medium"},
                    {"id": LARGE_TYPE_ID, "family": "standard", "size": "large"},
                ],
            },
        ),
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
    _mock_resolver_lists(respx_mock)
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(200, json={"reference": {"id": CREATED_INSTANCE_ID}}),
    )

    instance_id = await _api().create_instance(
        name="sb-test",
        image="Linux Ubuntu 24.04 LTS 64-bit",
        ssh_key_name="drukbox-sb-test",
        user_data="#!/bin/sh\necho hi",
        labels={"managed-by": "drukbox"},
    )

    assert instance_id == CREATED_INSTANCE_ID
    body = json.loads(route.calls.last.request.read())
    assert body["name"] == "sb-test"
    assert body["disk-size"] == 50
    # template-ref and instance-type-ref are {id}-only; the zone comes from the
    # zonal API host, not the body.
    assert body["template"] == {"id": UBUNTU_TEMPLATE_ID}
    assert body["instance-type"] == {"id": MEDIUM_TYPE_ID}
    assert "zone" not in body
    assert body["ssh-key"] == {"name": "drukbox-sb-test"}
    assert body["labels"] == {"managed-by": "drukbox"}
    assert base64.standard_b64decode(body["user-data"]).decode("utf-8") == "#!/bin/sh\necho hi"


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_prefers_explicit_instance_type(respx_mock):
    _mock_resolver_lists(respx_mock)
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(200, json={"reference": {"id": CREATED_INSTANCE_ID}}),
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
    assert body["instance-type"] == {"id": LARGE_TYPE_ID}


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_create_instance_prefers_explicit_disk_gb(respx_mock):
    _mock_resolver_lists(respx_mock)
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(200, json={"reference": {"id": CREATED_INSTANCE_ID}}),
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
    _mock_resolver_lists(respx_mock)
    route = respx_mock.post("/instance").mock(
        return_value=httpx.Response(200, json={"reference": {"id": CREATED_INSTANCE_ID}}),
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
async def test_resolve_template_id_picks_newest_build_matching_name(respx_mock):
    old_build_id = "9f2c8f74-2b7e-4f3a-b2a5-5d9f2f1e0c4d"
    respx_mock.get("/template").mock(
        return_value=httpx.Response(
            200,
            json={
                "templates": [
                    {
                        "id": old_build_id,
                        "name": "Linux Ubuntu 24.04 LTS 64-bit",
                        "created-at": "2024-11-05T08:00:00Z",
                        "visibility": "public",
                    },
                    {
                        "id": UBUNTU_TEMPLATE_ID,
                        "name": "Linux Ubuntu 24.04 LTS 64-bit",
                        "created-at": "2025-04-01T09:00:00Z",
                        "visibility": "public",
                    },
                    {
                        "id": "1c9e1e2d-4b6f-4a0e-9d3c-7e5b8a2f6d10",
                        "name": "Linux Debian 12 (Bookworm) 64-bit",
                        "created-at": "2025-06-01T09:00:00Z",
                        "visibility": "public",
                    },
                ],
            },
        ),
    )

    template_id = await _api()._resolve_template_id("Linux Ubuntu 24.04 LTS 64-bit")

    assert template_id == UBUNTU_TEMPLATE_ID


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_resolve_template_id_raises_when_name_unknown(respx_mock):
    respx_mock.get("/template").mock(
        return_value=httpx.Response(200, json={"templates": []}),
    )

    with pytest.raises(ExoscaleProviderError, match="no Exoscale template named"):
        await _api()._resolve_template_id("Linux Ubuntu 24.04 LTS 64-bit")


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_resolve_instance_type_id_matches_family_and_size(respx_mock):
    _mock_instance_type_list(respx_mock)

    assert await _api()._resolve_instance_type_id("standard.medium") == MEDIUM_TYPE_ID
    assert await _api()._resolve_instance_type_id("standard.large") == LARGE_TYPE_ID


@pytest.mark.asyncio
@respx.mock(base_url=BASE_URL)
async def test_resolve_instance_type_id_raises_when_name_unknown(respx_mock):
    _mock_instance_type_list(respx_mock)

    with pytest.raises(ExoscaleProviderError, match="no Exoscale instance type named"):
        await _api()._resolve_instance_type_id("standard.colossus")


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
async def test_find_instance_id_by_name_returns_id_when_present(respx_mock):
    respx_mock.get("/instance").mock(
        return_value=httpx.Response(
            200,
            json={
                "instances": [
                    {"id": "i-abc", "name": "sb-found"},
                    {"id": "i-xyz", "name": "other"},
                ],
            },
        ),
    )

    assert await _api().find_instance_id_by_name("sb-found") == "i-abc"


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
        return_value=httpx.Response(200, json={"instances": [{}, {}, {}]}),
    )
    assert await _api().list_instances_count() == 3


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
        return_value=httpx.Response(200, json={"reference": {"id": CREATED_INSTANCE_ID}}),
    )

    # Frozen signing fixture: the exact bytes the reference implementation
    # signed to produce `expected`. Input to the HMAC oracle only — not a
    # claim about the create-instance body shape.
    await _api()._request(
        "POST",
        "/instance",
        json={
            "name": "sb-test",
            "template": {"name": "Linux Ubuntu 24.04 LTS 64-bit"},
            "instance-type": {"name": "standard.medium"},
            "zone": ZONE,
            "disk-size": 50,
            "ssh-key": {"name": "drukbox-sb-test"},
            "labels": {"managed-by": "drukbox"},
            "user-data": base64.standard_b64encode(b"#!/bin/sh\necho hi").decode("utf-8"),
        },
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
        return_value=httpx.Response(200, json={"instances": []}),
    )

    await _api()._request("GET", "/instance", params={"zone": ZONE, "name": "sb-test"})

    header = route.calls.last.request.headers["authorization"]
    assert "signed-query-args=name;zone" in header
    assert header == expected
