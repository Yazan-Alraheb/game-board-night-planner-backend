from datetime import datetime, timedelta, timezone
import re

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.auth_settings import get_auth_settings


_password_hasher = PasswordHash.recommended()
_JWT_ALGORITHM = "HS256"
_MAX_USER_ID = 2**31 - 1


def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _password_hasher.verify(plain_password, password_hash)


def create_access_token(user_id: int) -> str:
    if type(user_id) is not int or not 1 <= user_id <= _MAX_USER_ID:
        raise ValueError(f"User ID must be an integer between 1 and {_MAX_USER_ID}")

    settings = get_auth_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=_JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> int:
    settings = get_auth_settings()
    claims = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[_JWT_ALGORITHM],
        options={
            "require": ["sub", "exp", "iat"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_sub": True,
        },
        leeway=0,
    )

    subject = claims["sub"]
    if isinstance(subject, str) and len(subject) > len(str(_MAX_USER_ID)):
        raise InvalidTokenError("User ID exceeds the supported range")
    if not isinstance(subject, str) or re.fullmatch(r"[1-9][0-9]*", subject) is None:
        raise InvalidTokenError("Subject must be a canonical positive integer")
    if any(type(claims[name]) is not int for name in ("iat", "exp")):
        raise InvalidTokenError("Issued-at and expiration must be integer timestamps")
    if claims["exp"] <= claims["iat"]:
        raise InvalidTokenError("Expiration must be after issuance")
    try:
        user_id = int(subject)
    except ValueError as exc:
        raise InvalidTokenError("Invalid user ID") from exc
    if user_id > _MAX_USER_ID:
        raise InvalidTokenError("User ID exceeds the supported range")
    return user_id
