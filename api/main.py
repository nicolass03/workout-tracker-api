from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.config import get_settings
from api.database import close_db, init_db
from api.routers import activity, auth, health, places, sessions, strength


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db(settings)
    yield
    await close_db()


app = FastAPI(
    title="Workout Tracker API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(activity.router)
app.include_router(places.router)
app.include_router(sessions.router)
app.include_router(strength.router)
