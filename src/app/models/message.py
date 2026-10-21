from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time_types import UTCDateTime


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    content = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        UTCDateTime(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )

    user = relationship(
        "User",
        back_populates="messages",
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_message_content_not_empty",
        ),
        CheckConstraint("length(content) <= 2000", name="ck_message_content_length"),
        Index("ix_messages_conversation_created_id", conversation_id, created_at.desc(), id.desc()),
    )
