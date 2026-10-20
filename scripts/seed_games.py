from sqlalchemy.orm import Session

import app.models
from app.core.database import engine
from app.models.game import Game


games = [
    {
        "name": "Catan",
        "description": "A strategy board game about building settlements.",
        "minimum_players": 3,
        "maximum_players": 4,
        "playtime": 60,
        "difficulty": "Medium",
        "categories": ["Strategy", "Family"],
        "image_url": None,
        "rating": 4.5,
        "review_count": 100,
        "instructions": "Collect resources and build settlements.",
    },
    {
        "name": "Flip 7",
        "description": (
            "A push-your-luck card game where players flip cards "
            "to score points without revealing duplicate numbers."
        ),
        "minimum_players": 3,
        "maximum_players": 18,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Card Game", "Party", "Family"],
        "image_url": None,
        "rating": None,
        "review_count": None,
        "instructions": (
            "Draw cards to earn points, but avoid duplicate numbers. "
            "Stop drawing to bank your points or risk losing them."
        ),
    },
]


with Session(engine) as db:
    for game_data in games:
        existing_game = (
            db.query(Game)
            .filter(Game.name == game_data["name"])
            .first()
        )

        if existing_game:
            print(
                f"{game_data['name']} already exists "
                f"with ID: {existing_game.id}"
            )
            continue

        game = Game(**game_data)

        db.add(game)
        db.commit()
        db.refresh(game)

        print(f"Created {game.name} with ID: {game.id}")
