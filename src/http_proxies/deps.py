from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from http_proxies.exceptions import HTTPProxyUnsupportedError
from http_proxies.service import HTTPProxyService
from providers.exceptions import UnknownProviderError


async def get_http_proxy_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTTPProxyService:
    # The active provider may not speak the http-proxy capability (only exe
    # does today). Translate that into a clean 501 instead of letting the
    # raw UnknownProviderError surface as a 500.
    try:
        return HTTPProxyService(session)
    except UnknownProviderError as exc:
        raise HTTPProxyUnsupportedError(str(exc)) from exc
