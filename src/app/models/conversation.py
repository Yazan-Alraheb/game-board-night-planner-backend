from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)

    type = Column(
        String,
        nullable=False,
    )

    game_night_id = Column(
        Integer,
        ForeignKey("game_nights.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    game_night = relationship(
        "GameNight",
        back_populates="conversation",
    )

    participants = relationship(
        "ConversationMember",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('private', 'group')",
            name="ck_conversation_type",
        ),
        CheckConstraint(
            "type != 'private' OR game_night_id IS NULL",
            name="ck_private_conversation_no_game_night",
        ),
    )
