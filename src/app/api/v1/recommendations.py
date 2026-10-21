from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.game import Game
from app.models.game_night import GameNight
from app.models.game_night_member import GameNightMember
from app.models.preference import Preference
from app.models.user import User
from app.models.user_game import UserGame
from app.schemas.recommendation import (
    Recommendation, RecommendationError, RecommendationListResponse, RecommendationRequest,
)
from app.services.recommendations import (
    GameFeatures, SavedPreferences, categories, explain, personally_disliked, score_game,
)


router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.post(
    "", response_model=RecommendationListResponse, operation_id="post_api_recommendations",
    responses={code: {"model": RecommendationError, "description": description}
               for code, description in {
                   400: "Invalid mode-specific fields", 401: "Missing or invalid authentication",
                   403: "Not the host or an accepted attendee", 404: "Game night not found",
               }.items()},
)
def recommend(
    data: RecommendationRequest, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = data.mode == "game_night"
    if not group:
        if "game_night_id" in data.model_fields_set:
            raise HTTPException(status_code=400, detail="Personal mode cannot include game_night_id")
        if data.player_count is None:
            raise HTTPException(status_code=400, detail="Personal mode requires player_count")
        participant_ids = {current_user.id}
    else:
        if data.game_night_id is None:
            raise HTTPException(status_code=400, detail="Game-night mode requires game_night_id")
        night = db.get(GameNight, data.game_night_id)
        if night is None:
            raise HTTPException(status_code=404, detail="Game night not found")
        if night.host_id != current_user.id:
            membership = db.get(GameNightMember, (night.id, current_user.id))
            if membership is None or membership.status != "accepted":
                raise HTTPException(status_code=403, detail="Not the host or an accepted attendee")
        # Authorization must precede all other participants' collections/preferences.
        participant_ids = {night.host_id} | {
            row[0] for row in db.query(GameNightMember.user_id).filter(
                GameNightMember.game_night_id == night.id,
                GameNightMember.status == "accepted",
            ).all()
        }
    player_count = data.player_count if data.player_count is not None else len(participant_ids)
    rows = db.query(UserGame).join(UserGame.game).options(
        joinedload(UserGame.game), joinedload(UserGame.user),
    ).filter(
        UserGame.user_id.in_(participant_ids), UserGame.status == "owned",
        Game.minimum_players <= player_count, Game.maximum_players >= player_count,
        Game.playtime <= data.max_playtime,
    ).order_by(UserGame.game_id, UserGame.user_id).all()
    saved = {p.user_id: SavedPreferences(
        favorites=categories(p.favorite_categories), dislikes=categories(p.disliked_categories),
        difficulty=p.preferred_difficulty, playtime=p.preferred_playtime,
    ) for p in db.query(Preference).filter(Preference.user_id.in_(participant_ids)).all()}
    preferences = [saved.get(user_id, SavedPreferences()) for user_id in sorted(participant_ids)]
    requested = categories(data.categories)
    games = {}
    for row in rows:
        if row.game_id not in games:
            games[row.game_id] = (row.game, [])
        games[row.game_id][1].append(row.user)
    ranked = []
    for game_id, (game, owners) in games.items():
        features = GameFeatures(categories(game.categories), game.difficulty, game.playtime)
        if not group and personally_disliked(features, preferences[0], requested):
            continue
        score = score_game(features, preferences, requested, data.experience_level, group=group)
        result = Recommendation(
            game=game, score=round(score, 2), owners=owners,
            reason=explain(features, preferences, requested, data.experience_level,
                           player_count, data.max_playtime, group=group),
        )
        ranked.append((score, game_id, result))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return {"recommendations": [item[2] for item in ranked]}
