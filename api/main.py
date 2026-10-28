import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.config import get_settings
from api.cache import response_cache
from api.database import close_db, init_db
from api.observability import log_validation_failure
from api.routers import auth, health, places, saved_routes, sessions, strength

error_logger = logging.getLogger("workout_tracker.errors")

# The largest legitimate body is a 32-chunk trace batch (~8 MiB of JSON).
_MAX_BODY_BYTES = 16 * 1024 * 1024
# Unique/foreign-key violations: a duplicate client id, a create race, or a parent
# deleted mid-request. They conflict with current state rather than being server bugs.
_CONFLICT_SQLSTATES = {"23503", "23505"}


class BodySizeLimitMiddleware:
    """Rejects oversized bodies while streaming; FastAPI buffers the body before auth runs."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                raise HTTPException(status_code=413, detail="Request body too large")
            return message

        await self.app(scope, limited_receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db(settings)
    await response_cache.start(settings)
    yield
    await response_cache.close()
    await close_db()


app = FastAPI(
    title="Workout Tracker API",
    version="0.1.0",
    lifespan=lifespan,
)
# Added first so it sits innermost, where FastAPI turns its HTTPException into the 413.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=_MAX_BODY_BYTES)
app.add_middleware(GZipMiddleware, minimum_size=1_000, compresslevel=5)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception:
        # Starlette's default 500 would carry no request id to match against the logs.
        error_logger.exception(
            "Unhandled error request_id=%s %s %s", request_id, request.method, request.url.path
        )
        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
    response.headers["X-Request-ID"] = request_id
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


@app.exception_handler(IntegrityError)
async def integrity_conflict(request: Request, exc: IntegrityError):
    if getattr(exc.orig, "sqlstate", None) not in _CONFLICT_SQLSTATES:
        raise exc
    return JSONResponse({"detail": "Conflicts with existing data"}, status_code=409)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(places.router)
app.include_router(sessions.router)
app.include_router(saved_routes.router)
app.include_router(strength.router)
