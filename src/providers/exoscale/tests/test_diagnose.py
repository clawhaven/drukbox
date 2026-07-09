from unittest.mock import AsyncMock, MagicMock

import pytest

from providers.exoscale.exceptions import ExoscaleTransportError
from providers.exoscale.provider import ExoscaleProvider
from providers.exoscale.settings import ExoscaleSettings


def _provider(count_side: object = 3) -> ExoscaleProvider:
    api = MagicMock()
    if isinstance(count_side, Exception):
        api.list_instances_count = AsyncMock(side_effect=count_side)
    else:
        api.list_instances_count = AsyncMock(return_value=count_side)
    settings = ExoscaleSettings(api_key="exo-key", api_secret="exo-secret", zone="ch-gva-2")
    return ExoscaleProvider(api, settings)


@pytest.mark.asyncio
async def test_diagnose_returns_zone_and_instance_count():
    detail = await _provider(count_side=3).diagnose()
    assert detail == "zone=ch-gva-2 instances=3"


@pytest.mark.asyncio
async def test_diagnose_raises_on_api_failure():
    with pytest.raises(ExoscaleTransportError):
        await _provider(count_side=ExoscaleTransportError("401")).diagnose()
