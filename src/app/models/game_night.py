from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class GameNight(Base):
    __tablename__ = "game_nights"

    id = Column(Integer, primary_key=True, index=True)

    host_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name = Column(String, nullable=False)

    starts_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    location = Column(String, nullable=False)

    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    host = relationship(
        "User",
        back_populates="hosted_game_nights",
    )

    members = relationship(
        "GameNightMember",
        back_populates="game_night",
        cascade="all, delete-orphan",
    )

    game_entries = relationship(
        "GameNightGame",
        back_populates="game_night",
        cascade="all, delete-orphan",
    )

    conversation = relationship(
        "Conversation",
        back_populates="game_night",
        uselist=False,
        cascade="all, delete-orphan",
    )
