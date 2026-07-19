from xhs_skill.core.security import decrypt_bytes, encrypt_bytes


def test_encryption_roundtrip():
    nonce, encrypted = encrypt_bytes(b"secret", "a" * 32, b"account")
    assert decrypt_bytes(nonce, encrypted, "a" * 32, b"account") == b"secret"
