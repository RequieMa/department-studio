import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from department_studio.domain import LeadCreate
from department_studio.store import Store

LEGACY_SCHEMA = Path(__file__).with_name("fixtures").joinpath("schema_v0.sql").read_text()
TABLES = ("room", "leads", "sessions", "chains", "messages", "deliveries", "receipts")


def legacy_database(path, workspace):
    """Generate v0 data without ever opening any deployed database."""
    settings = LeadCreate("Historical", "atlas", "Build", "test", "model-a", str(workspace))
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO leads VALUES(?,?,?,?,?,?)",
            (
                "lead",
                "atlas",
                json.dumps(asdict(settings)),
                "conversation",
                3,
                5,
            ),
        )
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            (
                "conversation",
                "lead",
                "native-reference",
                "created",
            ),
        )
        db.execute("INSERT INTO chains VALUES('chain',NULL,1,8)")
        db.execute(
            "INSERT INTO messages VALUES(1,'message','human',NULL,'You','you','@atlas work',"
            "'[\"lead\"]','[\"atlas\"]','chain','created',NULL)"
        )
        db.execute("UPDATE chains SET root_message_id='message'")
        db.execute(
            "INSERT INTO deliveries VALUES('delivery','chain','message','lead','conversation',"
            "5,'completed','created','started','finished',NULL,'native-reference',NULL)"
        )
        db.execute("INSERT INTO receipts VALUES('delivery','call','fingerprint','{}')")
    return path


def table_snapshot(path):
    with sqlite3.connect(path) as db:
        return {
            table: (
                [row[1] for row in db.execute(f"PRAGMA table_info({table})")],
                db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall(),
            )
            for table in TABLES
        }


def test_v0_migration_retains_every_existing_field_and_is_repeatable(tmp_path):
    path = legacy_database(tmp_path / "legacy.sqlite", tmp_path)
    before = table_snapshot(path)
    with Store(path) as store:
        assert store.get_lead("lead").revision == 3
        assert store.get_lead("lead").deleted_at is None
        assert store.list_session_refs("lead")[0]["native_session_ref"] == "native-reference"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, (columns, rows) in before.items():
            assert (
                db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY rowid").fetchall()
                == rows
            )
    migrated = table_snapshot(path)
    with Store(path):
        pass
    assert table_snapshot(path) == migrated


def test_new_database_has_version_one_and_nullable_tombstone(tmp_path):
    path = tmp_path / "new.sqlite"
    with Store(path):
        pass
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = {r[1]: r for r in db.execute("PRAGMA table_info(leads)")}
        assert columns["deleted_at"][2:4] == ("TEXT", 0)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("version", [2, 999, -1])
def test_unknown_version_rejected_before_schema_or_journal_writes(tmp_path, version):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE future_secret(value)")
        db.execute("INSERT INTO future_secret VALUES('preserve')")
        db.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="schema version"):
        Store(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + "-wal").exists()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("future_secret",)
        ]


def test_migration_failure_rolls_back_schema_and_version_and_closes_connection(
    tmp_path, monkeypatch
):
    path = legacy_database(tmp_path / "legacy.sqlite", tmp_path)
    before = table_snapshot(path)
    connect = sqlite3.connect
    connections = []

    class FaultyConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.strip().upper() == "PRAGMA USER_VERSION=1":
                raise sqlite3.OperationalError("synthetic version write failure")
            return super().execute(sql, *args, **kwargs)

    def faulty_connect(*args, **kwargs):
        db = connect(*args, **kwargs, factory=FaultyConnection)
        connections.append(db)
        return db

    with monkeypatch.context() as patch:
        patch.setattr("department_studio.store.sqlite3.connect", faulty_connect)
        with pytest.raises(sqlite3.OperationalError, match="synthetic"):
            Store(path)
    assert table_snapshot(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    with Store(path):
        pass
