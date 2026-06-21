from unittest.mock import AsyncMock, MagicMock

import pytest

from providers.hetzner.exceptions import HetznerTransportError
from providers.hetzner.provider import HetznerProvider
from providers.hetzner.settings import HetznerSettings


def _provider(count_side: object = 3) -> HetznerProvider:
    api = MagicMock()
    if isinstance(count_side, Exception):
        api.count_servers = AsyncMock(side_effect=count_side)
    else:
        api.count_servers = AsyncMock(return_value=count_side)
    settings = HetznerSettings(api_token="t", location="nbg1", server_type="cx23")
    return HetznerProvider(api, settings)


@pytest.mark.asyncio
async def test_diagnose_returns_location_and_server_count():
    detail = await _provider(count_side=3).diagnose()
    assert detail == "location=nbg1 servers=3"


@pytest.mark.asyncio
async def test_diagnose_raises_on_api_failure():
    with pytest.raises(HetznerTransportError):
        await _provider(count_side=HetznerTransportError("401")).diagnose()
