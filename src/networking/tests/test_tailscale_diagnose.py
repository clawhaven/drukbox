from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from networking.tailscale import (
    NetworkTransportError,
    Tailscale,
    TailscaleDevice,
)


def _make_tailscale(api: object) -> Tailscale:
    return Tailscale(api)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_diagnose_returns_tailnet_and_device_count() -> None:
    """list_devices covers OAuth + tailnet + signed call in one hop."""
    api = SimpleNamespace(
        tailnet="example.ts.net",
        list_devices=AsyncMock(
            return_value=[TailscaleDevice(id="n1", hostname="sb-a")],
        ),
    )
    network = _make_tailscale(api)

    detail = await network.diagnose()
    assert detail == "tailnet=example.ts.net devices=1"


@pytest.mark.asyncio
async def test_diagnose_raises_on_list_devices_failure() -> None:
    """Transport errors surface so the orchestrator can classify them."""
    api = SimpleNamespace(
        tailnet="example.ts.net",
        list_devices=AsyncMock(side_effect=NetworkTransportError("503")),
    )
    network = _make_tailscale(api)

    with pytest.raises(NetworkTransportError, match="503"):
        await network.diagnose()
