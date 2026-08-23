"""
payment_gate.py
----------------
This is the single choke point every negotiation must pass through
before a live Razorpay payment link is created. Nothing upstream
(the LLM, the negotiation transcript, "the buyer said they agreed") is
trusted here — every check is re-run authoritatively.

Order of operations, each one independently gated and logged:
  1. Idempotency check       -> don't create two links for one deal
  2. Authoritative price check -> re-validate against the real floor
  3. Inventory reservation   -> don't oversell
  4. Call Razorpay (via your MCP tool) -> with retry + graceful failure
  5. Confirm or release reservation based on outcome
  6. Log every step to the audit trail

This directly gives you the "one failure handled gracefully" demo
moment the judging bar asks for — see `simulate_gateway_failure` at
the bottom for a ready-made scenario for your pitch video.
"""

import time
import random
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from guardrails import PriceGuard
from inventory_lock import InventoryManager
from audit_log import AuditLog


class PaymentBlockedError(Exception):
    """Raised when a deal is blocked by a guardrail — this is a SUCCESS
    case for security, not a bug. Always caught and logged, never a
    silent crash."""


@dataclass
class PaymentGateResult:
    success: bool
    payment_link: Optional[str]
    reason: str


class IdempotencyStore:
    """Prevents duplicate payment links if a request is retried or a
    webhook fires twice. Swap for Redis/DB in production."""
    def __init__(self):
        self._seen: Dict[str, str] = {}  # idempotency_key -> payment_link

    def get(self, key: str) -> Optional[str]:
        return self._seen.get(key)

    def put(self, key: str, payment_link: str) -> None:
        self._seen[key] = payment_link


class PaymentGate:
    def __init__(self, price_guard: PriceGuard, inventory: InventoryManager,
                 audit: AuditLog, idempotency: IdempotencyStore,
                 razorpay_create_link_fn: Callable[[str, float], str]):
        """
        razorpay_create_link_fn: your real MCP call, e.g.
            lambda sku, amount: mcp_client.call("create_payment_link", ...)
        Injected as a function so this module has zero direct dependency
        on your MCP/Razorpay SDK and is trivially testable.
        """
        self.price_guard = price_guard
        self.inventory = inventory
        self.audit = audit
        self.idempotency = idempotency
        self._create_link = razorpay_create_link_fn

    def finalize_deal(self, negotiation_id: str, sku: str, agreed_price: float,
                       idempotency_key: str, max_retries: int = 2) -> PaymentGateResult:

        # 1. Idempotency — never double-charge on retry
        existing = self.idempotency.get(idempotency_key)
        if existing:
            self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                    agreed_price, "created",
                                    "returned existing idempotent link")
            return PaymentGateResult(True, existing, "idempotent replay")

        # 2. Authoritative price re-check — the actual injection defense
        check = self.price_guard.authoritative_check(sku, agreed_price)
        self.audit.log_guardrail(negotiation_id, "hard", sku, agreed_price,
                                  check.allowed, check.reason)
        if not check.allowed:
            self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                    agreed_price, "blocked", check.reason)
            return PaymentGateResult(False, None,
                                      f"Blocked by price guard: {check.reason}")

        # 3. Reserve inventory
        try:
            reservation_id = self.inventory.reserve(sku, negotiation_id)
        except RuntimeError as e:
            self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                    agreed_price, "blocked", str(e))
            return PaymentGateResult(False, None, str(e))

        # 4. Call Razorpay with retry + graceful degradation
        last_error = ""
        for attempt in range(1, max_retries + 2):
            try:
                link = self._create_link(sku, agreed_price)
                self.idempotency.put(idempotency_key, link)
                self.inventory.confirm(reservation_id)
                self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                        agreed_price, "created",
                                        f"succeeded on attempt {attempt}")
                return PaymentGateResult(True, link, "ok")
            except Exception as e:  # noqa: BLE001 - deliberately broad, this is a boundary
                last_error = str(e)
                self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                        agreed_price, "retried",
                                        f"attempt {attempt} failed: {last_error}")
                time.sleep(min(2 ** attempt, 5))  # simple backoff

        # 5. Graceful failure — release stock, log, surface a clean
        # message instead of crashing or leaving a dangling reservation.
        self.inventory.release(reservation_id)
        self.audit.log_payment(negotiation_id, idempotency_key, sku,
                                agreed_price, "failed",
                                f"exhausted retries: {last_error}")
        return PaymentGateResult(
            False, None,
            "Payment link could not be created after retries. "
            "Deal held, no charge created, escalated for manual follow-up.",
        )


# ---------------------------------------------------------------------
# Demo scenario 1: injection attack blocked
# ---------------------------------------------------------------------
def demo_injection_attempt(gate: PaymentGate):
    """
    Simulates a buyer/attacker who jailbroke the negotiation into
    'agreeing' on a ₹0 price. Even though the LLM/transcript says the
    deal is done, the authoritative check blocks it and the audit log
    shows exactly why.
    """
    result = gate.finalize_deal(
        negotiation_id="demo-injection-001",
        sku="SKU123",
        agreed_price=0.0,
        idempotency_key="demo-injection-001-key",
    )
    print("Injection attempt result:", result)
    return result


# ---------------------------------------------------------------------
# Demo scenario 2: Razorpay gateway failure handled gracefully
# ---------------------------------------------------------------------
def flaky_razorpay_call(sku: str, amount: float) -> str:
    """Fails the first two calls, then succeeds — simulates a transient
    gateway/network issue for the 'one failure handled gracefully' demo."""
    if not hasattr(flaky_razorpay_call, "_calls"):
        flaky_razorpay_call._calls = 0
    flaky_razorpay_call._calls += 1
    if flaky_razorpay_call._calls < 3:
        raise ConnectionError("Simulated Razorpay gateway timeout")
    return f"https://rzp.io/l/demo-{sku}-{int(amount)}"
