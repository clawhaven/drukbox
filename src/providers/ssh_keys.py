from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_ed25519_keypair() -> tuple[str, str]:
    """Return ``(private_pem_openssh, public_openssh)`` for a fresh ed25519 key.

    Used by VM providers that mint per-instance key material at create time
    (AWS, Hetzner). The private half is returned to the caller exactly once
    and never persisted server-side.
    """
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_openssh = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode("utf-8")
    )
    return private_pem, public_openssh
