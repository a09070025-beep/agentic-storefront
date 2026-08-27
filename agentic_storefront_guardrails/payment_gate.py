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

from .guardrails import PriceGuard
from .inventory_lock import InventoryManager
from .audit_log import AuditLog
from .schemas import CheckoutItem


class PaymentBlockedError(Exception):
    """Raised when a deal is blocked by a guardrail — this is a SUCCESS
    case for security, not a bug. Always caught and logged, never a
    silent crash."""


@dataclass
class PaymentGateResult:
    success: bool
    payment_link: Optional[str]
    reason: str
    needs_reconciliation: bool = False





class PaymentGate:
    def __init__(self, price_guard: PriceGuard, inventory: InventoryManager,
                 audit: AuditLog,
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
        
        self._create_link = razorpay_create_link_fn

    def finalize_deal(self, negotiation_id: str, items: list[CheckoutItem],
                      idempotency_key: str, max_retries: int = 2,
                      customer_details: dict | None = None) -> PaymentGateResult:

        # 1. Idempotency — 2-phase claim
        claim_result = self.audit.claim_idempotency_key(idempotency_key)
        if not claim_result['success']:
            if claim_result['status'] == 'NEEDS_RECONCILIATION':
                return PaymentGateResult(False, None, claim_result['reason'], needs_reconciliation=True)
            elif claim_result['status'] == 'COMPLETED' or claim_result['status'] == 'RECONCILED_COMPLETED':
                self.audit.log_payment(negotiation_id, idempotency_key, "CART",
                                       sum(i.agreed_price * i.quantity for i in items),
                                       "created", "returned existing idempotent link")
                return PaymentGateResult(True, claim_result['payment_link'], "idempotent replay")
            elif claim_result['status'] == 'RECONCILED_FAILED' or claim_result['status'] == 'FAILED':
                return PaymentGateResult(False, None, "Previous payment session failed. Please modify cart to generate a new checkout session.")
            else:
                return PaymentGateResult(False, None, "Checkout in progress for this cart. Please wait.")

        # 2. Authoritative price re-check & 3. Inventory lock/refresh
        total_amount = 0.0
        active_reservations = []
        
        # Pre-collect any incoming reservations so we guarantee they are released on failure
        for item in items:
            if item.reservation_id:
                active_reservations.append(item.reservation_id)
                
        try:
            for item in items:
                # Price check
                check = self.price_guard.authoritative_check(item.sku, item.agreed_price)
                self.audit.log_guardrail(negotiation_id, "hard", item.sku, item.agreed_price,
                                         check.allowed, check.reason)
                if not check.allowed:
                    raise PaymentBlockedError(f"Blocked by price guard on {item.sku}: {check.reason}")
                
                total_amount += item.agreed_price * item.quantity
                
                # Inventory: extend existing TTL, or reserve fresh
                if item.reservation_id:
                    if not self.inventory.extend_ttl(item.reservation_id, 300):
                        raise RuntimeError(f"Reservation {item.reservation_id} for {item.sku} expired mid-checkout.")
                else:
                    new_res_id = self.inventory.reserve(item.sku, negotiation_id, quantity=item.quantity)
                    active_reservations.append(new_res_id)
        
        except (PaymentBlockedError, RuntimeError) as e:
            self.audit.commit_idempotency_key(idempotency_key, failed=True)
            # Rollback ALL reservations (incoming + newly created)
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "blocked", str(e))
            return PaymentGateResult(False, None, str(e))

        # 4. Call Razorpay with retry + graceful degradation
        link = None
        last_error = ""
        for attempt in range(1, max_retries + 2):
            try:
                link = self._create_link(items, total_amount, customer_details)
                break  # Success, exit retry loop
            except Exception as e:
                last_error = str(e)

        if not link:
            self.audit.commit_idempotency_key(idempotency_key, failed=True)
            # Exhausted retries, release reservations explicitly
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "failed", f"Razorpay API failed: {last_error}")
            return PaymentGateResult(False, None, f"Payment API failed: {last_error}")

        self.audit.commit_idempotency_key(idempotency_key, link)
        
        # 5. Confirm ALL
        needs_reconciliation = False
        for res_id in active_reservations:
            confirm_success = False
            for confirm_attempt in range(3):
                try:
                    self.inventory.confirm(res_id)
                    confirm_success = True
                    break
                except RuntimeError as e:
                    if "not found" in str(e).lower():
                        break # Permanent failure, don't retry
                    time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)
            
            if not confirm_success:
                needs_reconciliation = True
                self.audit.log_payment(negotiation_id, idempotency_key, "CART", total_amount, "fatal", f"Failed to confirm stock for reservation {res_id}")
                
        if needs_reconciliation:
            return PaymentGateResult(True, link, "WARNING: Payment created but some stock confirmations failed.", needs_reconciliation=True)

        self.audit.log_payment(negotiation_id, idempotency_key, "CART",
                               total_amount, "created",
                               f"deal verified, {len(items)} items locked and paid")
        return PaymentGateResult(True, link, "Payment link created")

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
        items=[CheckoutItem(sku="SKU123", agreed_price=0.0, quantity=1)],
        idempotency_key="demo-injection-001-key",
    )
    print("Injection attempt result:", result)
    return result


# ---------------------------------------------------------------------
# Demo scenario 2: Razorpay gateway failure handled gracefully
# ---------------------------------------------------------------------
def flaky_razorpay_call(items: list[CheckoutItem], amount: float, customer: dict | None = None) -> str:
    """Fails the first two calls, then succeeds — simulates a transient
    gateway/network issue for the 'one failure handled gracefully' demo."""
    if not hasattr(flaky_razorpay_call, "_calls"):
        flaky_razorpay_call._calls = 0
    flaky_razorpay_call._calls += 1
    if flaky_razorpay_call._calls < 3:
        raise ConnectionError("Simulated Razorpay gateway timeout")
    return f"https://rzp.io/l/demo-{items[0].sku}-{int(amount)}"
