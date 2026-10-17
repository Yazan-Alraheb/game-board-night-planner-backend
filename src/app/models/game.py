from sqlalchemy import JSON, CheckConstraint, Column, Float, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    minimum_players = Column(Integer, nullable=False)
    maximum_players = Column(Integer, nullable=False)
    playtime = Column(Integer, nullable=False)

    difficulty = Column(String, nullable=False)
    categories = Column(JSON, nullable=True)

    image_url = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)

    user_entries = relationship(
        "UserGame",
        back_populates="game",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("minimum_players >= 1"),
        CheckConstraint("maximum_players >= minimum_players"),
        CheckConstraint("playtime > 0"),
        CheckConstraint(
            "difficulty IN ('Easy', 'Medium', 'Hard')"
        ),
    )
