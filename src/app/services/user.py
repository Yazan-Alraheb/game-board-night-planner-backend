from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repository import user as user_repository
from app.schemas.user import LoginRequest, RegisterRequest

class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass




def _normalize_email(email: str) -> str:
    
    return email.strip().lower()

def register_user(db: Session, data: RegisterRequest) -> User:
        email= _normalize_email(data.email)
        if user_repository.get_user_by_email( db, email):
            raise EmailAlreadyRegisteredError()
        try:
            
            return user_repository.create_user(
                db,
                name=data.name.strip(),
                email=email,
                password_hash=hash_password(data.password),
            )

        
        except IntegrityError:
            db.rollback()
            raise EmailAlreadyRegisteredError()


def login_user(db: Session, data: LoginRequest) -> str:
    
    
    user= user_repository.get_user_by_email(db, _normalize_email (data.email))
    
    if user is None or not verify_password(data.password, user.password_hash):
        raise InvalidCredentialsError()
    
    return create_access_token( user.id )