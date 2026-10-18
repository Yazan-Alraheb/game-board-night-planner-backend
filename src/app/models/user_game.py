from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserGame(Base):
    __tablename__ = "user_games"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,

    )

    game_id = Column(
        Integer,
        ForeignKey("games.id", ondelete="CASCADE"),
        primary_key=True,

    )

    status = Column(String, nullable=False)
    user = relationship(
        "User",
        back_populates="game_entries",
    )

    game = relationship(
        "Game",
        back_populates="user_entries",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('owned', 'wishlist')"
        ),
    )
