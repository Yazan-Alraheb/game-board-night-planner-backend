from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repository import user as user_repository
from app.schemas.user import LoginRequest, RegisterRequest
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-unknown-users")
_EMAIL_UNIQUE_INDEX = "ix_users_email"
_USERNAME_UNIQUE_INDEX = "ix_users_username"
_POSTGRES_UNIQUE_VIOLATION = "23505"
_SQLITE_EMAIL_CONFLICT = "UNIQUE constraint failed: users.email"
_SQLITE_USERNAME_CONFLICT = "UNIQUE constraint failed: users.username"

class EmailAlreadyRegisteredError(Exception):
    pass


class UsernameAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _is_email_conflict(error: IntegrityError) -> bool:
    if getattr(error.orig, "sqlstate", None) == _POSTGRES_UNIQUE_VIOLATION:
        return getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        ) == _EMAIL_UNIQUE_INDEX

    return str(error.orig) == _SQLITE_EMAIL_CONFLICT


def _is_username_conflict(error: IntegrityError) -> bool:
    if getattr(error.orig, "sqlstate", None) == _POSTGRES_UNIQUE_VIOLATION:
        return getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        ) == _USERNAME_UNIQUE_INDEX

    return str(error.orig) == _SQLITE_USERNAME_CONFLICT


def register_user(
    db: Session,
    data: RegisterRequest,
) -> tuple[User, str]:

    email = _normalize_email(data.email)
    username = data.username.strip().lower()

    if user_repository.get_user_by_email(db, email):
        raise EmailAlreadyRegisteredError()

    if user_repository.get_user_by_username(db, username):
        raise UsernameAlreadyRegisteredError()

    try:
        user = user_repository.create_user(
            db,
            name=data.name,
            username=username,
            email=email,
            password_hash=hash_password(data.password),
        )

    except IntegrityError as error:
        db.rollback()

        if _is_email_conflict(error):
            raise EmailAlreadyRegisteredError() from error

        if _is_username_conflict(error):
            raise UsernameAlreadyRegisteredError() from error

        raise

    return user, create_access_token(user.id)



def login_user(
    db: Session,
    data: LoginRequest,
) -> tuple[User, str]:

    identifier = data.identifier.strip().lower()

    if "@" in identifier:
        user = user_repository.get_user_by_email(
            db,
            identifier,
        )
    else:
        user = user_repository.get_user_by_username(
            db,
            identifier,
        )

    password_hash = (
        user.password_hash if user else _DUMMY_PASSWORD_HASH
    )

    password_is_valid = verify_password(
        data.password,
        password_hash,
    )

    if user is None or not password_is_valid:
        raise InvalidCredentialsError()

    return user, create_access_token(user.id)
