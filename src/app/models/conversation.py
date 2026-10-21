from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time_types import UTCDateTime


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
    )

    # Canonical pair for private conversations; membership still controls access.
    private_user_low_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )
    private_user_high_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )

    created_at = Column(
        UTCDateTime(),
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
        UniqueConstraint("game_night_id", name="uq_conversation_game_night"),
        UniqueConstraint(
            "private_user_low_id", "private_user_high_id",
            name="uq_conversation_private_pair",
        ),
        CheckConstraint(
            "type IN ('private', 'group')",
            name="ck_conversation_type",
        ),
        CheckConstraint(
            "type != 'private' OR game_night_id IS NULL",
            name="ck_private_conversation_no_game_night",
        ),
        CheckConstraint(
            "(type = 'private' AND private_user_low_id IS NOT NULL "
            "AND private_user_high_id IS NOT NULL "
            "AND private_user_low_id < private_user_high_id) "
            "OR (type = 'group' AND private_user_low_id IS NULL "
            "AND private_user_high_id IS NULL)",
            name="ck_conversation_private_pair",
        ),
    )
