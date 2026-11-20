"""Persistent task metadata and explicit human decisions, using Store's transactions.

This mixin never controls a native runtime. Execution always uses the existing delivery
queue; task lifecycle and decision resolution are not execution/cancellation states.
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from department_studio.domain import Conflict, Invalid, NotFound, message_text

TASK_SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, parent_id TEXT REFERENCES tasks(id),
    root_id TEXT NOT NULL REFERENCES tasks(id), owner_lead_id TEXT NOT NULL REFERENCES leads(id),
    title TEXT NOT NULL, context TEXT NOT NULL,
    source_message_id TEXT NOT NULL REFERENCES messages(id),
    source_chain_id TEXT NOT NULL REFERENCES chains(id),
    lifecycle TEXT NOT NULL CHECK(lifecycle IN ('open','closed')),
    revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX task_parent ON tasks(parent_id);
CREATE TABLE task_deliveries (
    delivery_id TEXT PRIMARY KEY REFERENCES deliveries(id),
    task_id TEXT NOT NULL REFERENCES tasks(id), context_snapshot TEXT NOT NULL
);
CREATE INDEX task_delivery_owner ON task_deliveries(task_id);
CREATE TABLE task_messages (
    task_id TEXT NOT NULL REFERENCES tasks(id), message_id TEXT NOT NULL REFERENCES messages(id),
    source_delivery_id TEXT REFERENCES deliveries(id), PRIMARY KEY(task_id,message_id)
);
CREATE TABLE task_instructions (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    message_id TEXT UNIQUE NOT NULL REFERENCES messages(id),
    chain_id TEXT UNIQUE NOT NULL REFERENCES chains(id),
    delivery_id TEXT UNIQUE REFERENCES deliveries(id), context_snapshot TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('queued','recorded_no_dispatch')),
    reason TEXT, created_at TEXT NOT NULL
);
CREATE INDEX instruction_task ON task_instructions(task_id);
CREATE TABLE task_requests (
    kind TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
    receipt TEXT NOT NULL, PRIMARY KEY(kind,request_key)
);
CREATE TABLE action_requests (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    source_message_id TEXT REFERENCES messages(id), question TEXT NOT NULL, options TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','resolved')), revision INTEGER NOT NULL,
    created_at TEXT NOT NULL, resolved_at TEXT, resolution TEXT
);
CREATE INDEX unresolved_actions ON action_requests(status);
"""

STATES = ("queued", "running", "stopping", "completed", "failed", "interrupted", "canceled")
PUBLIC_DELIVERY_FIELDS = (
    "id",
    "chain_id",
    "message_id",
    "lead_id",
    "state",
    "created_at",
    "started_at",
    "finished_at",
    "error",
    "diagnostic",
)


class TaskConflict(Conflict):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def now():
    return datetime.now(UTC).isoformat()


def bounded_text(value, name, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise Invalid(f"{name} must contain {'0' if empty else '1'}–{maximum} characters.")
    return value.strip()


def positive_revision(value):
    if type(value) is not int or value < 1:
        raise Invalid("Revision must be a positive integer.")


def pagination(cursor, limit):
    if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise Invalid("Cursor must be nonnegative and limit must be between 1 and 200.")


class TaskStore:
    @contextmanager
    def _task_read(self):
        # One SQLite read snapshot, including across independent Store connections.
        with self._lock:
            owned = not self._db.in_transaction
            if owned:
                self._db.execute("BEGIN")
            try:
                yield
                if owned:
                    self._db.commit()
            except BaseException:
                if owned:
                    self._db.rollback()
                raise

    def _task_row(self, task_id):
        row = self._db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise NotFound("Task not found.")
        return dict(row)

    def _request_fingerprint(self, key, payload):
        bounded_text(key, "Idempotency key", 128)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _request_replay(self, kind, key, fingerprint):
        row = self._db.execute(
            "SELECT fingerprint,receipt FROM task_requests WHERE kind=? AND request_key=?",
            (kind, key),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise TaskConflict("idempotency_conflict", "Request key already has different content.")
        return json.loads(row["receipt"])

    def _remember_request(self, kind, key, fingerprint, receipt):
        self._db.execute(
            "INSERT INTO task_requests VALUES(?,?,?,?)",
            (kind, key, fingerprint, json.dumps(receipt)),
        )
        return receipt

    def _new_task(self, *, owner_lead_id, title, context, message_id, chain_id, parent=None):
        task_id, stamp = str(uuid4()), now()
        self._db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,'open',1,?,?)",
            (
                task_id,
                parent["id"] if parent else None,
                parent["root_id"] if parent else task_id,
                owner_lead_id,
                title,
                context,
                message_id,
                chain_id,
                stamp,
                stamp,
            ),
        )
        self._link_task_message(task_id, message_id)
        return task_id

    def _create_root_tasks(self, message_id, chain_id, recipients, text):
        # Called exactly once from ordinary human-message creation, in its writer transaction.
        return {
            lead_id: self._new_task(
                owner_lead_id=lead_id,
                title=" ".join(text.split())[:120],
                context=text[:8000],
                message_id=message_id,
                chain_id=chain_id,
            )
            for lead_id in recipients
        }

    def _link_task_message(self, task_id, message_id, source_delivery_id=None):
        if task_id is not None:
            self._db.execute(
                "INSERT INTO task_messages VALUES(?,?,?)", (task_id, message_id, source_delivery_id)
            )

    def _task_snapshot(self, task_id):
        task = self._task_row(task_id)
        return {
            key: task[key]
            for key in (
                "id",
                "parent_id",
                "root_id",
                "title",
                "context",
                "owner_lead_id",
                "revision",
                "source_message_id",
                "source_chain_id",
            )
        }

    def _link_task_delivery(self, task_id, delivery_id, snapshot=None):
        if task_id is not None:
            self._db.execute(
                "INSERT INTO task_deliveries VALUES(?,?,?)",
                (
                    delivery_id,
                    task_id,
                    json.dumps(snapshot or self._task_snapshot(task_id)),
                ),
            )

    def task_context_for_delivery(self, delivery_id):
        with self._task_read():
            row = self._db.execute(
                "SELECT context_snapshot FROM task_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def _public_delivery(self, delivery_id):
        delivery = self.get_delivery(delivery_id)
        context = self.task_context_for_delivery(delivery_id)
        return {key: getattr(delivery, key) for key in PUBLIC_DELIVERY_FIELDS} | {
            "task_id": context["id"] if context else None,
        }

    def get_task(self, task_id):
        with self._task_read():
            task = self._task_row(task_id)
            lead = self.get_lead(task["owner_lead_id"], include_deleted=True)
            task["owner"] = {
                key: getattr(lead, key)
                for key in (
                    "id",
                    "name",
                    "handle",
                    "enabled",
                    "deleted_at",
                    "revision",
                    "status",
                )
            }
            reason = None
            if task["lifecycle"] == "closed":
                mode, reason = "blocked", "task_closed"
            elif lead.deleted_at or not lead.enabled:
                mode, reason = "blocked", "owner_unavailable"
            elif self.paused:
                mode, reason = "record_note", "room_paused"
            elif lead.status == "stopping":
                mode, reason = "record_note", "owner_stopping"
            else:
                mode = "execute"
            task["instruction_action"] = {"mode": mode, "reason": reason}
            task["delivery_summary"] = dict.fromkeys(STATES, 0)
            rows = self._db.execute(
                "SELECT d.state,COUNT(*) AS n FROM task_deliveries t "
                "JOIN deliveries d ON d.id=t.delivery_id WHERE t.task_id=? GROUP BY d.state",
                (task_id,),
            )
            for row in rows:
                task["delivery_summary"][row["state"]] = row["n"]
            last = self._db.execute(
                "SELECT d.id FROM deliveries d JOIN task_deliveries t ON t.delivery_id=d.id "
                "WHERE t.task_id=? ORDER BY d.rowid DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            task["latest_delivery"] = self._public_delivery(last[0]) if last else None
            task["child_count"] = self._db.execute(
                "SELECT COUNT(*) FROM tasks WHERE parent_id=?", (task_id,)
            ).fetchone()[0]
            return task

    def list_tasks(self, *, cursor=0, limit=100):
        pagination(cursor, limit)
        with self._task_read():
            rows = self._db.execute(
                "SELECT rowid,id FROM tasks WHERE rowid>? ORDER BY rowid LIMIT ?",
                (cursor, limit + 1),
            ).fetchall()
            return {
                "tasks": [self.get_task(row["id"]) for row in rows[:limit]],
                "next_cursor": rows[limit - 1]["rowid"] if len(rows) > limit else None,
                "open_count": self._db.execute(
                    "SELECT COUNT(*) FROM tasks WHERE lifecycle='open'"
                ).fetchone()[0],
            }

    def task_detail(self, task_id, *, cursor=0, limit=50):
        pagination(cursor, limit)
        with self._task_read():
            task = self.get_task(task_id)
            rows = self._db.execute(
                "SELECT m.* FROM messages m JOIN task_messages t ON t.message_id=m.id "
                "WHERE t.task_id=? AND m.sequence>? ORDER BY m.sequence LIMIT ?",
                (task_id, cursor, limit + 1),
            ).fetchall()
            messages = [asdict(self._message(row)) for row in rows[:limit]]
            ids = [message["id"] for message in messages]
            deliveries, instructions = [], []
            if ids:
                slots = ",".join("?" for _ in ids)
                runs = self._db.execute(
                    "SELECT d.id FROM deliveries d JOIN task_deliveries t ON t.delivery_id=d.id "
                    f"WHERE t.task_id=? AND (d.message_id IN ({slots}) OR d.id IN "
                    f"(SELECT source_delivery_id FROM task_messages WHERE message_id IN ({slots}) "
                    "AND task_id=?)) ORDER BY d.rowid LIMIT 201",
                    (task_id, *ids, *ids, task_id),
                ).fetchall()
                deliveries = [self._public_delivery(row[0]) for row in runs]
                records = self._db.execute(
                    f"SELECT * FROM task_instructions WHERE task_id=? AND message_id IN ({slots}) "
                    "ORDER BY rowid",
                    (task_id, *ids),
                ).fetchall()
                for record in records:
                    entry = self._instruction_receipt(record)
                    entry["text"] = self.get_message(entry["message_id"]).text
                    entry["delivery_state"] = (
                        self.get_delivery(entry["delivery_id"]).state
                        if entry["delivery_id"]
                        else None
                    )
                    instructions.append(entry)
            actions = self._db.execute(
                "SELECT id FROM action_requests WHERE task_id=? ORDER BY rowid DESC LIMIT 201",
                (task_id,),
            ).fetchall()
            return {
                "task": task,
                "messages": messages,
                "deliveries": deliveries[:200],
                "deliveries_truncated": len(deliveries) > 200,
                "instructions": instructions,
                "action_requests": [self._action_request(row[0]) for row in actions[:200]],
                "action_requests_truncated": len(actions) > 200,
                "next_cursor": rows[limit - 1]["sequence"] if len(rows) > limit else None,
            }

    def _check_task(self, task_id, revision, *, available=True):
        positive_revision(revision)
        task = self._task_row(task_id)
        if task["revision"] != revision:
            raise TaskConflict("stale_task", "Task changed; reload and review before submitting.")
        if task["lifecycle"] != "open":
            raise TaskConflict("task_closed", "Reopen this task before adding work.")
        if available:
            lead = self.get_lead(task["owner_lead_id"], include_deleted=True)
            if lead.deleted_at or not lead.enabled:
                raise TaskConflict(
                    "owner_unavailable", "The responsible department is unavailable."
                )
        return task

    def create_task(
        self, *, parent_id, parent_revision, owner_lead_id, title, context="", idempotency_key
    ):
        title = bounded_text(title, "Title", 120)
        context = bounded_text(context, "Context", 8000, empty=True)
        payload = [parent_id, parent_revision, owner_lead_id, title, context]
        fingerprint = self._request_fingerprint(idempotency_key, payload)
        with self._transaction():
            replay = self._request_replay("child", idempotency_key, fingerprint)
            if replay is not None:
                return replay
            parent = self._check_task(parent_id, parent_revision, available=False)
            lead = self.get_lead(owner_lead_id, include_deleted=True)
            if lead.deleted_at or not lead.enabled:
                raise TaskConflict("owner_unavailable", "Choose an enabled, existing department.")
            task_id = self._new_task(
                owner_lead_id=owner_lead_id,
                title=title,
                context=context,
                message_id=parent["source_message_id"],
                chain_id=parent["source_chain_id"],
                parent=parent,
            )
            return self._remember_request(
                "child", idempotency_key, fingerprint, self.get_task(task_id)
            )

    def update_task(self, task_id, task_revision, changes):
        positive_revision(task_revision)
        if not changes or set(changes) - {"title", "context", "lifecycle"}:
            raise Invalid("Provide title, context or lifecycle only.")
        values = dict(changes)
        if "title" in values:
            values["title"] = bounded_text(values["title"], "Title", 120)
        if "context" in values:
            values["context"] = bounded_text(values["context"], "Context", 8000, empty=True)
        if "lifecycle" in values and values["lifecycle"] not in {"open", "closed"}:
            raise Invalid("Lifecycle must be open or closed.")
        with self._transaction():
            task = self._task_row(task_id)
            if task["revision"] != task_revision:
                raise TaskConflict("stale_task", "Task changed; reload before editing.")
            if (
                values.get("lifecycle") == "closed"
                and self._db.execute(
                    "SELECT 1 FROM task_deliveries t JOIN deliveries d ON d.id=t.delivery_id "
                    "WHERE t.task_id=? AND d.state IN ('queued','running','stopping') LIMIT 1",
                    (task_id,),
                ).fetchone()
            ):
                raise TaskConflict("task_busy", "Wait for linked work to finish before closing.")
            fields = ",".join(f"{key}=?" for key in values)  # Whitelisted above.
            self._db.execute(
                f"UPDATE tasks SET {fields},revision=revision+1,updated_at=? WHERE id=?",
                (*values.values(), now(), task_id),
            )
            return self.get_task(task_id)

    @staticmethod
    def _instruction_receipt(row):
        return {
            key: row[key]
            for key in (
                "id",
                "task_id",
                "message_id",
                "chain_id",
                "delivery_id",
                "disposition",
                "reason",
                "created_at",
            )
        }

    def _write_instruction(self, task_id, text, task_revision, mode):
        if mode not in {"execute", "record_note"}:
            raise Invalid("Mode must be execute or record_note.")
        task = self._check_task(task_id, task_revision)
        lead = self.get_lead(task["owner_lead_id"])
        reason = (
            "room_paused"
            if self.paused
            else ("owner_stopping" if lead.status == "stopping" else None)
        )
        if mode == "execute" and reason:
            raise TaskConflict(
                reason, "Execution unavailable; review and explicitly record a note."
            )
        snapshot = self._task_snapshot(task_id)
        chain_id, instruction_id, stamp = str(uuid4()), str(uuid4()), now()
        self._db.execute(
            "INSERT INTO chains(id,allowance) VALUES(?,?)", (chain_id, self.max_chain_deliveries)
        )
        notice = (
            None
            if mode == "execute"
            else ("Recorded task note only. No execution queued; Resume will not send this note.")
        )
        message_id = self._insert_message(None, text, [lead.id], chain_id, notice, task_id=task_id)
        self._db.execute("UPDATE chains SET root_message_id=? WHERE id=?", (message_id, chain_id))
        delivery_id = None
        if mode == "execute":
            self._enqueue(chain_id, message_id, [lead.id], task_ids={lead.id: task_id})
            delivery_id = self._db.execute(
                "SELECT id FROM deliveries WHERE message_id=?", (message_id,)
            ).fetchone()[0]
        disposition = "queued" if delivery_id else "recorded_no_dispatch"
        self._db.execute(
            "INSERT INTO task_instructions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                instruction_id,
                task_id,
                message_id,
                chain_id,
                delivery_id,
                json.dumps(snapshot),
                disposition,
                None if delivery_id else (reason or "human_note"),
                stamp,
            ),
        )
        row = self._db.execute(
            "SELECT * FROM task_instructions WHERE id=?", (instruction_id,)
        ).fetchone()
        return self._instruction_receipt(row)

    def post_task_instruction(self, task_id, *, text, task_revision, idempotency_key, mode):
        text = message_text(text)
        fingerprint = self._request_fingerprint(
            idempotency_key, [task_id, text, task_revision, mode]
        )
        with self._transaction():
            replay = self._request_replay("instruction", idempotency_key, fingerprint)
            if replay is not None:
                return replay
            receipt = self._write_instruction(task_id, text, task_revision, mode)
            return self._remember_request("instruction", idempotency_key, fingerprint, receipt)

    def _action_request(self, request_id):
        row = self._db.execute("SELECT * FROM action_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise NotFound("Action request not found.")
        result = dict(row)
        result["options"] = json.loads(result["options"])
        result["resolution"] = json.loads(result["resolution"]) if result["resolution"] else None
        result["task"] = self.get_task(result["task_id"])
        return result

    def list_action_requests(self, *, cursor=0, limit=100):
        pagination(cursor, limit)
        with self._task_read():
            rows = self._db.execute(
                "SELECT a.rowid,a.id FROM action_requests a JOIN tasks t ON t.id=a.task_id "
                "JOIN leads l ON l.id=t.owner_lead_id "
                "WHERE a.status='open' AND a.rowid>? AND t.lifecycle='open' "
                "AND l.deleted_at IS NULL AND json_extract(l.settings,'$.enabled')=1 "
                "ORDER BY a.rowid LIMIT ?",
                (cursor, limit + 1),
            ).fetchall()
            return {
                "action_requests": [self._action_request(row["id"]) for row in rows[:limit]],
                "next_cursor": rows[limit - 1]["rowid"] if len(rows) > limit else None,
            }

    def create_action_request(
        self, task_id, *, question, options, task_revision, idempotency_key, source_message_id=None
    ):
        question = bounded_text(question, "Question", 2000)
        if not isinstance(options, list) or not 2 <= len(options) <= 8:
            raise Invalid("Provide two to eight single-choice options.")
        normalized = []
        for option in options:
            if not isinstance(option, dict) or set(option) != {"id", "label"}:
                raise Invalid("Each option requires id and label only.")
            normalized.append(
                {
                    "id": bounded_text(option["id"], "Option ID", 64),
                    "label": bounded_text(option["label"], "Option label", 300),
                }
            )
        if len({option["id"] for option in normalized}) != len(normalized):
            raise Invalid("Option IDs must be distinct.")
        fingerprint = self._request_fingerprint(
            idempotency_key, [task_id, question, normalized, task_revision, source_message_id]
        )
        with self._transaction():
            replay = self._request_replay("action", idempotency_key, fingerprint)
            if replay is not None:
                return replay
            self._check_task(task_id, task_revision)
            if (
                source_message_id
                and not self._db.execute(
                    "SELECT 1 FROM task_messages WHERE task_id=? AND message_id=?",
                    (task_id, source_message_id),
                ).fetchone()
            ):
                raise Invalid("Source message must belong to this task.")
            request_id = str(uuid4())
            self._db.execute(
                "INSERT INTO action_requests VALUES(?,?,?,?,?,'open',1,?,NULL,NULL)",
                (request_id, task_id, source_message_id, question, json.dumps(normalized), now()),
            )
            return self._remember_request(
                "action", idempotency_key, fingerprint, self._action_request(request_id)
            )

    def resolve_action_request(
        self, request_id, *, option_id, revision, task_revision, idempotency_key, mode
    ):
        positive_revision(revision)
        fingerprint = self._request_fingerprint(
            idempotency_key, [request_id, option_id, revision, task_revision, mode]
        )
        with self._transaction():
            replay = self._request_replay("resolution", idempotency_key, fingerprint)
            if replay is not None:
                return replay
            request = self._action_request(request_id)
            if request["status"] != "open" or request["revision"] != revision:
                raise TaskConflict("stale_action", "Decision already resolved or changed; reload.")
            selected = next((o for o in request["options"] if o["id"] == option_id), None)
            if selected is None:
                raise Invalid("Choose exactly one listed option.")
            text = f"Decision: {request['question']}\nSelected: {selected['label']}"
            receipt = self._write_instruction(request["task_id"], text, task_revision, mode)
            result = {
                "action_request_id": request_id,
                "status": "resolved",
                "option_id": option_id,
                "revision": revision + 1,
                "instruction": receipt,
            }
            self._db.execute(
                "UPDATE action_requests SET status='resolved',revision=revision+1,"
                "resolved_at=?,resolution=? WHERE id=?",
                (now(), json.dumps(result), request_id),
            )
            return self._remember_request("resolution", idempotency_key, fingerprint, result)
