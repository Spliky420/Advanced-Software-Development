import sqlite3
import sys
from pathlib import Path

import pytest


HYUNWOO_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = HYUNWOO_DIR / "backend"
DATABASE_DIR = HYUNWOO_DIR / "database"

sys.path.insert(0, str(BACKEND_DIR))

import app as app_module
import db


# Give each test a fresh copy of the sample database.
@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "bills.db"

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            (DATABASE_DIR / "init.sql").read_text(encoding="utf-8")
        )
        connection.executescript(
            (DATABASE_DIR / "seed.sql").read_text(encoding="utf-8")
        )

    monkeypatch.setattr(db, "DB_PATH", str(database_path))
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as test_client:
        yield test_client
