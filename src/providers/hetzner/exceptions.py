class HetznerProviderError(RuntimeError):
    """Base error for the Hetzner provider."""


class HetznerVMNotFoundError(HetznerProviderError):
    """No server matched the lookup."""


class HetznerTransportError(HetznerProviderError):
    """Talking to the Hetzner Cloud API failed for transport reasons."""
