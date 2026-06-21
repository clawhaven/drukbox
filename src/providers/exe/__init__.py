from providers.exe.provider import ExeProvider
from providers.registry import register_vm_provider

register_vm_provider(ExeProvider)
