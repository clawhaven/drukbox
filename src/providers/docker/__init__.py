from providers.docker.provider import DockerProvider
from providers.registry import register_vm_provider

register_vm_provider(DockerProvider)
