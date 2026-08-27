"""
audit_log.py
------------
Answers the buildathon's judging bar directly:
"Every money action explainable, bounded and gated. Show the audit trail."

Implementation notes:
- SQLite, single file, zero external dependencies.
- Append-only tables with triggers.
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
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    proposed_price REAL,
    rationale TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_events (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    check_type TEXT NOT NULL,
    sku TEXT NOT NULL,
    checked_price REAL NOT NULL,
    allowed INTEGER NOT NULL,
    reason TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_events (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    sku TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS app_events (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    details TEXT,
    amount REAL,
    reason TEXT,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payment_link TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

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

CREATE TRIGGER IF NOT EXISTS no_update_app
BEFORE UPDATE ON app_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS no_delete_app
BEFORE DELETE ON app_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

class AuditLog:
    def __init__(self, db_path: str = "audit_log.sqlite3"):
        self.db_path = db_path
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.executescript(IMMUTABILITY_TRIGGERS)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
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

    def log(self, action: str, actor: str, details: dict = None, amount: float = None, reason: str = None):
        """Unified with the old JSONL AuditLogger."""
        with self._conn() as conn:
            # handle ENUMs like AuditAction.xxx by converting to str
            action_str = str(action.value) if hasattr(action, 'value') else str(action)
            conn.execute(
                "INSERT INTO app_events VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), action_str, actor, json.dumps(details) if details else None, amount, reason, time.time())
            )

    def claim_idempotency_key(self, key: str, ttl_seconds: int = 60) -> dict:
        """
        Two-phase idempotency claim. Status state machine:
        
          PENDING -> COMPLETED | FAILED | NEEDS_RECONCILIATION (on TTL expiry)
          NEEDS_RECONCILIATION -> RECONCILED_COMPLETED | RECONCILED_FAILED (ops resolution)
        
        Reclaimable states (buyer can retry same cart):
          FAILED              - guardrail blocked the deal, normal business outcome
          RECONCILED_FAILED   - ops confirmed the payment truly failed
        
        Non-reclaimable states:
          PENDING             - another request is in-flight
          COMPLETED           - payment link already created, return it
          RECONCILED_COMPLETED - ops confirmed the payment succeeded
          NEEDS_RECONCILIATION - stuck, waiting for ops
        """
        now = time.time()
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status, payment_link, expires_at FROM idempotency_keys WHERE id=?", (key,)).fetchone()
            if row:
                status, link, expires_at = row
                
                # Expired PENDING -> flag for ops reconciliation (idempotent: only writes once)
                if status == 'PENDING' and now > expires_at:
                    conn.execute("UPDATE idempotency_keys SET status='NEEDS_RECONCILIATION' WHERE id=?", (key,))
                    conn.commit()
                    return {'success': False, 'status': 'NEEDS_RECONCILIATION', 'payment_link': None, 'reason': 'Expired pending claim flagged for reconciliation'}
                
                # FAILED or RECONCILED_FAILED: safe to reclaim — delete old row, fall through to fresh insert
                if status in ('FAILED', 'RECONCILED_FAILED'):
                    conn.execute("DELETE FROM idempotency_keys WHERE id=?", (key,))
                    # Fall through to fresh insert below
                else:
                    # PENDING (non-expired), COMPLETED, RECONCILED_COMPLETED, NEEDS_RECONCILIATION
                    conn.rollback()
                    return {'success': False, 'status': status, 'payment_link': link, 'reason': 'Key already exists'}
            
            conn.execute("INSERT INTO idempotency_keys (id, status, payment_link, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                         (key, 'PENDING', None, now, now + ttl_seconds))
            conn.commit()
            return {'success': True, 'status': 'PENDING', 'payment_link': None, 'reason': 'Claimed'}
        except sqlite3.IntegrityError:
            conn.rollback()
            # Concurrent claim won the race — re-read and return current state
            row = conn.execute("SELECT status, payment_link FROM idempotency_keys WHERE id=?", (key,)).fetchone()
            if row:
                return {'success': False, 'status': row[0], 'payment_link': row[1], 'reason': 'Lost race to concurrent claim'}
            return {'success': False, 'status': 'PENDING', 'payment_link': None, 'reason': 'Lost race to concurrent claim'}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            
    def commit_idempotency_key(self, key: str, payment_link: str = None, failed: bool = False):
        with self._conn() as conn:
            status = 'FAILED' if failed else 'COMPLETED'
            conn.execute("UPDATE idempotency_keys SET status=?, payment_link=? WHERE id=?", (status, payment_link, key))
            
    def resolve_idempotency_key(self, key: str, payment_link: str = None, failed: bool = False):
        with self._conn() as conn:
            status = 'RECONCILED_FAILED' if failed else 'RECONCILED_COMPLETED'
            conn.execute("UPDATE idempotency_keys SET status=?, payment_link=? WHERE id=?", (status, payment_link, key))

    def full_trace(self, negotiation_id: str) -> dict:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            turns = [dict(r) for r in conn.execute(
                "SELECT * FROM negotiation_turns WHERE negotiation_id=? ORDER BY round_number", (negotiation_id,))]
            guardrails = [dict(r) for r in conn.execute(
                "SELECT * FROM guardrail_events WHERE negotiation_id=? ORDER BY ts", (negotiation_id,))]
            payments = [dict(r) for r in conn.execute(
                "SELECT * FROM payment_events WHERE negotiation_id=? ORDER BY ts", (negotiation_id,))]
        return {"negotiation_id": negotiation_id, "turns": turns,
                "guardrail_events": guardrails, "payment_events": payments}

    def get_dashboard_metrics(self) -> dict:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT COUNT(DISTINCT negotiation_id) as total_deals, SUM(amount) as gmv FROM payment_events WHERE status = 'created'").fetchone()
            total_deals = row['total_deals'] or 0
            gmv = row['gmv'] or 0.0
            row = conn.execute("SELECT COUNT(*) as blocked FROM guardrail_events WHERE allowed = 0 AND check_type = 'hard'").fetchone()
            blocked_injections = row['blocked'] or 0
            row = conn.execute("SELECT COUNT(DISTINCT negotiation_id) as total_negs FROM negotiation_turns").fetchone()
            total_negs = row['total_negs'] or 0
            row = conn.execute("SELECT AVG(max_round) as avg_rounds FROM (SELECT MAX(round_number) as max_round FROM negotiation_turns GROUP BY negotiation_id)").fetchone()
            avg_rounds = round(row['avg_rounds'] or 0, 1)
            walk_aways = conn.execute("SELECT COUNT(DISTINCT negotiation_id) as walk_aways FROM negotiation_turns WHERE action = 'walk_away'").fetchone()['walk_aways'] or 0
            return {
                "total_deals": total_deals, "gmv": gmv, "blocked_injections": blocked_injections,
                "total_negotiations": total_negs, "win_rate_pct": round((total_deals / total_negs * 100) if total_negs > 0 else 0, 1),
                "avg_rounds": avg_rounds, "walk_aways": walk_aways
            }
