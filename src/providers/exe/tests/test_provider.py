from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from providers.exe.api import ExeAPI
from providers.exe.provider import ExeProvider
from providers.exe.settings import ExeSettings


def _settings(**overrides: Any) -> ExeSettings:
    defaults: dict[str, Any] = {"api_token": "test-token", "default_image": "img:latest"}
    return ExeSettings(**{**defaults, **overrides})


def _make_provider(api: object) -> ExeProvider:
    return ExeProvider(api, _settings())  # type: ignore[arg-type]


async def test_create_vm_forwards_kwargs_and_maps_result() -> None:
    api = SimpleNamespace(
        create_vm=AsyncMock(
            return_value={
                "vm_name": "sb-1234",
                "ssh_port": "2222",
                "ssh_dest": "sb-1234.public.exe.dev",
            }
        ),
    )
    provider = _make_provider(api)

    result = await provider.create_vm(
        name="sb-1234",
        image="img:latest",
        env={"K": "V"},
        setup_script="#!/bin/bash\necho hello",
    )

    # ExeProvider constructs its own tags from the name + service_label.
    api.create_vm.assert_awaited_once_with(
        name="sb-1234",
        image="img:latest",
        env={"K": "V"},
        setup_script="#!/bin/bash\necho hello",
        tags=["managed-by-drukbox"],
    )
    assert result.provider_id == "sb-1234"
    assert result.name == "sb-1234"
    assert result.ssh_port == 2222
    assert result.ssh_host == "sb-1234.public.exe.dev"


async def test_delete_vm_delegates_to_api() -> None:
    api = SimpleNamespace(delete_vm=AsyncMock())
    provider = _make_provider(api)

    await provider.delete_vm("sb-1234")
    api.delete_vm.assert_awaited_once_with("sb-1234")


async def test_delete_vm_translates_not_found_to_provider_not_found() -> None:
    from providers.exceptions import ProviderNotFoundError
    from providers.exe.exceptions import ExeVMNotFoundError

    api = SimpleNamespace(
        delete_vm=AsyncMock(side_effect=ExeVMNotFoundError("vm 'sb-1' not found")),
    )
    provider = _make_provider(api)

    with pytest.raises(ProviderNotFoundError, match="sb-1"):
        await provider.delete_vm("sb-1")


async def test_aclose_delegates_to_api() -> None:
    api = SimpleNamespace(aclose=AsyncMock())
    provider = _make_provider(api)

    await provider.aclose()
    api.aclose.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        (
            "create_http_proxy",
            {"name": "p", "target": "https://t", "headers": {"H": "v"}},
        ),
        ("delete_http_proxy", {"name": "p"}),
        ("attach_http_proxy", {"name": "p", "attach_vm": "sb-1234"}),
        ("detach_http_proxy", {"name": "p", "attach_vm": "sb-1234"}),
    ],
)
async def test_http_proxy_methods_delegate_to_api(method_name: str, kwargs: dict) -> None:
    api = SimpleNamespace(**{method_name: AsyncMock()})
    provider = _make_provider(api)

    proxy_kwargs = dict(kwargs)
    positional: list[str] = []

    if method_name in {"delete_http_proxy", "attach_http_proxy", "detach_http_proxy"}:
        positional.append(proxy_kwargs.pop("name"))
    await getattr(provider, method_name)(*positional, **proxy_kwargs)
    getattr(api, method_name).assert_awaited_once_with(*positional, **proxy_kwargs)


def test_from_settings_constructs_with_exeapi() -> None:
    provider = ExeProvider.from_settings()
    assert isinstance(provider.api, ExeAPI)
