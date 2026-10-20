from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models
from app.core.auth_settings import get_auth_settings
from app.routes import user

from app.api.v1.users import router as users_router
from app.api.v1.games import router as games_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_auth_settings()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(user.router)

app.include_router(games_router)

app.include_router(users_router)


@app.get("/")
async def root():
    return {"message": "Game Board Night Planner API"}
