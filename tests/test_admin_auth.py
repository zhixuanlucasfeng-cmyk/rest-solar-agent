import pytest
from app.admin.auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hash_and_verify():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_create_and_decode_token():
    token = create_access_token({"sub": "1", "role": "agent"})
    payload = decode_access_token(token)
    assert payload["sub"] == "1"
    assert payload["role"] == "agent"


def test_expired_token_raises():
    from datetime import timedelta
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(Exception):
        decode_access_token(token)
