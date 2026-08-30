from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from api.config import get_settings
from api.database import close_db, init_db
from api.observability import log_validation_failure
from api.routers import activity, auth, health, places, saved_trails, sessions, strength


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


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def log_request_validation_error(request: Request, exc: RequestValidationError):
    log_validation_failure(
        request_id=getattr(request.state, "request_id", "unknown"),
        method=request.method,
        path=request.url.path,
        errors=exc.errors(),
    )
    return await request_validation_exception_handler(request, exc)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(activity.router)
app.include_router(places.router)
app.include_router(sessions.router)
app.include_router(saved_trails.router)
app.include_router(strength.router)
