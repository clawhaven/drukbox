from providers.exceptions import (
    ProviderAuthError,
    ProviderCommandError,
    ProviderError,
    ProviderNotFoundError,
    ProviderTransportError,
)


class ExeAPIError(ProviderError):
    pass


class ExeAuthError(ProviderAuthError, ExeAPIError):
    pass


class ExeResponseError(ProviderTransportError, ExeAPIError):
    pass


class ExeCommandError(ProviderCommandError, ExeAPIError):
    pass


class ExeVMNotFoundError(ProviderNotFoundError, ExeAPIError):
    pass


class ExeIntegrationNotFoundError(ProviderNotFoundError, ExeAPIError):
    pass


class ExeIntegrationAlreadyExistsError(ExeAPIError):
    pass
