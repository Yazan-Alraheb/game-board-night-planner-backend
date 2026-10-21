from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repository import user as user_repository
from app.schemas.user import LoginRequest, RegisterRequest
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-unknown-users")
_EMAIL_UNIQUE_INDEX = "ix_users_email"
_POSTGRES_UNIQUE_VIOLATION = "23505"
_SQLITE_EMAIL_CONFLICT = "UNIQUE constraint failed: users.email"

class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass




def _normalize_email(email: str) -> str:

    return email.strip().lower()



def _is_email_conflict(error: IntegrityError) -> bool:
        if getattr(error.orig, "sqlstate", None) == _POSTGRES_UNIQUE_VIOLATION:
            return error.orig.diag.constraint_name == _EMAIL_UNIQUE_INDEX
        return str(error.orig) == _SQLITE_EMAIL_CONFLICT



def register_user(db: Session, data: RegisterRequest) -> tuple[User,str]:
        email= _normalize_email(data.email)
        if user_repository.get_user_by_email( db, email):
            raise EmailAlreadyRegisteredError()
        try:

             user =  user_repository.create_user(db,name = data.name,email=email,password_hash=hash_password(data.password),
            )


        except IntegrityError as error:
            db.rollback()
            if _is_email_conflict(error):

                raise EmailAlreadyRegisteredError() from error
            raise
        return user, create_access_token(user.id)


def login_user(db: Session, data: LoginRequest) -> tuple[User, str]:
    user = user_repository.get_user_by_email(db, _normalize_email(data.email))

    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(data.password, password_hash)

    if user is None or not password_is_valid:

        raise InvalidCredentialsError()

    return user, create_access_token(user.id)
