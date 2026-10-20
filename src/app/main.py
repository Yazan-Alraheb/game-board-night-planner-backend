from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.auth_settings import get_auth_settings
from app.routes import user



@asynccontextmanager
async def lifespan(app: FastAPI):
    get_auth_settings()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(user.router)


@app.get("/")
async def root():
    return {"message": "Game Board Night Planner API"}
