from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.game import Game
from app.models.game_night import GameNight
from app.models.game_night_member import GameNightMember
from app.models.preference import Preference
from app.models.user import User
from app.models.user_game import UserGame


@pytest.fixture
def recommendations(auth_environment):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[model.__table__ for model in
        [User, Game, UserGame, Preference, GameNight, GameNightMember]])
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=i, name=f"Player {i}", email=f"secret{i}@example.com",
                         password_hash="private-hash") for i in range(1, 7)])
        db.add_all([Game(id=i, name=f"Game {i}", minimum_players=2, maximum_players=4,
                         playtime=60, difficulty="Medium", categories=["Strategy"])
                    for i in range(1, 8)])
        db.flush()
        # Past event, host deliberately has no membership; no friendship/chat rows.
        db.add(GameNight(id=1, host_id=1, name="Past night", location="Home",
                         starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
        db.flush()
        db.add_all([GameNightMember(game_night_id=1, user_id=i, status=status)
                    for i, status in [(2, "accepted"), (3, "pending"), (4, "declined")]])
        db.add_all([UserGame(user_id=u, game_id=g, status=status) for u, g, status in
                    [(1, 1, "owned"), (1, 2, "wishlist"), (2, 1, "owned"),
                     (2, 2, "owned"), (3, 3, "owned"), (4, 4, "owned"), (5, 5, "owned")]])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def auth(actor=1):
    return {"Authorization": f"Bearer {create_access_token(actor)}"}


def request(client, actor=1, **fields):
    body = {"mode": "personal", "player_count": 2, "max_playtime": 60, **fields}
    return client.post("/api/recommendations", headers=auth(actor), json=body)


def items(response):
    assert response.status_code == 200, response.text
    return response.json()["recommendations"]


def test_personal_ownership_and_private_response(recommendations):
    client, _ = recommendations
    results = items(request(client))
    assert [r["game"]["id"] for r in results] == [1]
    assert set(results[0]) == {"game", "score", "reason", "owners"}
    assert results[0]["score"] == 50
    assert [o["id"] for o in results[0]["owners"]] == [1]
    assert set(results[0]["owners"][0]) == {"id", "name", "bio", "avatar_url"}
    assert "secret" not in str(results) and "private-hash" not in str(results)


@pytest.mark.parametrize("actor", [1, 2])
def test_event_eligible_candidates_and_all_owners(recommendations, actor):
    client, _ = recommendations
    results = items(request(client, actor, mode="game_night", game_night_id=1))
    assert [r["game"]["id"] for r in results] == [1, 2]
    assert [o["id"] for o in results[0]["owners"]] == [1, 2]
    assert [o["id"] for o in results[1]["owners"]] == [2]


@pytest.mark.parametrize("actor", [3, 4, 5, 6])
def test_event_unauthorized_before_private_queries(recommendations, actor):
    client, factory = recommendations
    queries = []
    def record(conn, cursor, statement, params, context, many):
        queries.append(statement.lower())
    event.listen(factory.kw["bind"], "before_cursor_execute", record)
    try:
        response = request(client, actor, mode="game_night", game_night_id=1)
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record)
    assert response.status_code == 403
    assert not any("from user_games" in q or "from preferences" in q for q in queries)


def test_removed_attendee_and_missing_event(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.delete(db.get(GameNightMember, (1, 2)))
        db.commit()
    assert request(client, 2, mode="game_night", game_night_id=1).status_code == 403
    assert request(client, mode="game_night", game_night_id=999).status_code == 404


@pytest.mark.parametrize("credentials", [None, "Bearer invalid", "Basic abc", "missing-user", "expired"])
def test_real_jwt_authentication(recommendations, credentials):
    from datetime import timedelta
    import jwt
    from app.core.auth_settings import get_auth_settings
    client, _ = recommendations
    if credentials == "missing-user":
        headers = auth(999)
    elif credentials == "expired":
        token = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                           get_auth_settings().jwt_secret_key.get_secret_value(), algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = {} if credentials is None else {"Authorization": credentials}
    assert client.post("/api/recommendations", headers=headers,
                       json={"mode": "personal", "player_count": 2, "max_playtime": 60}).status_code == 401


@pytest.mark.parametrize("body,code", [
    ({}, 422), ({"mode": "personal"}, 422),
    ({"mode": "personal", "max_playtime": 60}, 400),
    ({"mode": "game_night", "max_playtime": 60}, 400),
    ({"mode": "personal", "player_count": 2, "max_playtime": 60, "game_night_id": 1}, 400),
])
def test_required_and_mode_fields(recommendations, body, code):
    client, _ = recommendations
    assert client.post("/api/recommendations", headers=auth(), json=body).status_code == code


@pytest.mark.parametrize("field,value", [
    ("mode", "other"), ("player_count", 0), ("player_count", True), ("player_count", "2"),
    ("player_count", 2.5), ("player_count", None), ("player_count", 2147483648),
    ("player_count", 10**20), ("max_playtime", 0), ("max_playtime", 2147483648),
    ("max_playtime", 10**20),
    ("max_playtime", -1), ("max_playtime", True), ("max_playtime", "60"),
    ("max_playtime", None), ("game_night_id", 0), ("game_night_id", 2147483648),
    ("game_night_id", True), ("game_night_id", "1"), ("game_night_id", None),
    ("categories", [""]), ("categories", ["   "]), ("categories", [42]),
    ("categories", "Strategy"), ("categories", None), ("experience_level", "Expert"),
    ("experience_level", None), ("unknown", 1),
])
def test_invalid_fields(recommendations, field, value):
    client, _ = recommendations
    assert request(client, **{field: value}).status_code == 422


@pytest.mark.parametrize("players,playtime,expected", [(1,60,[]),(2,60,[1]),(4,60,[1]),(5,60,[]),(2,59,[])])
def test_hard_filter_boundaries(recommendations, players, playtime, expected):
    client, _ = recommendations
    assert [r["game"]["id"] for r in items(request(client, player_count=players, max_playtime=playtime))] == expected


@pytest.mark.parametrize("values,code", [
    ([f"c{i}" for i in range(50)], 200), ([f"c{i}" for i in range(51)], 422),
    (["x" * 100], 200), (["x" * 101], 422),
])
def test_category_count_and_length_limits(recommendations, values, code):
    client, _ = recommendations
    assert request(client, categories=values).status_code == code


@pytest.mark.parametrize("stored", [
    ["Strategy", 5, None, True, {"x": 1}, ["y"]], "Strategy", {"Strategy": 1}, None, [],
])
def test_invalid_stored_game_categories_do_not_fail(recommendations, stored):
    client, factory = recommendations
    with factory() as db:
        db.get(Game, 1).categories = stored
        db.commit()
    expected = ["Strategy"] if isinstance(stored, list) and stored else []
    for body in ({}, {"categories": ["Strategy"]}, {"mode": "game_night", "game_night_id": 1}):
        game = next(r["game"] for r in items(request(client, **body)) if r["game"]["id"] == 1)
        assert game["categories"] == expected


def test_numeric_upper_bounds_are_accepted(recommendations):
    client, _ = recommendations
    limit = 2147483647
    assert items(request(client, player_count=limit, max_playtime=limit)) == []
    assert [r["game"]["id"] for r in items(request(client, max_playtime=limit))] == [1]


def test_group_questionnaire_keeps_attendee_dislikes_and_favorites(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.get(Game, 2).categories = ["Party"]
        db.add(Preference(user_id=1, favorite_categories=[], disliked_categories=["Strategy"]))
        db.add(Preference(user_id=2, favorite_categories=["Party"], disliked_categories=[]))
        db.commit()
    results = items(request(client, mode="game_night", game_night_id=1, categories=["Strategy"]))
    # Game 1: 30 requested + 10 + mean saved (25, 15) - 20 * 1/2 host dislike = 50.
    # Game 2: 0 requested + 10 + mean saved (25, 35) = 40; the request erases no favorite.
    assert [(r["game"]["id"], r["score"]) for r in results] == [(1, 50), (2, 40)]
    assert results[0]["reason"].endswith("Some saved group preferences count against this game.")
    assert results[1]["reason"].endswith("Fits saved group preferences.")
    assert all("Player" not in r["reason"] and "dislike" not in r["reason"].lower() for r in results)


def test_event_default_host_deduplication_and_override(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(GameNightMember(game_night_id=1, user_id=1, status="accepted"))
        db.commit()
    body = {"mode": "game_night", "game_night_id": 1, "max_playtime": 60}
    result = items(client.post("/api/recommendations", headers=auth(), json=body))
    assert len(result) == 2 and "Supports 2 players" in result[0]["reason"]
    assert items(request(client, mode="game_night", game_night_id=1, player_count=5)) == []


def test_personal_dislikes_explicit_override_and_category_soft_scoring(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(Preference(user_id=1, favorite_categories=[], disliked_categories=[" STRATEGY "]))
        db.commit()
    assert items(request(client)) == []
    assert len(items(request(client, categories=[" strategy ", "STRATEGY"]))) == 1
    with factory() as db:
        db.query(Preference).delete()
        db.commit()
    assert len(items(request(client, categories=["Unknown"], experience_level="Experienced"))) == 1


def test_group_dislikes_penalize_not_exclude_and_host_is_not_double_counted(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(Preference(user_id=1, favorite_categories=[], disliked_categories=["Strategy"]))
        db.add(GameNightMember(game_night_id=1, user_id=1, status="accepted"))
        db.commit()
    results = items(request(client, mode="game_night", game_night_id=1))
    assert len(results) == 2 and all(r["score"] == 40 for r in results)
    assert all("dislike" not in r["reason"].lower() and "Player" not in r["reason"] for r in results)


def test_null_categories_empty_collection_and_stable_ranking(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(UserGame(user_id=1, game_id=6, status="owned"))
        db.get(Game, 6).categories = None
        db.commit()
    results = items(request(client))
    assert [r["game"]["id"] for r in results] == [1, 6]
    assert results[1]["game"]["categories"] == []
    assert items(request(client, actor=6)) == []
    assert [r["game"]["id"] for r in items(request(client, categories=["Party"]))] == [1, 6]


def test_scoring_uses_saved_attendee_preferences(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.get(Game, 2).difficulty = "Easy"
        db.add(Preference(user_id=2, favorite_categories=[], disliked_categories=[], preferred_difficulty="Easy"))
        # A pending attendee's opposite preferences must not affect scores.
        db.add(Preference(user_id=3, favorite_categories=[], disliked_categories=["Strategy"], preferred_difficulty="Hard"))
        db.commit()
    results = items(request(client, mode="game_night", game_night_id=1))
    assert [r["game"]["id"] for r in results] == [2, 1]
    assert [r["score"] for r in results] == [53.75, 50]


def test_read_only_bounded_query_count(recommendations):
    client, factory = recommendations
    for size in [0, 30]:
        with factory() as db:
            for i in range(10, 10 + size):
                db.add(Game(id=i, name=f"Game {i}", minimum_players=1, maximum_players=10,
                            playtime=20, difficulty="Easy", categories=[]))
            db.flush()
            db.add_all([UserGame(user_id=2, game_id=i, status="owned") for i in range(10, 10 + size)])
            db.commit()
        queries = []
        def record(conn, cursor, statement, params, context, many):
            queries.append(statement.strip().lower())
        event.listen(factory.kw["bind"], "before_cursor_execute", record)
        try:
            assert len(items(request(client, mode="game_night", game_night_id=1))) == 2 + size
        finally:
            event.remove(factory.kw["bind"], "before_cursor_execute", record)
        assert len(queries) == 5  # JWT user, event, eligible IDs, candidates+owners, preferences.
        assert all(q.startswith("select") for q in queries)


def test_openapi_contract():
    operation = app.openapi()["paths"]["/api/recommendations"]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert set(operation["responses"]) == {"200", "400", "401", "403", "404", "422"}
    schemas = app.openapi()["components"]["schemas"]
    request_schema = schemas["RecommendationRequest"]
    assert request_schema["required"] == ["mode", "max_playtime"]
    assert request_schema["additionalProperties"] is False
    assert schemas["Recommendation"]["properties"]["score"]["minimum"] == 0
    assert schemas["Recommendation"]["properties"]["score"]["maximum"] == 100


def test_unrounded_scores_control_order(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(UserGame(user_id=1, game_id=6, status="owned"))
        db.get(Game, 1).playtime = 9999
        db.get(Game, 6).playtime = 9998
        db.add(Preference(user_id=1, favorite_categories=[], disliked_categories=[], preferred_playtime=1))
        db.commit()
    results = items(request(client, max_playtime=10000))
    assert [r["game"]["id"] for r in results] == [6, 1]
    assert results[0]["score"] == results[1]["score"]


def test_personal_saved_preferences_and_playtime_are_soft(recommendations):
    client, factory = recommendations
    with factory() as db:
        db.add(Preference(user_id=1, favorite_categories=[" Strategy "], disliked_categories=[],
                          preferred_difficulty="Medium", preferred_playtime=30))
        db.commit()
    results = items(request(client))
    assert results[0]["score"] == 67.5
    assert "saved favorite" in results[0]["reason"]


def test_default_player_count_includes_host_without_membership(recommendations):
    client, _ = recommendations
    body = {"mode": "game_night", "game_night_id": 1, "max_playtime": 60}
    results = items(client.post("/api/recommendations", headers=auth(2), json=body))
    assert len(results) == 2 and "Supports 2 players" in results[0]["reason"]


def test_checked_in_openapi_matches_recommendation_contract():
    from pathlib import Path
    import yaml
    spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "gamenight-openapi.yaml").read_text(encoding="utf-8"))
    schema = spec["components"]["schemas"]["RecommendationRequest"]
    generated = app.openapi()["components"]["schemas"]["RecommendationRequest"]
    assert schema["required"] == generated["required"]
    assert set(schema["properties"]) == set(generated["properties"])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["experience_level"]["enum"] == ["Beginner", "Intermediate", "Experienced"]
    for name in ("game_night_id", "player_count", "max_playtime"):
        assert schema["properties"][name]["maximum"] == 2147483647
    assert generated["properties"]["max_playtime"]["maximum"] == 2147483647
    assert generated["properties"]["player_count"]["anyOf"][0]["maximum"] == 2147483647
    assert schema["properties"]["categories"]["items"]["minLength"] == 1
    for spec_schema in (schema, generated):
        assert spec_schema["properties"]["categories"]["maxItems"] == 50
        assert spec_schema["properties"]["categories"]["items"]["maxLength"] == 100
    assert set(spec["paths"]["/api/recommendations"]["post"]["responses"]) == set(app.openapi()["paths"]["/api/recommendations"]["post"]["responses"])
