from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class GameNightMember(Base):
    __tablename__ = "game_night_members"

    game_night_id = Column(
        Integer,
        ForeignKey("game_nights.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    status = Column(
        String,
        nullable=False,
        default="pending",
    )

    game_night = relationship(
        "GameNight",
        back_populates="members",
    )

    user = relationship(
        "User",
        back_populates="game_night_memberships",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name="ck_game_night_member_status",
        ),
    )
