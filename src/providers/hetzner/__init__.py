from providers.hetzner.provider import HetznerProvider
from providers.registry import register_vm_provider

register_vm_provider(HetznerProvider)
