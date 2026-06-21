class AwsProviderError(RuntimeError):
    """Base error for the AWS provider."""


class AwsVMNotFoundError(AwsProviderError):
    """No instance matched the lookup tags."""


class AwsTransportError(AwsProviderError):
    """Talking to EC2 / SSM failed for transport reasons."""
