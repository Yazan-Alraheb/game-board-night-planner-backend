from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time_types import UTCDateTime
from sqlalchemy import Index, func

class Friend(Base):
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)

    requester_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    receiver_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    status = Column(
        String,
        nullable=False,
        default="pending",
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Null on pending requests and historical resolutions with unknown timing.
    resolved_at = Column(UTCDateTime(), nullable=True)

    requester = relationship(
        "User",
        foreign_keys=[requester_id],
        back_populates="sent_friend_requests",
    )

    receiver = relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_friend_requests",
    )

    __table_args__ = (
    CheckConstraint(
        "status IN ('pending', 'accepted', 'declined')",
        name="ck_friend_status",
    ),
    CheckConstraint(
        "requester_id != receiver_id",
        name="ck_friend_not_self",
    ),
    Index(
        "uq_active_friend_pair",
        func.least(requester_id, receiver_id),
        func.greatest(requester_id, receiver_id),
        unique=True,
        postgresql_where=status.in_(["pending", "accepted"]),
    ),
    Index(
        "ix_friends_decline_lookup",
        requester_id,
        receiver_id,
        resolved_at.desc(),
        postgresql_where=(status == "declined") & resolved_at.is_not(None),
    ),
)
