"""SQLite owns public history, identities and transactional delivery reservations."""

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from department_studio.domain import (
    Chain,
    Conflict,
    Delivery,
    Invalid,
    Lead,
    LeadCreate,
    LeadDeletion,
    NotFound,
    Receipt,
    RoomMessage,
    message_text,
    normalize_handle,
)
from department_studio.tasks import TASK_SCHEMA, TaskStore

_ACTIVE = "('running', 'stopping')"
_BUSY = "('queued', 'running', 'stopping')"
_MENTIONS = re.compile(r"(?<![\w@])@([\w-]+)")
# Immutable v0 baseline. Schema upgrades below must also work on existing databases.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS room (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL);
INSERT OR IGNORE INTO room VALUES (1, 1);
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY, handle TEXT UNIQUE NOT NULL COLLATE NOCASE, settings TEXT NOT NULL,
    conversation_id TEXT NOT NULL, revision INTEGER NOT NULL, generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    conversation_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
    native_session_ref TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chains (
    id TEXT PRIMARY KEY, root_message_id TEXT REFERENCES messages(id),
    reserved INTEGER NOT NULL DEFAULT 0, allowance INTEGER NOT NULL,
    CHECK(reserved >= 0 AND reserved <= allowance)
);
CREATE TABLE IF NOT EXISTS messages (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
    sender_kind TEXT NOT NULL, sender_id TEXT, sender_name TEXT NOT NULL,
    sender_handle TEXT NOT NULL, text TEXT NOT NULL, recipient_ids TEXT NOT NULL,
    recipient_handles TEXT NOT NULL, chain_id TEXT REFERENCES chains(id),
    timestamp TEXT NOT NULL, notice TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, chain_id TEXT NOT NULL REFERENCES chains(id),
    message_id TEXT NOT NULL REFERENCES messages(id), lead_id TEXT NOT NULL REFERENCES leads(id),
    conversation_id TEXT NOT NULL REFERENCES sessions(conversation_id),
    generation INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN
        ('queued','running','stopping','completed','failed','interrupted','canceled')),
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error TEXT,
    native_session_ref TEXT, diagnostic TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_lead ON deliveries(lead_id)
    WHERE state IN ('running', 'stopping');
CREATE INDEX IF NOT EXISTS dispatch_queue ON deliveries(state, lead_id);
CREATE TABLE IF NOT EXISTS receipts (
    delivery_id TEXT NOT NULL REFERENCES deliveries(id), call_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(delivery_id, call_id)
);
"""


def _now():
    return datetime.now(UTC).isoformat()


def _stop_cause(error: str) -> str:
    return error.split("; awaiting confirmed stop")[0].rstrip(".")


class Store(TaskStore):
    def __init__(self, path: Path, *, max_chain_deliveries: int = 8):
        if type(max_chain_deliveries) is not int or max_chain_deliveries <= 0:
            raise Invalid("Delivery allowance must be a positive integer.")
        self.max_chain_deliveries = max_chain_deliveries
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5)
        self._db.row_factory = sqlite3.Row
        try:
            # Reject unknown versions before even changing the persistent journal mode.
            self._schema_version()
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=5000")
            with self._transaction():
                # Another opener may have migrated while we waited for the writer lock.
                if self._schema_version() == 0:
                    # These baseline statements contain no embedded semicolons. Do not use
                    # executescript here: it implicitly commits an existing transaction.
                    for statement in _SCHEMA.split(";"):
                        if statement.strip():
                            self._db.execute(statement)
                    self._db.execute("ALTER TABLE leads ADD COLUMN deleted_at TEXT")
                    self._db.execute("PRAGMA user_version=1")
                if self._schema_version() == 1:
                    for statement in TASK_SCHEMA.split(";"):
                        if statement.strip():
                            self._db.execute(statement)
                    self._db.execute("PRAGMA user_version=2")
            self._db.execute("PRAGMA journal_mode=WAL")
        except BaseException:
            self._db.close()
            raise

    def _schema_version(self) -> int:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1, 2}:
            raise RuntimeError("Unsupported database schema version; use a compatible release.")
        return version

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._db.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    @property
    def paused(self) -> bool:
        with self._lock:
            return bool(self._db.execute("SELECT paused FROM room WHERE id=1").fetchone()[0])

    def create_lead(self, data: LeadCreate) -> Lead:
        lead_id, conversation_id = str(uuid4()), str(uuid4())
        try:
            with self._transaction():
                self._db.execute(
                    "INSERT INTO leads(id,handle,settings,conversation_id,revision) "
                    "VALUES(?,?,?,?,1)",
                    (lead_id, data.handle, json.dumps(asdict(data)), conversation_id),
                )
                self._db.execute(
                    "INSERT INTO sessions VALUES(?,?,NULL,?)", (conversation_id, lead_id, _now())
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("That handle is already in use.") from exc
        return self.get_lead(lead_id)

    def get_lead(self, lead_id: str, *, include_deleted: bool = False) -> Lead:
        """Active configuration by default; explicit historical reads never enable writes."""
        with self._lock:
            row = self._db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            if row is None or (row["deleted_at"] is not None and not include_deleted):
                raise NotFound("Department not found.")
            active = self._db.execute(
                f"SELECT state FROM deliveries WHERE lead_id=? AND state IN {_BUSY} "
                "ORDER BY CASE state WHEN 'stopping' THEN 0 WHEN 'running' THEN 1 ELSE 2 "
                "END LIMIT 1",
                (lead_id,),
            ).fetchone()
            settings = json.loads(row["settings"])
            return Lead(
                **settings,
                id=row["id"],
                conversation_id=row["conversation_id"],
                revision=row["revision"],
                status="deleted"
                if row["deleted_at"] is not None
                else (active[0] if active else ("idle" if settings["enabled"] else "disabled")),
                deleted_at=row["deleted_at"],
            )

    def list_leads(self) -> list[Lead]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM leads WHERE deleted_at IS NULL ORDER BY rowid"
            ).fetchall()
            # Another connection can tombstone an ID after the roster query. Finish
            # that cursor first, then read retained records and omit any tombstones.
            leads = [self.get_lead(row[0], include_deleted=True) for row in rows]
            return [lead for lead in leads if lead.deleted_at is None]

    def delete_lead(self, lead_id: str, revision: int) -> LeadDeletion:
        """Tombstone only: no cancellation, file removal, or historical row deletion."""
        if type(revision) is not int or revision < 1:
            raise Invalid("Revision must be a positive integer.")
        with self._transaction():
            lead = self.get_lead(lead_id, include_deleted=True)
            if lead.deleted_at is not None:
                # The precondition applies only to the active -> deleted transition.
                return LeadDeletion(lead.id, lead.revision, lead.deleted_at)
            if lead.revision != revision:
                raise Conflict("Configuration revision changed; reload before deleting.")
            # Future worker/continuation support must extend this busy predicate before
            # activation. Deletion never stops work or makes uncertain work look idle.
            if self._db.execute(
                f"SELECT 1 FROM deliveries WHERE lead_id=? AND state IN {_BUSY} LIMIT 1",
                (lead_id,),
            ).fetchone():
                raise Conflict("Department is busy; wait for all deliveries to finish.")
            deleted_at = _now()
            self._db.execute(
                "UPDATE leads SET deleted_at=?,revision=revision+1 WHERE id=?",
                (deleted_at, lead_id),
            )
            return LeadDeletion(lead_id, lead.revision + 1, deleted_at)

    def update_lead(self, lead_id: str, revision: int, changes: dict) -> Lead:
        try:
            with self._transaction():
                lead = self.get_lead(lead_id)
                if lead.revision != revision:
                    raise Conflict("Configuration revision changed; reload before saving.")
                if lead.status in {"queued", "running", "stopping"}:
                    raise Conflict("Department is busy; wait for all deliveries to finish.")
                settings = {key: getattr(lead, key) for key in LeadCreate.__dataclass_fields__}
                try:
                    data = LeadCreate(**(settings | changes))
                except TypeError as exc:
                    raise Invalid("Unknown configuration field.") from exc
                conversation_id = lead.conversation_id
                if data.workspace != lead.workspace:
                    conversation_id = str(uuid4())
                    self._db.execute(
                        "INSERT INTO sessions VALUES(?,?,NULL,?)",
                        (conversation_id, lead_id, _now()),
                    )
                self._db.execute(
                    "UPDATE leads SET handle=?,settings=?,conversation_id=?,revision=revision+1 "
                    "WHERE id=?",
                    (data.handle, json.dumps(asdict(data)), conversation_id, lead_id),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("That handle is already in use.") from exc
        return self.get_lead(lead_id)

    def list_session_refs(self, lead_id: str) -> list[dict]:
        with self._lock:
            return [
                dict(r)
                for r in self._db.execute(
                    "SELECT * FROM sessions WHERE lead_id=? ORDER BY rowid", (lead_id,)
                )
            ]

    def _resolve_handles(self, handles: list[str], *, human: bool) -> list[str]:
        leads = self.list_leads()
        by_handle = {lead.handle: lead for lead in leads}
        result = []
        for handle in handles:
            handle = normalize_handle(handle)
            if handle == "all" and human:
                result.extend(lead.id for lead in leads if lead.enabled)
            elif handle not in by_handle or not by_handle[handle].enabled:
                raise Invalid(f"Unknown or disabled recipient: @{handle}")
            else:
                result.append(by_handle[handle].id)
        return list(dict.fromkeys(result))

    def resolve_mentions(self, text: str) -> list[str]:
        with self._lock:
            return self._resolve_handles(_MENTIONS.findall(text), human=True)

    def _insert_message(
        self,
        sender: Lead | None,
        text: str,
        recipients: list[str],
        chain_id: str | None,
        notice: str | None = None,
        *,
        task_id: str | None = None,
        source_delivery_id: str | None = None,
    ) -> str:
        message_id = str(uuid4())
        labels = [self.get_lead(lead_id).handle for lead_id in recipients]
        self._db.execute(
            "INSERT INTO messages(id,sender_kind,sender_id,sender_name,sender_handle,text,"
            "recipient_ids,recipient_handles,chain_id,timestamp,notice) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id,
                "lead" if sender else "human",
                sender.id if sender else None,
                sender.name if sender else "You",
                sender.handle if sender else "you",
                text,
                json.dumps(recipients),
                json.dumps(labels),
                chain_id,
                _now(),
                notice,
            ),
        )
        self._link_task_message(task_id, message_id, source_delivery_id)
        return message_id

    def _enqueue(
        self,
        chain_id: str,
        message_id: str,
        recipients: list[str],
        *,
        task_ids: dict[str, str] | None = None,
        task_snapshot: dict | None = None,
    ) -> Receipt:
        # All callers hold the same write transaction used for deletion and claiming.
        leads = [self.get_lead(lead_id) for lead_id in recipients]
        notice = None
        if recipients:
            chain = self.get_chain(chain_id)
            if self.paused:
                notice = "Room is paused. Resume and send a new request to start work."
            elif any(lead.status == "stopping" for lead in leads):
                notice = "A recipient is still stopping. Wait for confirmed idle and send again."
            elif chain.reserved + len(recipients) > chain.allowance:
                notice = (
                    "Delivery allowance reached. No recipients enqueued; send a new human request."
                )
        if notice:
            self._db.execute("UPDATE messages SET notice=? WHERE id=?", (notice, message_id))
            return Receipt(message_id, [], notice)
        self._db.execute(
            "UPDATE chains SET reserved=reserved+? WHERE id=?", (len(recipients), chain_id)
        )
        for lead in leads:
            delivery_id = str(uuid4())
            self._db.execute(
                "INSERT INTO "
                "deliveries(id,chain_id,message_id,lead_id,conversation_id,state,created_at)"
                " VALUES(?,?,?,?,?,'queued',?)",
                (
                    delivery_id,
                    chain_id,
                    message_id,
                    lead.id,
                    lead.conversation_id,
                    _now(),
                ),
            )
            self._link_task_delivery((task_ids or {}).get(lead.id), delivery_id, task_snapshot)
        return Receipt(message_id, recipients)

    def post_human_message(self, text: str) -> Receipt:
        text = message_text(text)
        with self._transaction():
            recipients = self.resolve_mentions(text)
            chain_id = str(uuid4())
            self._db.execute(
                "INSERT INTO chains(id,allowance) VALUES(?,?)",
                (chain_id, self.max_chain_deliveries),
            )
            message_id = self._insert_message(None, text, recipients, chain_id)
            self._db.execute(
                "UPDATE chains SET root_message_id=? WHERE id=?", (message_id, chain_id)
            )
            task_ids = self._create_root_tasks(message_id, chain_id, recipients, text)
            return self._enqueue(chain_id, message_id, recipients, task_ids=task_ids)

    def _is_current(self, delivery_id: str, generation: int) -> bool:
        return (
            not self.paused
            and self._db.execute(
                "SELECT 1 FROM deliveries d JOIN leads l ON l.id=d.lead_id "
                "WHERE d.id=? AND d.generation=? AND l.generation=? AND d.state='running' "
                "AND l.deleted_at IS NULL",
                (delivery_id, generation, generation),
            ).fetchone()
            is not None
        )

    def is_current(self, delivery_id: str, generation: int) -> bool:
        with self._lock:
            return self._is_current(delivery_id, generation)

    def post_bridge_message(
        self, delivery_id: str, generation: int, call_id: str, text: str, recipients: list[str]
    ) -> Receipt:
        text = message_text(text)
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise Invalid("call_id must contain 1–200 characters.")
        if not isinstance(recipients, list) or len(recipients) > 128:
            raise Invalid("recipients must be a list of at most 128 handles.")
        handles = [normalize_handle(h) for h in recipients]
        fingerprint = hashlib.sha256(
            json.dumps([text, handles], ensure_ascii=False).encode()
        ).hexdigest()
        with self._transaction():
            if not self._is_current(delivery_id, generation):
                raise Conflict("Execution generation is no longer active.")
            saved = self._db.execute(
                "SELECT * FROM receipts WHERE delivery_id=? AND call_id=?", (delivery_id, call_id)
            ).fetchone()
            if saved:
                if saved["fingerprint"] != fingerprint:
                    raise Conflict("call_id was already used with different content.")
                return Receipt(**json.loads(saved["receipt"]))
            delivery = self.get_delivery(delivery_id)
            sender = self.get_lead(delivery.lead_id)
            selected = [i for i in self._resolve_handles(handles, human=False) if i != sender.id]
            task_context = self.task_context_for_delivery(delivery_id)
            task_id = task_context["id"] if task_context else None
            message_id = self._insert_message(
                sender,
                text,
                selected,
                delivery.chain_id,
                task_id=task_id,
                source_delivery_id=delivery_id,
            )
            receipt = self._enqueue(
                delivery.chain_id,
                message_id,
                selected,
                task_ids={lead_id: task_id for lead_id in selected} if task_id else None,
                task_snapshot=task_context,
            )
            self._db.execute(
                "INSERT INTO receipts VALUES(?,?,?,?)",
                (delivery_id, call_id, fingerprint, json.dumps(asdict(receipt))),
            )
            return receipt

    def post_public_reply(
        self, lead_id: str, text: str, chain_id: str | None = None
    ) -> RoomMessage:
        text = message_text(text)
        with self._transaction():
            message_id = self._insert_message(self.get_lead(lead_id), text, [], chain_id)
        return self.get_message(message_id)

    @staticmethod
    def _message(row) -> RoomMessage:
        data = dict(row)
        for key in ("recipient_ids", "recipient_handles"):
            data[key] = json.loads(data[key])
        return RoomMessage(**data)

    def list_messages(self) -> list[RoomMessage]:
        with self._lock:
            return [
                self._message(r)
                for r in self._db.execute("SELECT * FROM messages ORDER BY sequence")
            ]

    def recent_messages(self, limit: int = 50) -> tuple[list[RoomMessage], int]:
        with self._lock:
            total = self._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            rows = self._db.execute(
                "SELECT * FROM messages ORDER BY sequence DESC LIMIT ?", (limit,)
            )
            return list(reversed([self._message(r) for r in rows])), max(0, total - limit)

    def get_message(self, message_id: str) -> RoomMessage:
        with self._lock:
            row = self._db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if row is None:
                raise NotFound("Message not found.")
            return self._message(row)

    def get_chain(self, chain_id: str) -> Chain:
        with self._lock:
            row = self._db.execute("SELECT * FROM chains WHERE id=?", (chain_id,)).fetchone()
            if row is None:
                raise NotFound("Conversation chain not found.")
            return Chain(**dict(row))

    def get_delivery(self, delivery_id: str) -> Delivery:
        with self._lock:
            row = self._db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is None:
                raise NotFound("Delivery not found.")
            return Delivery(**dict(row))

    def list_deliveries(self) -> list[Delivery]:
        with self._lock:
            return [
                Delivery(**dict(r))
                for r in self._db.execute("SELECT * FROM deliveries ORDER BY rowid")
            ]

    def claim_delivery(self, max_concurrency: int = 2) -> Delivery | None:
        with self._transaction():
            count = self._db.execute(
                f"SELECT COUNT(*) FROM deliveries WHERE state IN {_ACTIVE}"
            ).fetchone()[0]
            if self.paused or count >= max_concurrency:
                return None
            row = self._db.execute(
                "SELECT d.* FROM deliveries d JOIN leads l ON l.id=d.lead_id "
                "WHERE d.state='queued' AND l.deleted_at IS NULL AND NOT EXISTS "
                f"(SELECT 1 FROM deliveries busy WHERE busy.lead_id=d.lead_id AND "
                f"busy.state IN {_ACTIVE}) "
                "ORDER BY d.rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._db.execute(
                "UPDATE leads SET generation=generation+1 WHERE id=?", (row["lead_id"],)
            )
            generation = self._db.execute(
                "SELECT generation FROM leads WHERE id=?", (row["lead_id"],)
            ).fetchone()[0]
            self._db.execute(
                "UPDATE deliveries SET state='running',generation=?,started_at=? WHERE id=?",
                (generation, _now(), row["id"]),
            )
            return self.get_delivery(row["id"])

    def finish_delivery(
        self,
        delivery_id: str,
        generation: int,
        state: str,
        *,
        text: str = "",
        error: str | None = None,
        native_session_ref: str | None = None,
    ) -> bool:
        if state not in {"completed", "failed", "interrupted"}:
            raise Invalid("Invalid runtime outcome.")
        with self._transaction():
            if not self._is_current(delivery_id, generation):
                self._db.execute(
                    "UPDATE deliveries SET diagnostic=? WHERE id=?",
                    (f"Late {state} outcome ignored; no public reply accepted.", delivery_id),
                )
                return False
            delivery = self.get_delivery(delivery_id)
            self._db.execute(
                "UPDATE deliveries SET state=?,finished_at=?,error=?,native_session_ref=? "
                "WHERE id=?",
                (state, _now(), error, native_session_ref, delivery_id),
            )
            if native_session_ref:
                self._db.execute(
                    "UPDATE sessions SET native_session_ref=? WHERE conversation_id=?",
                    (native_session_ref, delivery.conversation_id),
                )
            if state == "completed" and text.strip():
                notice = None
                if len(text) > 32000:
                    text = (
                        text[:31920]
                        + "\n[Response truncated; inspect the native session for the full reply.]"
                    )
                    notice = "Public response exceeded the room message limit."
                task_context = self.task_context_for_delivery(delivery_id)
                self._insert_message(
                    self.get_lead(delivery.lead_id),
                    text,
                    [],
                    delivery.chain_id,
                    notice,
                    task_id=task_context["id"] if task_context else None,
                    source_delivery_id=delivery_id,
                )
            return True

    def _invalidate(self, lead_id: str, error: str):
        self._db.execute("UPDATE leads SET generation=generation+1 WHERE id=?", (lead_id,))
        self._db.execute(
            "UPDATE deliveries SET state='canceled',finished_at=?,error=? WHERE lead_id=? "
            "AND state='queued'",
            (_now(), f"{_stop_cause(error)}. Queued delivery canceled before execution.", lead_id),
        )
        self._db.execute(
            "UPDATE deliveries SET state='stopping',error=? WHERE lead_id=? AND state='running'",
            (error, lead_id),
        )

    def invalidate_delivery(self, delivery_id: str, error: str):
        with self._transaction():
            delivery = self.get_delivery(delivery_id)
            if delivery.state in {"running", "stopping"}:
                self._invalidate(delivery.lead_id, error)

    def pause(self) -> list[Delivery]:
        with self._transaction():
            self._db.execute("UPDATE room SET paused=1 WHERE id=1")
            active = [d for d in self.list_deliveries() if d.state in {"running", "stopping"}]
            for lead in self.list_leads():
                self._invalidate(lead.id, "Paused by the human; awaiting confirmed stop.")
            return active

    def confirm_stopped(self, delivery_id: str):
        with self._transaction():
            row = self._db.execute(
                "SELECT error FROM deliveries WHERE id=? AND state='stopping'", (delivery_id,)
            ).fetchone()
            if row is None:
                return
            cause = _stop_cause(row[0] or "Execution interrupted")
            self._db.execute(
                "UPDATE deliveries SET state='interrupted',finished_at=?,error=? WHERE id=? AND "
                "state='stopping'",
                (
                    _now(),
                    f"{cause}. Runtime stop confirmed; existing edits are preserved.",
                    delivery_id,
                ),
            )

    def resume(self):
        with self._transaction():
            self._db.execute("UPDATE room SET paused=0 WHERE id=1")

    def recover(self):
        with self._transaction():
            self._db.execute("UPDATE room SET paused=1 WHERE id=1")
            self._db.execute("UPDATE leads SET generation=generation+1")
            self._db.execute(
                f"UPDATE deliveries SET state='interrupted',finished_at=?,error=? WHERE "
                f"state IN {_ACTIVE}",
                (_now(), "Service restarted; previous execution outcome is uncertain."),
            )
            self._db.execute(
                "UPDATE deliveries SET state='canceled',finished_at=?,error=? WHERE state='queued'",
                (_now(), "Service restarted; queued work was not replayed."),
            )

    def record_diagnostic(self, delivery_id: str, message: str):
        with self._transaction():
            self._db.execute(
                "UPDATE deliveries SET diagnostic=? WHERE id=?", (message[:1000], delivery_id)
            )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "paused": self.paused,
                "leads": [asdict(x) for x in self.list_leads()],
                "messages": [asdict(x) for x in self.list_messages()],
                "deliveries": [asdict(x) for x in self.list_deliveries()],
            }
