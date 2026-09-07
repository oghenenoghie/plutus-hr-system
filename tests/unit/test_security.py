import uuid

import jwt
import pytest
from pyotp import TOTP

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_totp_roundtrip() -> None:
    secret = generate_totp_secret()
    code = TOTP(secret).now()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000")


def test_access_token_roundtrip() -> None:
    account_id, org_id = uuid.uuid4(), uuid.uuid4()
    token = create_access_token(account_id, org_id, "admin")
    claims = decode_token(token, expected_type="access")
    assert claims.account_id == account_id
    assert claims.org_id == org_id
    assert claims.role == "admin"


def test_refresh_token_rejected_as_access_token() -> None:
    token = create_refresh_token(uuid.uuid4(), uuid.uuid4(), "admin")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, expected_type="access")
