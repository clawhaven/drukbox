class ExoscaleProviderError(RuntimeError):
    """Base error for the Exoscale provider."""


class ExoscaleVMNotFoundError(ExoscaleProviderError):
    """No instance matched the lookup."""


class ExoscaleTransportError(ExoscaleProviderError):
    """Talking to the Exoscale API failed for transport reasons."""
