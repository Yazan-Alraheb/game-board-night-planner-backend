from sqlalchemy.orm import Session

import app.models
from app.core.database import engine
from app.models.game import Game


games = [
        {
        "name": "Clue",
        "description": "Solve a murder mystery by identifying the suspect, room, and weapon.",
        "minimum_players": 3,
        "maximum_players": 6,
        "playtime": 45,
        "difficulty": "Medium",
        "categories": ["Family", "Deduction"],
        "image_url": "/images/games/clue.jpg",
        "rating": 4.3,
        "review_count": 150,
        "instructions": "Collect clues and determine who committed the crime.",
    },
    {
        "name": "Monopoly",
        "description": "Buy, trade, and develop properties while trying to bankrupt your opponents.",
        "minimum_players": 2,
        "maximum_players": 8,
        "playtime": 120,
        "difficulty": "Medium",
        "categories": ["Family", "Strategy"],
        "image_url": "/images/games/monopoly.jpg",
        "rating": 4.0,
        "review_count": 200,
        "instructions": "Buy properties, collect rent, and manage your money.",
    },
    {
        "name": "Battleship",
        "description": "Locate and sink your opponent's hidden fleet.",
        "minimum_players": 2,
        "maximum_players": 2,
        "playtime": 30,
        "difficulty": "Easy",
        "categories": ["Strategy", "Classic"],
        "image_url": "/images/games/battleship.jpg",
        "rating": 4.1,
        "review_count": 120,
        "instructions": "Call coordinates and try to sink every opposing ship.",
    },
    {
        "name": "The Game of Life",
        "description": "Travel through life while making choices about careers, family, and money.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 60,
        "difficulty": "Easy",
        "categories": ["Family", "Classic"],
        "image_url": "/images/games/game-of-life.jpg",
        "rating": 4.0,
        "review_count": 110,
        "instructions": "Move along the board and make decisions that affect your final score.",
    },
    {
        "name": "Risk",
        "description": "Conquer territories and defeat opposing armies around the world.",
        "minimum_players": 2,
        "maximum_players": 6,
        "playtime": 120,
        "difficulty": "Hard",
        "categories": ["Strategy", "War Game"],
        "image_url": "/images/games/risk.jpg",
        "rating": 4.2,
        "review_count": 180,
        "instructions": "Deploy armies, attack territories, and complete your objective.",
    },
    {
        "name": "Sorry!",
        "description": "Race your pawns around the board while sending opponents back to start.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 30,
        "difficulty": "Easy",
        "categories": ["Family", "Classic"],
        "image_url": "/images/games/sorry.jpg",
        "rating": 4.0,
        "review_count": 100,
        "instructions": "Draw cards and move your pawns toward the safety zone.",
    },
    {
        "name": "Trouble",
        "description": "Move your pieces around the board and be the first player to finish.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 30,
        "difficulty": "Easy",
        "categories": ["Family", "Classic"],
        "image_url": "/images/games/trouble.jpg",
        "rating": 3.9,
        "review_count": 90,
        "instructions": "Press the Pop-O-Matic dice roller and move your pieces.",
    },
    {
        "name": "Connect 4",
        "description": "Drop colored discs and connect four in a row before your opponent.",
        "minimum_players": 2,
        "maximum_players": 2,
        "playtime": 15,
        "difficulty": "Easy",
        "categories": ["Family", "Strategy"],
        "image_url": "/images/games/connect-4.jpg",
        "rating": 4.2,
        "review_count": 130,
        "instructions": "Place discs strategically to connect four horizontally, vertically, or diagonally.",
    },
    {
        "name": "Scrabble",
        "description": "Create words with letter tiles to earn the highest score.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 60,
        "difficulty": "Medium",
        "categories": ["Word Game", "Family"],
        "image_url": "/images/games/scrabble.jpg",
        "rating": 4.3,
        "review_count": 160,
        "instructions": "Build connected words and use premium spaces to maximize points.",
    },
    {
        "name": "UNO",
        "description": "Match cards by color or number and be the first player to empty your hand.",
        "minimum_players": 2,
        "maximum_players": 10,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Card Game", "Family"],
        "image_url": "/images/games/uno.jpg",
        "rating": 4.4,
        "review_count": 220,
        "instructions": "Play matching cards and say UNO when you have one card remaining.",
    },
    {
        "name": "Candy Land",
        "description": "Travel through a colorful candy-themed world to reach the finish.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Family", "Children"],
        "image_url": "/images/games/candy-land.jpg",
        "rating": 4.0,
        "review_count": 100,
        "instructions": "Draw colored cards and move your piece to the matching space.",
    },
    {
        "name": "Operation",
        "description": "Remove objects from the patient without touching the sides.",
        "minimum_players": 1,
        "maximum_players": 4,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Family", "Dexterity"],
        "image_url": "/images/games/operation.jpg",
        "rating": 4.1,
        "review_count": 95,
        "instructions": "Use the tweezers carefully to remove pieces without making the buzzer sound.",
    },
    {
        "name": "Guess Who?",
        "description": "Ask yes-or-no questions to identify your opponent's mystery character.",
        "minimum_players": 2,
        "maximum_players": 2,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Family", "Deduction"],
        "image_url": "/images/games/guess-who.jpg",
        "rating": 4.2,
        "review_count": 115,
        "instructions": "Ask questions and eliminate characters until only the correct one remains.",
    },
    {
        "name": "Chutes and Ladders",
        "description": "Race to the top of the board while climbing ladders and sliding down chutes.",
        "minimum_players": 2,
        "maximum_players": 4,
        "playtime": 20,
        "difficulty": "Easy",
        "categories": ["Family", "Children"],
        "image_url": "/images/games/chutes-and-ladders.jpg",
        "rating": 4.0,
        "review_count": 90,
        "instructions": "Roll the dice and move forward while avoiding the chutes.",
    },
    {
        "name": "Hi Ho! Cherry-O",
        "description": "Collect fruit from your tree and be the first player to fill your basket.",
        "minimum_players": 2,
        "maximum_players": 3,
        "playtime": 15,
        "difficulty": "Easy",
        "categories": ["Family", "Children"],
        "image_url": "/images/games/hi-ho-cherry-o.jpg",
        "rating": 3.9,
        "review_count": 75,
        "instructions": "Spin the spinner and collect or lose fruit according to the result.",
    },
    {
        "name": "Cranium",
        "description": "Work with your team to complete creative challenges and reach the finish.",
        "minimum_players": 4,
        "maximum_players": 16,
        "playtime": 60,
        "difficulty": "Medium",
        "categories": ["Party", "Family"],
        "image_url": "/images/games/cranium.jpg",
        "rating": 4.2,
        "review_count": 125,
        "instructions": "Complete activities involving words, drawing, acting, and trivia.",
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
