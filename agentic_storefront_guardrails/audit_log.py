"""
audit_log.py
------------
Answers the buildathon's judging bar directly:
"Every money action explainable, bounded and gated. Show the audit trail."

Implementation notes:
- SQLite, single file, zero external dependencies — easy to demo and to
  attach to your pitch (query it live, show a blocked injection attempt).
- Append-only: INSERT-only tables, plus triggers that reject UPDATE/DELETE
  so the log can't be quietly edited after the fact, even by your own code.
- Three event types map directly to the three things judges want to see:
  negotiation turns, guardrail decisions, and payment/tool actions.
"""

import sqlite3
import json
import time
import uuid
from contextlib import contextmanager
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS negotiation_turns (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    actor TEXT NOT NULL,              -- 'buyer' | 'merchant_ai' | 'system'
    action TEXT NOT NULL,
    proposed_price REAL,
    rationale TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_events (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    check_type TEXT NOT NULL,         -- 'soft' | 'hard'
    sku TEXT NOT NULL,
    checked_price REAL NOT NULL,
    allowed INTEGER NOT NULL,         -- 0/1
    reason TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_events (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    sku TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,             -- 'created' | 'blocked' | 'failed' | 'retried'
    detail TEXT,
    ts REAL NOT NULL
);
"""

# Triggers that make every table effectively append-only.
IMMUTABILITY_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS no_update_turns
BEFORE UPDATE ON negotiation_turns
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_delete_turns
BEFORE DELETE ON negotiation_turns
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_update_guardrail
BEFORE UPDATE ON guardrail_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_delete_guardrail
BEFORE DELETE ON guardrail_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_update_payment
BEFORE UPDATE ON payment_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_delete_payment
BEFORE DELETE ON payment_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


class AuditLog:
    def __init__(self, db_path: str = "audit_log.sqlite3"):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.executescript(IMMUTABILITY_TRIGGERS)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def log_turn(self, negotiation_id: str, round_number: int, actor: str,
                 action: str, proposed_price: Optional[float] = None,
                 rationale: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO negotiation_turns VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), negotiation_id, round_number, actor,
                 action, proposed_price, rationale, time.time()),
            )

    def log_guardrail(self, negotiation_id: str, check_type: str, sku: str,
                       checked_price: float, allowed: bool, reason: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO guardrail_events VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), negotiation_id, check_type, sku,
                 checked_price, int(allowed), reason, time.time()),
            )

    def log_payment(self, negotiation_id: str, idempotency_key: str, sku: str,
                     amount: float, status: str, detail: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO payment_events VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), negotiation_id, idempotency_key, sku,
                 amount, status, detail, time.time()),
            )

    def full_trace(self, negotiation_id: str) -> dict:
        """Pull everything for one negotiation — this is what you show
        judges when they ask 'why did the AI do that?'"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            turns = [dict(r) for r in conn.execute(
                "SELECT * FROM negotiation_turns WHERE negotiation_id=? "
                "ORDER BY round_number", (negotiation_id,))]
            guardrails = [dict(r) for r in conn.execute(
                "SELECT * FROM guardrail_events WHERE negotiation_id=? "
                "ORDER BY ts", (negotiation_id,))]
            payments = [dict(r) for r in conn.execute(
                "SELECT * FROM payment_events WHERE negotiation_id=? "
                "ORDER BY ts", (negotiation_id,))]
        return {"negotiation_id": negotiation_id, "turns": turns,
                "guardrail_events": guardrails, "payment_events": payments}
