from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from api.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, int] = {}
    engine_kwargs: dict = {
        "echo": False,
    }

    if settings.uses_transaction_pooler:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_pre_ping"] = True

    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    return create_async_engine(settings.async_database_url, **engine_kwargs)


def init_db(settings: Settings | None = None) -> None:
    global _engine, _session_factory

    settings = settings or get_settings()
    _engine = create_engine(settings)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized. Call init_db() first.")
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
