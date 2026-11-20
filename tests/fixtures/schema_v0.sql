-- Frozen bootstrap schema, used only to generate temporary migration fixtures.

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
