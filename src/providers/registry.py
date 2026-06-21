from collections.abc import Callable

from core.settings import get_settings
from providers.base import VMProvider
from providers.exceptions import UnknownProviderError

VMProviderFactory = Callable[[], VMProvider]

_factories: dict[str, VMProviderFactory] = {}
_instances: dict[str, VMProvider] = {}


def register_vm_provider(provider_cls: type[VMProvider]) -> None:
    _factories[provider_cls.name] = provider_cls.from_settings


def get_vm_provider(name: str | None = None) -> VMProvider:
    resolved = name if name is not None else get_settings().default_host_provider

    if resolved in _instances:
        return _instances[resolved]

    factory = _factories.get(resolved)

    if factory is None:
        raise UnknownProviderError(f"unknown VM provider: {resolved}")
    instance = factory()
    _instances[resolved] = instance
    return instance


def get_default_vm_provider() -> VMProvider:
    return get_vm_provider(None)


def iter_initialized_vm_providers() -> list[VMProvider]:
    """Return providers that have been constructed in this process, without forcing construction."""
    return list(_instances.values())


def get_provider_names() -> list[str]:
    """Return the names of every registered VM provider, whether or not constructed."""
    return list(_factories.keys())


def reset_vm_provider_cache() -> None:
    _instances.clear()
