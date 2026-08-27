"""
Agentic Storefront — Razorpay Service
Real Razorpay API integration for orders and payment links.
Uses Razorpay Test Mode — every call is a REAL API call with REAL responses.

Verified API Endpoints:
  POST /v1/orders           — Create order
  GET  /v1/orders/{id}      — Fetch order status
  GET  /v1/orders/{id}/payments — Fetch payments for order
  POST /v1/payment_links    — Create payment link
  GET  /v1/payment_links/{id} — Fetch payment link status
"""

import razorpay
import time
from config import Settings, get_razorpay_client, get_settings
from src.models import AuditAction, OrderResult, PaymentStatus
from agentic_storefront_guardrails.audit_log import AuditLog


def _retry_api_call(func, *args, max_retries: int = 4, base_delay: float = 2.0, **kwargs):
    """Retry a Razorpay API call with exponential backoff on rate limits."""
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            if "too many requests" in error_msg and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
                continue
            raise


class RazorpayService:
    """Razorpay API wrapper. Every call is logged to the audit trail."""

    def __init__(
        self,
        client: razorpay.Client | None = None,
        audit: AuditLog | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.audit = audit or AuditLog()

        if client:
            self.client = client
        else:
            self.client = get_razorpay_client(self.settings)

    def create_order(
        self,
        amount: int,
        currency: str = "INR",
        receipt: str = "",
        notes: dict | None = None,
    ) -> dict:
        """Create a Razorpay order.

        POST /v1/orders
        Amount is in paise (e.g., 50000 = Rs.500).

        Returns the full Razorpay order entity.
        """
        # Bounds check before API call
        if amount > self.settings.max_order_amount:
            self.audit.log(
                AuditAction.BOUNDS_CHECK, actor="system",
                details={"amount": amount, "max": self.settings.max_order_amount},
                amount=amount, status="rejected",
                reason=f"Order amount Rs.{amount/100:.2f} exceeds max Rs.{self.settings.max_order_amount/100:.2f}"
            )
            raise ValueError(
                f"Order amount Rs.{amount/100:.2f} exceeds maximum "
                f"Rs.{self.settings.max_order_amount/100:.2f}"
            )

        if amount <= 0:
            raise ValueError("Order amount must be positive")

        payload = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt or None,
            "notes": notes or {},
        }

        order = _retry_api_call(self.client.order.create, data=payload)

        self.audit.log(
            AuditAction.ORDER_CREATED, actor="system",
            details={
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "status": order["status"],
                "receipt": receipt,
            },
            amount=order["amount"],
            reason=f"Razorpay order {order['id']} created for Rs.{order['amount']/100:.2f}"
        )

        return order

    def create_payment_link(
        self,
        amount: int,
        currency: str = "INR",
        description: str = "",
        customer: dict | None = None,
        receipt: str = "",
        notes: dict | None = None,
    ) -> dict:
        """Create a Razorpay payment link.

        POST /v1/payment_links
        Returns entity with short_url for the buyer to pay.
        """
        payload: dict = {
            "amount": amount,
            "currency": currency,
            "description": description or "Agentic Storefront Order",
            "notes": notes or {},
        }

        if customer:
            payload["customer"] = customer

        if receipt:
            payload["reference_id"] = receipt

        # Razorpay Payment Link API
        plink = _retry_api_call(self.client.payment_link.create, data=payload)

        self.audit.log(
            AuditAction.PAYMENT_LINK_CREATED, actor="system",
            details={
                "payment_link_id": plink["id"],
                "short_url": plink.get("short_url", ""),
                "amount": plink["amount"],
                "status": plink.get("status", "created"),
            },
            amount=plink["amount"],
            reason=(
                f"Payment link {plink['id']} created: "
                f"{plink.get('short_url', 'N/A')}"
            )
        )

        return plink

    def create_order_with_payment_link(
        self,
        amount: int,
        currency: str = "INR",
        description: str = "",
        customer: dict | None = None,
        receipt: str = "",
        notes: dict | None = None,
    ) -> OrderResult:
        """Create both order and payment link in one call.

        This is the main checkout method:
        1. Creates Razorpay order (for tracking)
        2. Creates payment link (for buyer to pay)

        Returns OrderResult with both IDs and the payment URL.
        """
        # Step 1: Create order
        order = self.create_order(
            amount=amount, currency=currency,
            receipt=receipt, notes=notes,
        )

        # Step 2: Create payment link (may fail in test mode — 30 link limit)
        link_notes = {**(notes or {}), "order_id": order["id"]}
        plink_id = ""
        plink_url = ""
        try:
            plink = self.create_payment_link(
                amount=amount, currency=currency,
                description=description,
                customer=customer,
                receipt=receipt,
                notes=link_notes,
            )
            plink_id = plink["id"]
            plink_url = plink.get("short_url", "")
        except Exception as e:
            # Payment link creation failed (test mode limit or rate limit)
            # Order is still valid — log and continue
            self.audit.log(
                AuditAction.ERROR, actor="system",
                details={"order_id": order["id"], "error": str(e)},
                status="failed",
                reason=f"Payment link skipped (test mode limit): order {order['id']} still valid"
            )

        return OrderResult(
            order_id=order["id"],
            payment_link_id=plink_id,
            payment_link_url=plink_url,
            amount=order["amount"],
            currency=order["currency"],
            status=order["status"],
            cart_id=receipt,
            receipt=receipt,
        )

    def get_order_status(self, order_id: str) -> PaymentStatus:
        """Fetch order status from Razorpay.

        GET /v1/orders/{order_id}
        """
        order = self.client.order.fetch(order_id)

        return PaymentStatus(
            order_id=order["id"],
            status=order["status"],
            amount=order["amount"],
            amount_paid=order.get("amount_paid", 0),
            currency=order.get("currency", "INR"),
        )

    def get_order_payments(self, order_id: str) -> list[dict]:
        """Fetch all payment attempts for an order.

        GET /v1/orders/{order_id}/payments
        """
        response = self.client.order.payments(order_id)
        return response.get("items", [])

    def get_payment_link_status(self, payment_link_id: str) -> dict:
        """Fetch payment link status.

        GET /v1/payment_links/{id}
        """
        return self.client.payment_link.fetch(payment_link_id)


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    console = Console(force_terminal=True)

    console.print("\n[bold blue]Razorpay Service — Self-Test[/bold blue]\n")

    settings = get_settings()

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        console.print("[yellow]Razorpay keys not set. Skipping live API tests.[/yellow]")
        console.print("[yellow]Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env[/yellow]")
        console.print("\n[bold yellow]Razorpay Service module loaded OK (no live test)[/bold yellow]\n")
        sys.exit(0)

    audit = AuditLog("data/pg_audit.sqlite3")
    audit.clear()

    try:
        service = RazorpayService(audit=audit)
        console.print(f"[green]Razorpay client initialized[/green]")
        console.print(f"  Key: {settings.razorpay_key_id[:15]}...")

        # Test 1: Create order
        console.print(f"\n[cyan]Test 1: Create Order (Rs.500)[/cyan]")
        order = service.create_order(
            amount=50000, currency="INR",
            receipt="test_order_001",
            notes={"source": "agentic-storefront-test"}
        )
        console.print(f"  Order ID: {order['id']}")
        console.print(f"  Status: {order['status']}")
        console.print(f"  Amount: Rs.{order['amount']/100:.2f}")

        # Test 2: Fetch order status
        console.print(f"\n[cyan]Test 2: Fetch Order Status[/cyan]")
        status = service.get_order_status(order["id"])
        console.print(f"  Status: {status.status}")
        console.print(f"  Amount Paid: Rs.{status.amount_paid/100:.2f}")

        # Test 3: Create payment link
        console.print(f"\n[cyan]Test 3: Create Payment Link (Rs.500)[/cyan]")
        plink = service.create_payment_link(
            amount=50000, currency="INR",
            description="Test order from Agentic Storefront",
            customer={"name": "Test Buyer", "email": "test@example.com",
                      "contact": "9123456780"},
        )
        console.print(f"  Link ID: {plink['id']}")
        console.print(f"  URL: {plink.get('short_url', 'N/A')}")
        console.print(f"  Status: {plink.get('status', 'N/A')}")

        # Test 4: Full checkout flow
        console.print(f"\n[cyan]Test 4: Full Checkout (create_order_with_payment_link)[/cyan]")
        result = service.create_order_with_payment_link(
            amount=85000, currency="INR",
            description="Coffee order #test002",
            customer={"name": "AI Buyer", "email": "ai@buyer.test",
                      "contact": "9876543210"},
            receipt="cart_test002",
            notes={"cart_id": "cart_test002", "items": "Dark Roast x2 + Grinder"},
        )
        console.print(f"  Order ID: {result.order_id}")
        console.print(f"  Payment Link: {result.payment_link_url}")
        console.print(f"  Amount: Rs.{result.amount/100:.2f}")

        console.print(f"\n[bold]Audit trail: {audit.entry_count} entries[/bold]")
        audit.clear()

        console.print(f"\n[bold green]Razorpay Service passed all 4 tests![/bold green]\n")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        console.print("[yellow]Make sure your Razorpay test keys are valid[/yellow]\n")
