"""Async engine + session factory."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str | None = None) -> AsyncEngine:
    """Create (or replace) the global engine. Tests call this with a SQLite URL."""
    global _engine, _session_factory
    url = database_url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}  # wait up to 30 s on a locked file
        if ":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite:"):
            # An in-memory database exists only inside ONE connection, so every session must share it (tests only).
            # File databases must NOT do this: sessions would then share a connection and collide on BEGIN.
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        _enable_sqlite_savepoints(_engine)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _enable_sqlite_savepoints(engine: AsyncEngine) -> None:
    """SQLAlchemy's documented recipe: make the SQLite driver honour BEGIN/SAVEPOINT, which the booking
    double-booking guard relies on. (PostgreSQL needs nothing.)"""
    from sqlalchemy import event

    in_memory = ":memory:" in str(engine.url)

    @event.listens_for(engine.sync_engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None  # stop the driver from emitting its own BEGIN
        if not in_memory:  # WAL: readers don't block the writer; far better for a file shared by concurrent requests
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _begin(conn):
        # Take the write lock up front. A deferred BEGIN that later upgrades read -> write fails instantly with
        # "database is locked" when another writer got in first (the busy timeout does not apply to upgrades);
        # BEGIN IMMEDIATE makes concurrent requests queue behind the busy timeout instead.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
