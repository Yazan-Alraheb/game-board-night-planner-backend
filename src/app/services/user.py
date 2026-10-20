from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repository import user as user_repository
from app.schemas.user import LoginRequest, RegisterRequest
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-unknown-users")


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass




def _normalize_email(email: str) -> str:

    return email.strip().lower()



def _is_email_conflict(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint:
        return "email" in constraint
    return "users.email" in str(error.orig)


def register_user(db: Session, data: RegisterRequest) -> User:
        email= _normalize_email(data.email)
        if user_repository.get_user_by_email( db, email):
            raise EmailAlreadyRegisteredError()
        try:

            return user_repository.create_user(
                db,
                name = data.name,
                email=email,
                password_hash=hash_password(data.password),
            )


        except IntegrityError as error:
            db.rollback()
            if _is_email_conflict(error):
                raise EmailAlreadyRegisteredError() from error
            raise


def login_user(db: Session, data: LoginRequest) -> str:
    user = user_repository.get_user_by_email(db, _normalize_email(data.email))
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(data.password, password_hash)

    if user is None or not password_is_valid:
        raise InvalidCredentialsError()
    return create_access_token(user.id)
