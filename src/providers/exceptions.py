class ProviderError(RuntimeError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderTransportError(ProviderError):
    pass


class ProviderCommandError(ProviderError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderTargetVMNotFoundError(ProviderNotFoundError):
    pass


class ProviderHttpProxyExistsError(ProviderError):
    pass


class ProviderHttpProxyNotFoundError(ProviderNotFoundError):
    pass


class UnknownProviderError(ProviderError):
    pass


class CapabilityUnsupportedError(ProviderError):
    pass
