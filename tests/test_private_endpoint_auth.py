import re

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.database import Base, get_db
from app.main import app
from app.models.user import User

PUBLIC_ENDPOINTS = {
    ("GET", "/"),
    ("GET", "/api/games"),
    ("GET", "/api/games/{id}"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
}


def api_endpoints():
    endpoints = []

    for context in iter_route_contexts(app.routes):
        if not isinstance(context.route, APIRoute):
            continue

        for method in (context.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue

            endpoints.append(
                (method, context.path, context)
            )

    return sorted(
        endpoints,
        key=lambda item: (item[1], item[0]),
    )


def test_route_discovery_includes_backend_routes():
    registered = {
        (method, path)
        for method, path, _ in api_endpoints()
    }

    expected = {
        ("POST", "/api/auth/login"),
        ("GET", "/api/games"),
        ("GET", "/api/users/{id}"),
        ("POST", "/api/recommendations"),
        ("GET", "/api/conversations"),
    }

    assert expected <= registered, (
        f"Missing routes: {expected - registered}"
    )


def uses_auth_dependency(dependant):
    return any(
        dependency.call is get_current_user
        or uses_auth_dependency(dependency)
        for dependency in dependant.dependencies
    )


def private_endpoints():
    return [
        (method, path)
        for method, path, _ in api_endpoints()
        if (method, path) not in PUBLIC_ENDPOINTS
    ]


@pytest.mark.parametrize("method,path", private_endpoints())
def test_every_private_endpoint_uses_jwt_dependency(method, path):
    route = next(
        route for current_method, current_path, route in api_endpoints()
        if (current_method, current_path) == (method, path)
    )
    assert uses_auth_dependency(route.dependant), (
        f"{method} {path} is missing Depends(get_current_user)"
    )


def test_public_endpoint_allowlist_matches_registered_routes():
    registered = {(method, path) for method, path, _ in api_endpoints()}
    assert PUBLIC_ENDPOINTS <= registered, (
        f"Public allowlist contains missing routes: {PUBLIC_ENDPOINTS - registered}"
    )
    assert private_endpoints(), "Expected at least one protected API endpoint"


@pytest.mark.parametrize("method,path", private_endpoints())
def test_private_endpoints_advertise_bearer_auth_in_swagger(method, path):
    operation = app.openapi()["paths"][path][method.lower()]
    assert operation.get("security") == [{"HTTPBearer": []}], (
        f"{method} {path} is missing the HTTPBearer Swagger security declaration"
    )


@pytest.mark.parametrize("method,path", sorted(PUBLIC_ENDPOINTS))
def test_public_endpoints_do_not_require_jwt(method, path):
    route = next(
        route for current_method, current_path, route in api_endpoints()
        if (current_method, current_path) == (method, path)
    )
    assert not uses_auth_dependency(route.dependant), (
        f"Public endpoint {method} {path} now requires a JWT"
    )
    operation = app.openapi()["paths"][path][method.lower()]
    assert not operation.get("security"), (
        f"Public endpoint {method} {path} is marked as JWT-protected in Swagger"
    )


@pytest.fixture
def anonymous_client(auth_environment):
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path", private_endpoints())
@pytest.mark.parametrize(
    "authorization", [None, "Bearer not-a-jwt", "Bearer 1", "Basic abc"]
)
def test_private_endpoint_rejects_unauthenticated_requests(
    anonymous_client, method, path, authorization
):
    concrete_path = re.sub(r"\{[^{}]+\}", "1", path)
    headers = {} if authorization is None else {"Authorization": authorization}

    response = anonymous_client.request(
        method,
        concrete_path,
        headers=headers,
        json={} if method in {"POST", "PUT", "PATCH"} else None,
        follow_redirects=False,
    )

    assert response.status_code == 401, (
        f"{method} {path} with Authorization={authorization!r} "
        f"returned {response.status_code}, not 401: {response.text}"
    )
    assert response.headers.get("www-authenticate") == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.fixture
def user_client(auth_environment):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__])
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def test_real_tokens_allow_access_but_other_users_cannot_modify_data(user_client):
    alice = user_client.post("/api/auth/register", json={
        "name": "Alice", "email": "alice-security@example.com",
        "password": "testing-password-123",
    })
    bob = user_client.post("/api/auth/register", json={
        "name": "Bob", "email": "bob-security@example.com",
        "password": "testing-password-456",
    })
    assert alice.status_code == 201, alice.text
    assert bob.status_code == 201, bob.text

    alice_id = alice.json()["user"]["id"]
    bob_token = bob.json()["access_token"]
    alice_token = alice.json()["access_token"]
    alice_auth = {"Authorization": f"Bearer {alice_token}"}
    bob_auth = {"Authorization": f"Bearer {bob_token}"}

    profile = user_client.get(f"/api/users/{alice_id}", headers=alice_auth)
    assert profile.status_code == 200, profile.text
    assert profile.json()["user"]["id"] == alice_id

    assert user_client.get(f"/api/users/{alice_id}").status_code == 401
    private_preferences = user_client.get(
        f"/api/users/{alice_id}/preferences", headers=bob_auth
    )
    other_collection = user_client.get(
        f"/api/users/{alice_id}/collection", headers=bob_auth
    )
    assert private_preferences.status_code == 403
    assert other_collection.status_code == 403

    changed = user_client.put(
        f"/api/users/{alice_id}",
        headers=bob_auth,
        json={"name": "Hacked"},
    )
    assert changed.status_code == 403, changed.text

    # The unauthorized attempt must not have modified Alice's name.
    profile_after = user_client.get(f"/api/users/{alice_id}", headers=alice_auth)
    assert profile_after.status_code == 200
    assert profile_after.json()["user"]["name"] == "Alice"


def test_login_issues_a_token_accepted_by_private_routes(user_client):
    registration = user_client.post("/api/auth/register", json={
        "name": "Tester", "email": "login-security@example.com",
        "password": "correct-password-123",
    })
    assert registration.status_code == 201, registration.text

    login = user_client.post("/api/auth/login", json={
        "email": "login-security@example.com", "password": "correct-password-123",
    })
    assert login.status_code == 200, login.text
    assert login.json()["token_type"] == "bearer"

    user_id = login.json()["user"]["id"]
    token = login.json()["access_token"]
    result = user_client.get(
        f"/api/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert result.status_code == 200, result.text
