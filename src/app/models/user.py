from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    preferences = relationship(
        "Preference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    hosted_game_nights = relationship(
        "GameNight",
        back_populates="host",
        cascade="all, delete-orphan",
        )

    game_night_memberships = relationship(
        "GameNightMember",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    sent_friend_requests = relationship(
        "Friend",
        foreign_keys="Friend.requester_id",
        back_populates="requester",
        cascade="all, delete-orphan",
    )

    received_friend_requests = relationship(
        "Friend",
        foreign_keys="Friend.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan",
    )

    conversation_memberships = relationship(
        "ConversationMember",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    messages = relationship(
        "Message",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    game_entries = relationship(
    "UserGame",
    back_populates="user",
    cascade="all, delete-orphan",
    )
