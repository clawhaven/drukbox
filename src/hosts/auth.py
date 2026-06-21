import hmac
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from core.settings import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def is_service_token(token: str) -> bool:
    settings = get_settings()
    return any(hmac.compare_digest(token, expected) for expected in settings.service_tokens)


def require_service_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="service token required")
    if is_service_token(credentials.credentials):
        return
    raise HTTPException(status_code=403, detail="service token rejected")
