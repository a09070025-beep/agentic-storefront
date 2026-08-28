#!/usr/bin/env python3
"""
ops_resolve.py — CLI tool for resolving stuck NEEDS_RECONCILIATION idempotency keys.

Usage:
    python ops_resolve.py list                              # Show all flagged keys
    python ops_resolve.py resolve <key> --completed <link>  # Mark as paid, store link
    python ops_resolve.py resolve <key> --failed            # Mark as genuinely failed
    
This is the only write path for NEEDS_RECONCILIATION -> RECONCILED_COMPLETED/RECONCILED_FAILED.
Once resolved, the buyer's next checkout attempt on the same cart will either:
  - Get the payment link back (RECONCILED_COMPLETED), or
  - Reclaim the key and start fresh (RECONCILED_FAILED)
"""

import sys
import sqlite3
import argparse
import time

DB_PATH = "data/pg_audit.sqlite3"


def list_flagged(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Already-flagged NEEDS_RECONCILIATION rows
    recon_rows = conn.execute(
        "SELECT id, status, payment_link, created_at, expires_at "
        "FROM idempotency_keys WHERE status = 'NEEDS_RECONCILIATION' "
        "ORDER BY created_at"
    ).fetchall()
    
    # 2. Orphaned PENDING rows past their TTL (no retry ever triggered the lazy check)
    now = time.time()
    orphaned_rows = conn.execute(
        "SELECT id, status, payment_link, created_at, expires_at "
        "FROM idempotency_keys WHERE status = 'PENDING' AND expires_at < ? "
        "ORDER BY created_at", (now,)
    ).fetchall()
    
    conn.close()

    if not recon_rows and not orphaned_rows:
        print("No flagged or orphaned keys found.")
        return

    if recon_rows:
        print(f"\n--- NEEDS_RECONCILIATION ({len(recon_rows)}) ---")
        print(f"{'Key':<40} {'Created':<26} {'Expired':<26}")
        print("-" * 92)
        for r in recon_rows:
            created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r['created_at']))
            expired = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r['expires_at']))
            print(f"{r['id']:<40} {created:<26} {expired:<26}")

    if orphaned_rows:
        print(f"\n--- ORPHANED PENDING (expired, never retried) ({len(orphaned_rows)}) ---")
        print(f"{'Key':<40} {'Created':<26} {'Expired':<26}")
        print("-" * 92)
        for r in orphaned_rows:
            created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r['created_at']))
            expired = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r['expires_at']))
            print(f"{r['id']:<40} {created:<26} {expired:<26}")
        print("  (Use 'resolve' on these keys -- they will be auto-transitioned to NEEDS_RECONCILIATION first)")

    total = len(recon_rows) + len(orphaned_rows)
    print(f"\n{total} key(s) requiring attention.")


def resolve_key(db_path: str, key: str, completed: bool, payment_link: str = None):
    from agentic_storefront_guardrails.audit_log import AuditLog
    audit = AuditLog(db_path=db_path)

    # Verify the key is actually NEEDS_RECONCILIATION
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status FROM idempotency_keys WHERE id=?", (key,)).fetchone()
    conn.close()

    if not row:
        print(f"ERROR: Key '{key}' not found.")
        sys.exit(1)
    
    current_status = row[0]
    if current_status == 'PENDING':
        # Check if it's expired — if so, auto-transition to NEEDS_RECONCILIATION
        conn2 = sqlite3.connect(db_path)
        row2 = conn2.execute("SELECT expires_at FROM idempotency_keys WHERE id=?", (key,)).fetchone()
        conn2.close()
        if row2 and time.time() > row2[0]:
            print(f"NOTE: Key '{key}' is orphaned PENDING (expired). Auto-transitioning to NEEDS_RECONCILIATION.")
            conn3 = sqlite3.connect(db_path)
            conn3.execute("UPDATE idempotency_keys SET status='NEEDS_RECONCILIATION' WHERE id=?", (key,))
            conn3.commit()
            conn3.close()
            current_status = 'NEEDS_RECONCILIATION'
        else:
            print(f"ERROR: Key '{key}' is PENDING and not yet expired. Cannot resolve an in-flight request.")
            sys.exit(1)
    elif current_status != 'NEEDS_RECONCILIATION':
        print(f"ERROR: Key '{key}' is in status '{current_status}', not NEEDS_RECONCILIATION. Cannot resolve.")
        sys.exit(1)

    if completed:
        if not payment_link:
            print("ERROR: --completed requires a payment link URL.")
            sys.exit(1)
        audit.resolve_idempotency_key(key, payment_link=payment_link, failed=False)
        print(f"RESOLVED: {key} -> RECONCILED_COMPLETED (link: {payment_link})")
    else:
        audit.resolve_idempotency_key(key, failed=True)
        print(f"RESOLVED: {key} -> RECONCILED_FAILED (buyer can retry)")


def main():
    parser = argparse.ArgumentParser(description="Resolve stuck NEEDS_RECONCILIATION idempotency keys")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all flagged keys")

    resolve_p = sub.add_parser("resolve", help="Resolve a specific key")
    resolve_p.add_argument("key", help="The idempotency key to resolve")
    group = resolve_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--completed", metavar="LINK", help="Mark as completed with this payment link")
    group.add_argument("--failed", action="store_true", help="Mark as genuinely failed")

    args = parser.parse_args()

    if args.command == "list":
        list_flagged(args.db)
    elif args.command == "resolve":
        resolve_key(args.db, args.key,
                    completed=bool(args.completed),
                    payment_link=args.completed)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
