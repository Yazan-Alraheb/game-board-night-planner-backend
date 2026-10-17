from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class Preference(Base):
    __tablename__ = "preferences"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
        ondelete="CASCADE",
    )

    preferred_difficulty = Column(String, nullable=True)
    preferred_playtime = Column(Integer, nullable=True)

    favorite_categories = Column(
        JSON,
        default=list,
        nullable=False,
    )

    disliked_categories = Column(
        JSON,
        default=list,
        nullable=False,
    )
    user = relationship(
        "User",
        back_populates="preferences",
    )
    __table_args__ = (
        CheckConstraint(
            "preferred_difficulty IS NULL "
            "OR preferred_difficulty IN ('Easy', 'Medium', 'Hard')"
        ),
        CheckConstraint(
            "preferred_playtime IS NULL OR preferred_playtime > 0"
        ),
    )
