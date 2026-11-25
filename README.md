# GameNight Backend

GameNight is a FastAPI application for organizing board game nights. Users can manage game collections, add friends, plan events, chat, and get game recommendations.

## Requirements

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker with Compose (Linux)

Make sure Docker is running before starting the database. On Windows, use **PowerShell** for the commands below. On macOS, use **Terminal**. WSL users can follow the macOS/Linux commands.

## Setup

### 1. Download the project and install dependencies

These commands work on Windows, macOS, and Linux:

```bash
git clone https://github.com/Yazan-Alraheb/game-board-night-planner-backend.git
cd game-board-night-planner-backend
uv python install 3.14
uv sync
```

### 2. Create your `.env` file

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux / WSL:**

```bash
cp .env.example .env
```

Open `.env` and set:

```dotenv
DATABASE_URL=postgresql+psycopg://gamenight:gamenight_dev@localhost:5433/gamenight
JWT_SECRET_KEY=replace_with_your_generated_secret
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Generate a secure JWT secret on any operating system:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the result into `JWT_SECRET_KEY` in `.env`. **Never commit `.env` to Git.**

### 3. Start PostgreSQL

```bash
docker compose up -d db
```

### 4. Set the Python import path

Run the command for your terminal **once per terminal session** before the next steps.

**Windows (PowerShell):**

```powershell
$env:PYTHONPATH = "src"
```

**macOS / Linux / WSL:**

```bash
export PYTHONPATH=src
```

### 5. Create the database tables (first time only)

```bash
uv run python -c "import app.models; from app.core.database import Base, engine; Base.metadata.create_all(bind=engine)"
```

Optional: add sample games (Catan and Flip 7):

```bash
uv run python scripts/seed_games.py
```

### 6. Start the application

```bash
uv run uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** in your browser to use Swagger UI.



## Database Migration - Username System

The username feature adds a required, unique username to the users table.

### Existing Databases

If your database was created before the username feature, you must apply the migration once.

Stop the FastAPI server and ensure PostgreSQL is running:

```bash
docker compose up -d db
```

Back up the database before applying the migration. Keep the backup outside the repository because it contains sensitive user information.

Apply the migration:

```bash
docker compose exec -T db psql -X -U gamenight -d gamenight -v ON_ERROR_STOP=1 < migrations/011_add_usernames.sql
```

The migration:

- Adds the username column to the users table.
- Generates unique usernames for existing users (e.g., user_1).
- Requires every user to have a username.
- Enforces lowercase usernames.
- Creates a unique username index.
- Preserves existing accounts and relationships.

Do not run the migration again if the username column already exists.

### New Databases

New databases created using SQLAlchemy's create_all() already include the username column and its constraints. No additional username migration is required.




## Authentication

Users can register with a unique username and log in using either their username or email.

### Username Requirements

- Between 3 and 32 characters.
- Letters, numbers, and underscores only.
- Case insensitive and stored in lowercase.
- Must be unique.

### Registration

POST /api/auth/register

```json
{
  "name": "Example Player",
  "username": "player123",
  "email": "player@example.com",
  "password": "password123"
}
```

### Login

POST /api/auth/login

Users can provide either their username or email as the identifier.

```json
{
  "identifier": "player123",
  "password": "password123"
}
```

The existing email-based request format is also supported for backward compatibility.

After logging in, copy the access_token from the response, click Authorize in Swagger, and paste the token.

### User Search

GET /api/users?search=player

Users can search by display name or username.

Prefix a username with @ to perform an exact username search.

Example:

GET /api/users?search=%40player123

Public user profiles include usernames but do not expose email addresses or password hashes.

## Testing

These commands work on Windows, macOS, and Linux:

```bash
# Run all tests
uv run pytest -v

# Run authentication tests only
uv run pytest tests/test_private_endpoint_auth.py -v

# Run pre-commit checks
uv run pre-commit run --all-files
```

Tests use an isolated database; you do not need PostgreSQL running for the standard pytest suite.

## Stop and restart PostgreSQL

Stop PostgreSQL after coding:

```bash
docker compose stop db
```

Restart it next time:

```bash
docker compose up -d db
```

Your database data stays saved in the Docker volume. **Do not run `docker compose down -v` unless you intend to delete that data.**

**Note:** Creating tables does not update existing table structures. Schema changes require a database migration.
