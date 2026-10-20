from sqlalchemy.orm import Session
from app.models.user import User



def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, name: str, email: str, password_hash: str) -> User:

    new_user = User(name = name, email = email, password_hash  = password_hash)


    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user
