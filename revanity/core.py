"""
Core hash computation functions for Reticulum identity and destination addresses.

All constants verified against RNS v1.1.3 source:
  - RNS/Identity.py: NAME_HASH_LENGTH = 80, KEYSIZE = 512
  - RNS/Reticulum.py: TRUNCATED_HASHLENGTH = 128
"""

import hashlib
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

# Verified RNS constants
NAME_HASH_LENGTH = 80          # bits (10 bytes)
TRUNCATED_HASHLENGTH = 128     # bits (16 bytes)
KEYSIZE = 512                  # bits (64 bytes total keypair)

# Serialization constants cached at module level for performance
_RAW = serialization.Encoding.Raw
_RAW_PRV = serialization.PrivateFormat.Raw
_RAW_PUB = serialization.PublicFormat.Raw
_NO_ENC = serialization.NoEncryption()

# Precomputed name hashes for known destination types
LXMF_NAME_HASH = bytes.fromhex("6ec60bc318e2c0f0d908")
NOMADNET_NAME_HASH = bytes.fromhex("213e6311bcec54ab4fde")

DEST_NAME_HASHES = {
    "lxmf.delivery": LXMF_NAME_HASH,
    "nomadnetwork.node": NOMADNET_NAME_HASH,
}


def compute_name_hash(dest_name: str) -> bytes:
    """Compute the 10-byte name hash for a destination type.

    Args:
        dest_name: Full destination name, e.g. "lxmf.delivery"

    Returns:
        10-byte name hash
    """
    return hashlib.sha256(dest_name.encode("utf-8")).digest()[:NAME_HASH_LENGTH // 8]


def generate_and_hash(name_hash: bytes) -> tuple[bytes, bytes, str]:
    """Generate one identity and compute its destination hash.

    This is the hot-path function called in the inner loop of each worker.

    Args:
        name_hash: Precomputed 10-byte name hash for the target destination type.

    Returns:
        (private_key_bytes, identity_hash, dest_hex)
        - private_key_bytes: 64 bytes (X25519 prv + Ed25519 prv), RNS-compatible
        - identity_hash: 16 bytes
        - dest_hex: 32-char lowercase hex string of the destination hash
    """
    x_prv = X25519PrivateKey.generate()
    e_prv = Ed25519PrivateKey.generate()

    x_pub = x_prv.public_key().public_bytes(_RAW, _RAW_PUB)
    e_pub = e_prv.public_key().public_bytes(_RAW, _RAW_PUB)

    identity_hash = hashlib.sha256(x_pub + e_pub).digest()[:16]
    dest_hash = hashlib.sha256(name_hash + identity_hash).digest()[:16]

    prv_bytes = x_prv.private_bytes(_RAW, _RAW_PRV, _NO_ENC)
    sig_bytes = e_prv.private_bytes(_RAW, _RAW_PRV, _NO_ENC)

    return prv_bytes + sig_bytes, identity_hash, dest_hash.hex()


def identity_hash_from_pub(x25519_pub: bytes, ed25519_pub: bytes) -> bytes:
    """Compute the 16-byte identity hash from public key components."""
    return hashlib.sha256(x25519_pub + ed25519_pub).digest()[:TRUNCATED_HASHLENGTH // 8]


def dest_hash_from_identity_hash(name_hash: bytes, identity_hash: bytes) -> bytes:
    """Compute the 16-byte destination hash from a name hash and identity hash."""
    return hashlib.sha256(name_hash + identity_hash).digest()[:TRUNCATED_HASHLENGTH // 8]
