import abc

from providers.base import VMProvider
from providers.exceptions import UnknownProviderError
from providers.registry import get_default_vm_provider


class HttpProxyCapability(abc.ABC):
    """Mix-in declaring a VMProvider also speaks the http-proxy capability.

    Modeled as an ABC (not a Protocol) so isinstance() really checks the
    inheritance chain — runtime_checkable Protocols would let any object that
    happens to expose the four method names pass the check, including MagicMock
    instances and providers with mismatched signatures.
    """

    @abc.abstractmethod
    async def create_http_proxy(
        self,
        *,
        name: str,
        target: str,
        headers: dict[str, str],
    ) -> None: ...

    @abc.abstractmethod
    async def delete_http_proxy(self, name: str) -> None: ...

    @abc.abstractmethod
    async def attach_http_proxy(self, name: str, *, attach_vm: str) -> None: ...

    @abc.abstractmethod
    async def detach_http_proxy(self, name: str, *, attach_vm: str) -> None: ...


def get_default_http_proxy_capability() -> HttpProxyCapability:
    provider: VMProvider = get_default_vm_provider()

    if not isinstance(provider, HttpProxyCapability):
        raise UnknownProviderError(
            f"default VM provider '{provider.name}' does not support http proxies",
        )
    return provider
