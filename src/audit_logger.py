"""
Agentic Storefront — Audit Logger
Structured JSON audit trail for every action.
Every financial action MUST be logged through this module.

The audit trail is the compliance backbone — it makes every money action
explainable, traceable, and verifiable.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.models import AuditAction, AuditEntry


class AuditLogger:
    """Structured audit logger. Appends entries to JSONL file."""

    def __init__(self, output_path: str = "output/audit_trail.jsonl"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[AuditEntry] = []

    def log(
        self,
        action: AuditAction,
        actor: str = "system",
        details: dict | None = None,
        amount: int | None = None,
        status: str = "success",
        reason: str = "",
    ) -> AuditEntry:
        """Log an audit entry. Appends to in-memory list and JSONL file.

        Args:
            action: The type of action being logged (from AuditAction enum)
            actor: Who performed the action ("buyer_agent" or "system")
            details: Action-specific payload (cart_id, product_ids, etc.)
            amount: Financial amount in paise (if applicable)
            status: Outcome — "success", "failed", "gated", "rejected"
            reason: Human-readable explanation of WHY this action happened

        Returns:
            The created AuditEntry
        """
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            action=action,
            actor=actor,
            details=details or {},
            amount=amount,
            status=status,
            reason=reason,
        )

        self._entries.append(entry)
        self._append_to_file(entry)
        return entry

    def _append_to_file(self, entry: AuditEntry) -> None:
        """Append a single entry to the JSONL file."""
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def get_trail(
        self,
        filter_action: AuditAction | None = None,
        filter_status: str | None = None,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering."""
        entries = self._entries
        if filter_action:
            entries = [e for e in entries if e.action == filter_action]
        if filter_status:
            entries = [e for e in entries if e.status == filter_status]
        return entries

    def get_financial_summary(self) -> dict:
        """Compute aggregate financial metrics from the audit trail.

        Returns dict with:
            total_actions: total audit entries
            financial_actions: entries with amount > 0
            total_gmv: sum of ORDER_CREATED amounts
            total_discounts: sum of COUPON_APPLIED amounts
            total_captured: sum of PAYMENT_CAPTURED amounts
            total_failed: count of PAYMENT_FAILED entries
            success_rate: captured / (captured + failed)
        """
        financial = [e for e in self._entries if e.amount is not None and e.amount > 0]

        order_amounts = [
            e.amount for e in self._entries
            if e.action == AuditAction.ORDER_CREATED and e.amount
        ]
        discount_amounts = [
            e.amount for e in self._entries
            if e.action == AuditAction.COUPON_APPLIED and e.amount
        ]
        captured = [
            e for e in self._entries
            if e.action == AuditAction.PAYMENT_CAPTURED
        ]
        failed = [
            e for e in self._entries
            if e.action == AuditAction.PAYMENT_FAILED
        ]

        total_captured = len(captured)
        total_failed = len(failed)
        total_payments = total_captured + total_failed

        return {
            "total_actions": len(self._entries),
            "financial_actions": len(financial),
            "total_gmv_paise": sum(order_amounts),
            "total_gmv_display": f"Rs.{sum(order_amounts) / 100:,.2f}",
            "total_discounts_paise": sum(discount_amounts),
            "total_discounts_display": f"Rs.{sum(discount_amounts) / 100:,.2f}",
            "payments_captured": total_captured,
            "payments_failed": total_failed,
            "success_rate": (
                total_captured / total_payments if total_payments > 0 else 0.0
            ),
        }

    def export_json(self, output_path: str | None = None) -> str:
        """Export full audit trail as formatted JSON.

        Returns the output file path.
        """
        path = Path(output_path or "output/audit_trail.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [entry.model_dump(mode="json") for entry in self._entries]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        return str(path)

    def clear(self) -> None:
        """Clear in-memory entries and the output file."""
        self._entries.clear()
        if self.output_path.exists():
            self.output_path.unlink()

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    from rich.table import Table

    console = Console(force_terminal=True)

    console.print("\n[bold blue]Audit Logger — Self-Test[/bold blue]\n")

    # Create logger with temp path
    logger = AuditLogger(output_path="output/test_audit.jsonl")
    logger.clear()

    # Log various actions
    logger.log(
        AuditAction.CATALOG_SEARCH, actor="buyer_agent",
        details={"query": "dark roast coffee", "results": 5},
        reason="Buyer searched for dark roast coffee"
    )
    logger.log(
        AuditAction.CART_CREATED, actor="buyer_agent",
        details={"cart_id": "cart_test123", "items": 2},
        amount=70000, status="success",
        reason="Buyer created cart with Dark Roast x2"
    )
    logger.log(
        AuditAction.COUPON_APPLIED, actor="buyer_agent",
        details={"cart_id": "cart_test123", "coupon": "WELCOME10"},
        amount=7000, status="success",
        reason="10% discount applied (Rs.70 off)"
    )
    logger.log(
        AuditAction.BOUNDS_CHECK, actor="system",
        details={"cart_id": "cart_test123", "total": 63000, "max_allowed": 5000000},
        amount=63000, status="success",
        reason="Order amount Rs.630 within bounds (max Rs.50,000)"
    )
    logger.log(
        AuditAction.ORDER_CREATED, actor="system",
        details={"cart_id": "cart_test123", "order_id": "order_test456"},
        amount=63000, status="success",
        reason="Razorpay order created for cart_test123"
    )
    logger.log(
        AuditAction.COUPON_REJECTED, actor="system",
        details={"coupon": "EXPIRED01"},
        status="rejected",
        reason="Coupon EXPIRED01 is no longer active"
    )

    # Display entries
    table = Table(title=f"Audit Trail ({logger.entry_count} entries)")
    table.add_column("Time", style="dim")
    table.add_column("Action", style="cyan")
    table.add_column("Actor", style="green")
    table.add_column("Amount", style="yellow", justify="right")
    table.add_column("Status", style="bold")
    table.add_column("Reason")

    for entry in logger.get_trail():
        amt = f"Rs.{entry.amount / 100:.2f}" if entry.amount else "-"
        status_style = "green" if entry.status == "success" else "red"
        table.add_row(
            entry.timestamp.strftime("%H:%M:%S"),
            entry.action.value,
            entry.actor,
            amt,
            f"[{status_style}]{entry.status}[/{status_style}]",
            entry.reason[:50],
        )

    console.print(table)

    # Show financial summary
    summary = logger.get_financial_summary()
    console.print(f"\n[bold]Financial Summary:[/bold]")
    console.print(f"  Total Actions: {summary['total_actions']}")
    console.print(f"  Financial Actions: {summary['financial_actions']}")
    console.print(f"  Total GMV: {summary['total_gmv_display']}")
    console.print(f"  Total Discounts: {summary['total_discounts_display']}")

    # Export
    export_path = logger.export_json("output/test_audit_export.json")
    console.print(f"\n  Exported to: {export_path}")

    # Verify file was written
    lines = Path("output/test_audit.jsonl").read_text(encoding="utf-8").strip().split("\n")
    console.print(f"  JSONL entries on disk: {len(lines)}")

    # Cleanup
    logger.clear()
    Path("output/test_audit_export.json").unlink(missing_ok=True)

    console.print("\n[bold green]Audit Logger passed all tests![/bold green]\n")
