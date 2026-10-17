from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base


class GameNightGame(Base):
    __tablename__ = "game_night_games"

    game_night_id = Column(
        Integer,
        ForeignKey("game_nights.id", ondelete="CASCADE"),
        primary_key=True,
    )

    game_id = Column(
        Integer,
        ForeignKey("games.id", ondelete="CASCADE"),
        primary_key=True,
    )

    game_night = relationship(
        "GameNight",
        back_populates="game_entries",
    )

    game = relationship(
        "Game",
        back_populates="game_night_entries",
    )
