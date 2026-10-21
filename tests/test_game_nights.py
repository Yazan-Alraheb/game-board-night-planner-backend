from app.main import app


EXPECTED_ROUTES = {
    ("/api/game-nights", "GET"),
    ("/api/game-nights", "POST"),
    ("/api/game-nights/{id}", "GET"),
    ("/api/game-nights/{id}", "PUT"),
    ("/api/game-nights/{id}", "DELETE"),
    ("/api/game-nights/{id}/members", "GET"),
    ("/api/game-nights/{id}/members", "POST"),
    ("/api/game-nights/{id}/rsvp", "PUT"),
    ("/api/game-nights/{id}/members/{user_id}", "DELETE"),
    ("/api/game-nights/{id}/games", "GET"),
    ("/api/game-nights/{id}/games", "POST"),
    ("/api/game-nights/{id}/games/{game_id}", "DELETE"),
}


def test_game_night_api_contract():
    openapi = app.openapi()
    paths = openapi["paths"]

    actual_routes = {
        (path, method.upper())
        for path, operations in paths.items()
        for method in operations
    }

    missing_routes = EXPECTED_ROUTES - actual_routes
    assert not missing_routes, f"Missing routes: {missing_routes}"

    assert "requestBody" in paths["/api/game-nights"]["post"]
    assert "requestBody" in paths["/api/game-nights/{id}"]["put"]
    assert "requestBody" in paths["/api/game-nights/{id}/members"]["post"]
    assert "requestBody" in paths["/api/game-nights/{id}/rsvp"]["put"]
    assert "requestBody" in paths["/api/game-nights/{id}/games"]["post"]

    assert "201" in paths["/api/game-nights"]["post"]["responses"]
    assert "204" in paths["/api/game-nights/{id}"]["delete"]["responses"]