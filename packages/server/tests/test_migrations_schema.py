from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from server.db.tables import JobHistory
from sqlalchemy import create_engine, inspect


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def _upgrade_sqlite(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPNEXT_DATABASE_URL", f"sqlite:///{path}")
    command.upgrade(_alembic_config(), "head")


def test_migrations_create_expected_job_history_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "migration-schema.db"
    _upgrade_sqlite(db_path, monkeypatch)

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        actual_columns = {col["name"] for col in inspector.get_columns("job_history")}
        actual_indexes = {idx["name"] for idx in inspector.get_indexes("job_history")}
    finally:
        engine.dispose()

    expected_columns = {col.name for col in JobHistory.__table__.columns}
    expected_indexes = {idx.name for idx in JobHistory.__table__.indexes}

    assert expected_columns == actual_columns
    assert expected_indexes == actual_indexes


def test_migrations_upgrade_head_is_reentrant_for_existing_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "migration-reentrant.db"
    _upgrade_sqlite(db_path, monkeypatch)
    _upgrade_sqlite(db_path, monkeypatch)

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    assert {"job_history", "artifacts", "pending_artifacts"} <= tables
