"""Regression: parallel requests must not collide on a file-backed SQLite database.

The browser fires several requests at once on first load. With every session sharing ONE connection, the
manual BEGIN used for SQLite savepoints raised 'cannot start a transaction within a transaction' (HTTP 500).
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, fake_tools_client

P = "/api/v1"


def test_parallel_requests_on_a_file_database_all_succeed(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'parallel.db').as_posix()}"
    app = create_app(
        Settings(_env_file=None, database_url=url, auto_create_tables=True, reminder_poll_seconds=0, rate_limit_per_minute=100000),
        llm_client=FakeLLM().client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(),
    )
    with TestClient(app) as c:
        h = login_guest(c)
        paths = ["/conversations", "/preferences", "/dashboard/summary", "/appointments", "/notifications", "/tasks", "/agents", "/providers?city=Guntur"]

        def hit(i: int) -> int:
            return c.get(P + paths[i % len(paths)], headers=h).status_code

        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(pool.map(hit, range(96)))
    assert codes.count(200) == len(codes), {code: codes.count(code) for code in set(codes)}


def test_parallel_writes_on_a_file_database(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'writes.db').as_posix()}"
    app = create_app(
        Settings(_env_file=None, database_url=url, auto_create_tables=True, reminder_poll_seconds=0, rate_limit_per_minute=100000),
        llm_client=FakeLLM().client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(),
    )
    with TestClient(app) as c:
        h = login_guest(c)

        def create(i: int) -> int:
            return c.post(f"{P}/conversations", json={"title": f"chat {i}"}, headers=h).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(create, range(24)))
        assert codes.count(201) == 24, codes
        assert c.get(f"{P}/conversations?limit=100", headers=h).json()["total"] == 24
