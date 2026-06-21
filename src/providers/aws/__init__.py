try:
    import aioboto3  # noqa: F401
except ImportError:
    pass  # AWS is an optional provider; skip it when aioboto3 isn't installed.
else:
    # Import + register here, not in the except's scope, so a real ImportError in
    # the provider module surfaces instead of being mistaken for a missing extra.
    from providers.aws.provider import AWSProvider
    from providers.registry import register_vm_provider

    register_vm_provider(AWSProvider)
