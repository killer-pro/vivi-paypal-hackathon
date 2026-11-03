from app.security import hash_password, new_token, token_hash, verify_password


def test_hash_roundtrip():
    stocke = hash_password("motdepasse1")
    assert verify_password("motdepasse1", stocke) is True
    assert verify_password("autre-mot", stocke) is False


def test_hash_is_salted():
    assert hash_password("motdepasse1") != hash_password("motdepasse1")


def test_verify_rejects_malformed_hash():
    assert verify_password("x", "n'importe quoi") is False


def test_token_hash_matches():
    token, digest = new_token()
    assert token_hash(token) == digest
    autre, _ = new_token()
    assert autre != token
