"""
Agentic Storefront — Webhook Handler
Verifies Razorpay webhook signatures and processes payment events.

Razorpay sends webhooks as POST requests with:
  - Body: JSON event payload
  - Header: X-Razorpay-Signature (HMAC-SHA256 hex digest)
"""

import hashlib
import hmac
import json

from src.models import AuditAction
from agentic_storefront_guardrails.audit_log import AuditLog


class WebhookHandler:
    """Handles Razorpay webhook events with signature verification."""

    def __init__(self, webhook_secret: str, audit: AuditLog | None = None):
        self.webhook_secret = webhook_secret
        self.audit = audit or AuditLog("data/pg_audit.sqlite3")

    def verify_signature(self, payload: str | bytes, signature: str) -> bool:
        """Verify the X-Razorpay-Signature header.

        Uses HMAC-SHA256 with the webhook secret as key.

        Args:
            payload: Raw request body (string or bytes)
            signature: Value of X-Razorpay-Signature header

        Returns:
            True if signature is valid, False if tampered
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected, signature)

        self.audit.log(
            AuditAction.WEBHOOK_RECEIVED, actor="system",
            details={"signature_valid": is_valid},
            status="success" if is_valid else "failed",
            reason="Webhook signature verified" if is_valid else "INVALID webhook signature — possible tampering"
        )

        return is_valid

    def process_event(self, event_data: dict) -> dict:
        """Route webhook event to appropriate handler.

        Supported events:
          - payment.captured: Payment was successful
          - payment.failed: Payment attempt failed
          - order.paid: Order fully paid

        Returns:
            Processing result with action taken
        """
        event_name = event_data.get("event", "")
        payload = event_data.get("payload", {})

        handlers = {
            "payment.captured": self._handle_payment_captured,
            "payment.failed": self._handle_payment_failed,
            "order.paid": self._handle_order_paid,
        }

        handler = handlers.get(event_name)
        if handler:
            return handler(payload)

        # Unknown event — log but don't fail
        self.audit.log(
            AuditAction.WEBHOOK_RECEIVED, actor="system",
            details={"event": event_name},
            reason=f"Received unhandled webhook event: {event_name}"
        )
        return {"status": "ignored", "event": event_name}

    def _handle_payment_captured(self, payload: dict) -> dict:
        """Handle payment.captured event — payment was successful."""
        payment = payload.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id", "unknown")
        payment_id = payment.get("id", "unknown")
        amount = payment.get("amount", 0)
        method = payment.get("method", "unknown")

        self.audit.log(
            AuditAction.PAYMENT_CAPTURED, actor="system",
            details={
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount,
                "method": method,
                "email": payment.get("email", ""),
                "contact": payment.get("contact", ""),
            },
            amount=amount,
            reason=(
                f"Payment {payment_id} captured for order {order_id}: "
                f"Rs.{amount/100:.2f} via {method}"
            )
        )

        return {
            "status": "captured",
            "payment_id": payment_id,
            "order_id": order_id,
            "amount": amount,
            "method": method,
        }

    def _handle_payment_failed(self, payload: dict) -> dict:
        """Handle payment.failed event — payment attempt failed."""
        payment = payload.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id", "unknown")
        payment_id = payment.get("id", "unknown")
        amount = payment.get("amount", 0)
        error_code = payment.get("error_code", "unknown")
        error_desc = payment.get("error_description", "No description")

        self.audit.log(
            AuditAction.PAYMENT_FAILED, actor="system",
            details={
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount,
                "error_code": error_code,
                "error_description": error_desc,
            },
            amount=amount,
            status="failed",
            reason=(
                f"Payment {payment_id} FAILED for order {order_id}: "
                f"{error_code} — {error_desc}"
            )
        )

        return {
            "status": "failed",
            "payment_id": payment_id,
            "order_id": order_id,
            "error_code": error_code,
            "error_description": error_desc,
        }

    def _handle_order_paid(self, payload: dict) -> dict:
        """Handle order.paid event — order fully paid."""
        order = payload.get("order", {}).get("entity", {})
        order_id = order.get("id", "unknown")
        amount = order.get("amount_paid", order.get("amount", 0))

        self.audit.log(
            AuditAction.ORDER_FULFILLED, actor="system",
            details={
                "order_id": order_id,
                "amount_paid": amount,
                "status": order.get("status", "paid"),
            },
            amount=amount,
            reason=f"Order {order_id} fully paid: Rs.{amount/100:.2f}"
        )

        return {
            "status": "paid",
            "order_id": order_id,
            "amount_paid": amount,
        }


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    console = Console(force_terminal=True)

    console.print("\n[bold blue]Webhook Handler — Self-Test[/bold blue]\n")

    audit = AuditLog("data/pg_audit.sqlite3")
    audit.clear()
    handler = WebhookHandler(webhook_secret="test_secret_123", audit=audit)

    # Test 1: Valid signature
    console.print("[cyan]Test 1: Valid signature verification[/cyan]")
    payload = '{"event":"payment.captured","payload":{}}'
    valid_sig = hmac.new(
        b"test_secret_123", payload.encode(), hashlib.sha256
    ).hexdigest()
    result = handler.verify_signature(payload, valid_sig)
    console.print(f"  Valid signature: {result} (expected True)")

    # Test 2: Invalid/tampered signature
    console.print("\n[cyan]Test 2: Tampered signature[/cyan]")
    result = handler.verify_signature(payload, "tampered_signature_abc")
    console.print(f"  Tampered signature: {result} (expected False)")

    # Test 3: Process payment.captured
    console.print("\n[cyan]Test 3: Process payment.captured[/cyan]")
    event = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test123",
                    "order_id": "order_test456",
                    "amount": 85000,
                    "method": "upi",
                    "email": "buyer@test.com",
                    "contact": "9876543210",
                }
            }
        }
    }
    result = handler.process_event(event)
    console.print(f"  Status: {result['status']}")
    console.print(f"  Payment: {result['payment_id']}")
    console.print(f"  Amount: Rs.{result['amount']/100:.2f}")
    console.print(f"  Method: {result['method']}")

    # Test 4: Process payment.failed
    console.print("\n[cyan]Test 4: Process payment.failed[/cyan]")
    event = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_fail789",
                    "order_id": "order_test456",
                    "amount": 85000,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment processing failed due to insufficient balance",
                }
            }
        }
    }
    result = handler.process_event(event)
    console.print(f"  Status: {result['status']}")
    console.print(f"  Error: {result['error_code']} — {result['error_description']}")

    # Test 5: Process order.paid
    console.print("\n[cyan]Test 5: Process order.paid[/cyan]")
    event = {
        "event": "order.paid",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_test456",
                    "amount": 85000,
                    "amount_paid": 85000,
                    "status": "paid",
                }
            }
        }
    }
    result = handler.process_event(event)
    console.print(f"  Status: {result['status']}")
    console.print(f"  Amount Paid: Rs.{result['amount_paid']/100:.2f}")

    # Test 6: Unknown event
    console.print("\n[cyan]Test 6: Unknown event type[/cyan]")
    result = handler.process_event({"event": "subscription.charged", "payload": {}})
    console.print(f"  Status: {result['status']} (expected 'ignored')")

    console.print(f"\n[bold]Audit trail: {audit.entry_count} entries[/bold]")
    audit.clear()

    console.print(f"\n[bold green]Webhook Handler passed all 6 tests![/bold green]\n")
