"""
Export generated identities to formats compatible with RNS applications.

Supported formats:
- Raw binary (64 bytes) — Nomadnet, Sideband, any RNS app
- Hex string
- Base32 string (Sideband Android import)
- Base64 string
"""

import os
import base64
from dataclasses import dataclass

from revanity.core import DEST_NAME_HASHES, dest_hash_from_identity_hash


@dataclass
class ExportedIdentity:
    """All information about an exported identity."""
    private_key_raw: bytes
    identity_hash_hex: str
    dest_hashes: dict[str, str]     # dest_type -> 32-char hex
    private_key_hex: str
    private_key_base32: str
    private_key_base64: str


def prepare_export(
    private_key: bytes,
    identity_hash: bytes,
    dest_type: str = "lxmf.delivery",
    dest_hash_hex: str = "",
) -> ExportedIdentity:
    """Prepare all export formats for an identity.

    Args:
        private_key: 64-byte raw private key.
        identity_hash: 16-byte identity hash.
        dest_type: Primary destination type that was searched.
        dest_hash_hex: Pre-computed destination hash hex for that type.
    """
    dest_hashes = {}
    for dt, name_hash in DEST_NAME_HASHES.items():
        dh = dest_hash_from_identity_hash(name_hash, identity_hash)
        dest_hashes[dt] = dh.hex()

    if dest_type not in dest_hashes and dest_hash_hex:
        dest_hashes[dest_type] = dest_hash_hex

    return ExportedIdentity(
        private_key_raw=private_key,
        identity_hash_hex=identity_hash.hex(),
        dest_hashes=dest_hashes,
        private_key_hex=private_key.hex(),
        private_key_base32=base64.b32encode(private_key).decode("ascii"),
        private_key_base64=base64.b64encode(private_key).decode("ascii"),
    )


def save_identity_file(private_key: bytes, path: str) -> str:
    """Save identity as raw 64-byte binary file (RNS-compatible format).

    Returns the absolute path of the saved file.
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(private_key)
    try:
        os.chmod(abs_path, 0o600)
    except OSError:
        pass  # Windows: chmod not fully supported
    return abs_path


def save_identity_text(export: ExportedIdentity, path: str) -> str:
    """Save identity info as a human-readable text file with import instructions.

    Returns the absolute path of the saved file.
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

    lines = [
        "# revanity Generated Identity",
        f"# Identity Hash: {export.identity_hash_hex}",
        "#",
        "# Destination Hashes:",
    ]
    for dt, dh in export.dest_hashes.items():
        lines.append(f"#   {dt}: {dh}")

    lines.extend([
        "#",
        "# Private Key (KEEP SECRET):",
        f"#   Hex:    {export.private_key_hex}",
        f"#   Base32: {export.private_key_base32}",
        f"#   Base64: {export.private_key_base64}",
        "#",
        "# Import Instructions:",
        "#",
        "#   Nomadnet:",
        "#     cp <file>.identity ~/.nomadnetwork/storage/identity",
        "#     (restart Nomadnet after copying)",
        "#",
        "#   Sideband (Linux):",
        "#     cp <file>.identity ~/.config/sideband/storage/identity",
        "#",
        "#   Sideband (macOS):",
        "#     cp <file>.identity ~/Library/Application\\ Support/Sideband/storage/identity",
        "#",
        "#   Sideband (Android):",
        "#     Import the Base32 string above via Settings > Identity",
        "#",
        "#   rnid utility:",
        f"#     rnid -m {export.private_key_hex}",
        f"#     rnid -m {export.private_key_base32} -B",
        "#",
        "#   Any RNS application (Python):",
        "#     import RNS",
        "#     identity = RNS.Identity.from_file('path/to/<file>.identity')",
        "#",
    ])
    with open(abs_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(abs_path, 0o600)
    except OSError:
        pass  # Windows: chmod not fully supported
    return abs_path
