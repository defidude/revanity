"""
Optional verification of generated identities against the RNS library.

If RNS is not installed, verification is skipped gracefully.
"""


def verify_with_rns(
    private_key: bytes,
    expected_identity_hash_hex: str,
    expected_dest_hex: str,
    dest_name: str = "lxmf.delivery",
) -> dict:
    """Verify a generated identity against the RNS library.

    Args:
        private_key: 64-byte raw private key.
        expected_identity_hash_hex: Our computed identity hash hex.
        expected_dest_hex: Our computed destination hash hex.
        dest_name: Full destination name, e.g. "lxmf.delivery".

    Returns dict with:
        rns_available, identity_hash_match, dest_hash_match,
        rns_identity_hash, rns_dest_hash, error
    """
    result = {
        "rns_available": False,
        "identity_hash_match": None,
        "dest_hash_match": None,
        "rns_identity_hash": None,
        "rns_dest_hash": None,
        "error": None,
    }

    try:
        import RNS  # noqa: F811
        result["rns_available"] = True
    except ImportError:
        result["error"] = "RNS not installed. Install with: pip install rns"
        return result

    try:
        identity = RNS.Identity(create_keys=False)
        identity.load_private_key(private_key)

        rns_id_hash = identity.hash.hex()
        result["rns_identity_hash"] = rns_id_hash
        result["identity_hash_match"] = rns_id_hash == expected_identity_hash_hex

        # Compute destination hash using RNS internal methods
        name_hash = RNS.Identity.full_hash(
            dest_name.encode("utf-8")
        )[:RNS.Identity.NAME_HASH_LENGTH // 8]
        rns_dest_hash = RNS.Identity.full_hash(
            name_hash + identity.hash
        )[:RNS.Reticulum.TRUNCATED_HASHLENGTH // 8]

        rns_dest_hex = rns_dest_hash.hex()
        result["rns_dest_hash"] = rns_dest_hex
        result["dest_hash_match"] = rns_dest_hex == expected_dest_hex

    except Exception as e:
        result["error"] = str(e)

    return result
