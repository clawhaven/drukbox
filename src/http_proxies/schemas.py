import uuid

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Proxy names become both an exe.dev CLI token and an integration identifier, so
# they must start alphanumeric (no leading hyphen → no option injection) and stay
# within a conservative charset. Shared with the {name} path params in api.py.
HTTP_PROXY_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class HTTPProxyCreate(BaseModel):
    name: str = Field(pattern=HTTP_PROXY_NAME_PATTERN)
    target: HttpUrl
    headers: dict[str, str] = Field(min_length=1)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            # Userinfo would be forwarded to the provider as part of its config
            # and could leak into provider-side logs. Targets are origin-only.
            raise ValueError("target URL must not contain credentials")
        if value.path not in ("", "/"):
            raise ValueError("target URL must not contain a path")
        if value.query:
            raise ValueError("target URL must not contain a query string")
        if value.fragment:
            raise ValueError("target URL must not contain a fragment")
        return value


class HTTPProxyOut(BaseModel):
    name: str
    status: str


class HTTPProxyAttachmentOut(BaseModel):
    name: str
    host_id: uuid.UUID
    status: str
