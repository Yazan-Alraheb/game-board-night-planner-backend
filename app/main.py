from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Game Board Night Planner API"}
