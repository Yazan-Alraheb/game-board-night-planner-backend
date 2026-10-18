from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    conversation = relationship(
        "Conversation",
        back_populates="participants",
    )

    user = relationship(
        "User",
        back_populates="conversation_memberships",
    )
