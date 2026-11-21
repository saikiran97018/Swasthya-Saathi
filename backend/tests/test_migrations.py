"""The Alembic migration must build exactly the schema the models describe (and be reversible)."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path):
    from app.database.models import Base

    db = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db.as_posix()}"

    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert set(Base.metadata.tables) <= _tables(db)

    # no drift: autogenerate against the migrated database finds nothing to change
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr

    down = _alembic(url, "downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert _tables(db) <= {"alembic_version"}
