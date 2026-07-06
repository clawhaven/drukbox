import pytest

from providers.capabilities import HttpProxyCapability, resolve_capability
from providers.exceptions import CapabilityUnsupportedError
from providers.registry import get_vm_provider


def test_resolve_capability_returns_implementing_provider() -> None:
    """A provider that inherits the capability mix-in resolves to itself."""
    provider = get_vm_provider("exe")
    assert resolve_capability(provider, HttpProxyCapability) is provider


def test_resolve_capability_refuses_provider_without_capability() -> None:
    """A provider without the mix-in raises the shared unsupported error."""
    with pytest.raises(CapabilityUnsupportedError, match="'docker' does not support"):
        resolve_capability(get_vm_provider("docker"), HttpProxyCapability)
