"""Shared fixtures. Tests run against fake LLM / speech backends (no network, no keys) and, by default, in-memory SQLite.

To run the same suite on PostgreSQL set TEST_DATABASE_URL to a dedicated database whose name ends in `_test`
(every table is dropped before each test), e.g.
    $env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<password>@localhost:5432/voiceagent_test"
"""
import os

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if TEST_DATABASE_URL and not TEST_DATABASE_URL.split("?")[0].rstrip("/").endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point at a database whose name ends with '_test': its tables are dropped before every test")

# Must be set before the app (and its settings) are imported.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DATABASE_URL or "sqlite+aiosqlite:///:memory:",
        "SARVAM_API_KEY": "",
        "SPEECH_PROVIDER": "auto",
        "LLM_FALLBACK_BASE_URL": "",
        "LLM_FALLBACK_API_KEY": "",
        "LLM_FALLBACK_MODEL": "",
        "LLM_EXTRA_BODY": "",
        "LLM_FALLBACK_EXTRA_BODY": "",
        "AUTO_CREATE_TABLES": "true",
        "AUTO_SEED": "true",
        "SEED_DEMO_PROVIDERS": "true",  # tests exercise the slot engine on invented partner clinics; the app itself seeds none
        "JWT_SECRET": "test-secret-not-for-production-use-0123456789",
        "LLM_BASE_URL": "https://llm.test/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "test-model",
        "BHASHINI_USER_ID": "test-user",
        "BHASHINI_ULCA_API_KEY": "test-ulca-key",
        "TAVILY_API_KEY": "",
        "SEARXNG_URL": "",
        "WEBHOOK_URL": "",
        "WEBHOOK_SECRET": "",
        "REMINDER_POLL_SECONDS": "0",
        "DEMO_MODE": "true",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "RATE_LIMIT_AI_PER_MINUTE": "100000",
        "AGENT_MAX_STEPS": "4",
        "MAX_AUDIO_BYTES": "400000",
    }
)

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.fakes import FakeBhashini, FakeLLM, fake_tools_client

get_settings.cache_clear()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _fresh_postgres():
    """On PostgreSQL every test starts from an empty schema (the app recreates and re-seeds it on startup)."""
    if not TEST_DATABASE_URL:
        yield
        return
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.database.models import Base

    async def reset():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(reset())
    yield


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM([{"content": "Hello! How can I help?"}])


@pytest.fixture
def bhashini() -> FakeBhashini:
    return FakeBhashini()


@pytest.fixture
def make_client(llm, bhashini):
    """Factory so a test can tweak settings; all created clients are cleaned up."""
    opened: list[TestClient] = []

    def factory(**settings_overrides) -> TestClient:
        app = create_app(
            _settings(**settings_overrides),
            llm_client=llm.client(),
            bhashini_client=bhashini.client(),
            tools_client=fake_tools_client(),
        )
        client = TestClient(app)
        client.__enter__()
        opened.append(client)
        return client

    yield factory
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def login_guest(client: TestClient, name: str | None = None) -> dict[str, str]:
    """Create a guest user and return Authorization headers."""
    body = {"display_name": name} if name else None
    r = client.post("/api/v1/auth/guest", json=body)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client) -> dict[str, str]:
    return login_guest(client)
