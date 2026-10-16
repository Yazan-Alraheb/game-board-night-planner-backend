from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String

from app.core.database import Base


class UserGame(Base):
    __tablename__ = "user_games"

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        primary_key=True,
    )

    game_id = Column(
        Integer,
        ForeignKey("games.id"),
        primary_key=True,
    )

    status = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('owned', 'wishlist')"
        ),
    )
