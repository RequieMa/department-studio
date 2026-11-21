import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from department_studio.domain import LeadCreate
from department_studio.store import Store
from department_studio.tasks import TASK_SCHEMA

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


def version_one_database(path, workspace):
    legacy_database(path, workspace)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE leads ADD COLUMN deleted_at TEXT")
        db.execute("UPDATE leads SET deleted_at='historical tombstone'")
        db.execute("PRAGMA user_version=1")
    return path


def apply_context_v2(path):
    """Rebuild released schema v2 (context maintenance) without opening Store."""
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE room ADD COLUMN preparation_id TEXT")
        db.execute("ALTER TABLE sessions ADD COLUMN history_cursor INTEGER NOT NULL DEFAULT 0")
        db.execute(
            "ALTER TABLE sessions ADD COLUMN previous_conversation_id TEXT "
            "REFERENCES sessions(conversation_id)"
        )
        db.execute(
            "CREATE TABLE context_checks ("
            "id TEXT UNIQUE NOT NULL, lead_id TEXT PRIMARY KEY REFERENCES leads(id), "
            "conversation_id TEXT NOT NULL REFERENCES sessions(conversation_id), "
            "state TEXT NOT NULL CHECK(state IN "
            "('queued','checking','compacting','stopping','kept','compacted',"
            "'reset','failed','interrupted')), detail TEXT NOT NULL)"
        )
        db.execute("PRAGMA user_version=2")
    return path


def apply_tasks_v2(path):
    """Rebuild the short-lived pre-merge task branch's schema v2 shape."""
    with sqlite3.connect(path) as db:
        for statement in TASK_SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute("PRAGMA user_version=2")
    return path


def tables(path):
    with sqlite3.connect(path) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(path, table):
    with sqlite3.connect(path) as db:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("version", [0, 1])
def test_migration_retains_every_existing_field_and_is_repeatable(tmp_path, version):
    path = legacy_database(tmp_path / "legacy.sqlite", tmp_path)
    if version == 1:
        with sqlite3.connect(path) as db:
            db.execute("ALTER TABLE leads ADD COLUMN deleted_at TEXT")
            db.execute("PRAGMA user_version=1")
    before = table_snapshot(path)
    with Store(path) as store:
        assert store.get_lead("lead").revision == 3
        assert store.get_lead("lead").deleted_at is None
        assert store.list_session_refs("lead")[0]["native_session_ref"] == "native-reference"
        assert store.session_context("conversation") == {
            "history_cursor": 0,
            "previous_conversation_id": None,
            "native_session_ref": None,
        }
        assert store.list_tasks()["tasks"] == []
        assert store.list_action_requests()["action_requests"] == []
        assert store.task_context_for_delivery("delivery") is None
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, (columns_before, rows) in before.items():
            assert (
                db.execute(
                    f"SELECT {','.join(columns_before)} FROM {table} ORDER BY rowid"
                ).fetchall()
                == rows
            )
    migrated = table_snapshot(path)
    with Store(path):
        pass
    assert table_snapshot(path) == migrated


def test_new_database_has_version_three_context_and_tasks(tmp_path):
    path = tmp_path / "new.sqlite"
    with Store(path):
        pass
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        lead_columns = {r[1]: r for r in db.execute("PRAGMA table_info(leads)")}
        assert lead_columns["deleted_at"][2:4] == ("TEXT", 0)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {"context_checks", "tasks", "task_deliveries", "action_requests"} <= tables(path)


@pytest.mark.parametrize("version", [4, 999, -1])
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


@pytest.mark.parametrize("version", [0, 1])
def test_migration_failure_rolls_back_whole_upgrade_and_closes_connection(
    tmp_path, monkeypatch, version
):
    path = tmp_path / "legacy.sqlite"
    if version:
        version_one_database(path, tmp_path)
    else:
        legacy_database(path, tmp_path)
    before = table_snapshot(path)
    connect = sqlite3.connect
    connections = []

    class FaultyConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.strip().upper() == "PRAGMA USER_VERSION=3":
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert "context_checks" not in tables(path)
        assert "tasks" not in tables(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    with Store(path):
        pass


def test_v2_context_migrates_to_v3_without_touching_history(tmp_path):
    path = apply_context_v2(version_one_database(tmp_path / "v2.sqlite", tmp_path))
    before = table_snapshot(path)
    with Store(path) as store:
        assert store.list_tasks()["tasks"] == []
        assert store.get_lead("lead", include_deleted=True).deleted_at == "historical tombstone"
    assert table_snapshot(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {"tasks", "task_deliveries", "task_messages", "action_requests"} <= tables(path)


def test_v2_task_only_database_is_repaired_and_upgraded(tmp_path):
    # The unmerged feature branch labelled task tables as v2. Opening such a local
    # test database must add the context schema rather than assume one v2 shape.
    path = apply_tasks_v2(version_one_database(tmp_path / "tasks-v2.sqlite", tmp_path))
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO tasks VALUES('task',NULL,'task','lead','Title','Context','message',"
            "'chain','open',1,'created','updated')"
        )
    with Store(path) as store:
        assert store.get_task("task")["title"] == "Title"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {"preparation_id"} <= columns(path, "room")
    assert {"history_cursor", "previous_conversation_id"} <= columns(path, "sessions")
    assert "context_checks" in tables(path)


@pytest.mark.parametrize("shape", ["context", "tasks"])
def test_v2_to_v3_failure_rolls_back_entire_upgrade(tmp_path, monkeypatch, shape):
    path = tmp_path / f"{shape}.sqlite"
    version_one_database(path, tmp_path)
    (apply_context_v2 if shape == "context" else apply_tasks_v2)(path)
    before = table_snapshot(path)
    connect = sqlite3.connect

    class FaultyConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.strip().upper() == "PRAGMA USER_VERSION=3":
                raise sqlite3.OperationalError("synthetic v3 failure")
            return super().execute(sql, *args, **kwargs)

    def faulty_connect(*args, **kwargs):
        return connect(*args, **kwargs, factory=FaultyConnection)

    with monkeypatch.context() as patch:
        patch.setattr("department_studio.store.sqlite3.connect", faulty_connect)
        with pytest.raises(sqlite3.OperationalError, match="synthetic v3"):
            Store(path)
    assert table_snapshot(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
