with open('agentic_storefront_guardrails/payment_gate.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Remove IdempotencyStore class entirely
import re
c = re.sub(r'class IdempotencyStore:.*?def put.*?self._seen\[key\] = payment_link', '', c, flags=re.DOTALL)

# Update PaymentGate signature
c = c.replace('def __init__(self, price_guard: PriceGuard, inventory: InventoryManager,\n                 audit: AuditLog, idempotency: IdempotencyStore,\n                 razorpay_create_link_fn: Callable[[str, float], str]):', 'def __init__(self, price_guard: PriceGuard, inventory: InventoryManager,\n                 audit: AuditLog,\n                 razorpay_create_link_fn: Callable[[str, float], str]):')
c = c.replace('self.idempotency = idempotency', '')

# Update idempotency logic
old_idem = '''        # 1. Idempotency \u2014 never double-charge on retry
        existing = self.idempotency.get(idempotency_key)
        if existing:
            self.audit.log_payment(negotiation_id, idempotency_key, "CART",
                                   sum(i.agreed_price * i.quantity for i in items), 
                                   "created", "returned existing idempotent link")
            return PaymentGateResult(True, existing, "idempotent replay")'''

new_idem = '''        # 1. Idempotency \u2014 2-phase claim
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
                return PaymentGateResult(False, None, "Checkout in progress for this cart. Please wait.")'''

c = c.replace(old_idem, new_idem)

# Update Razorpay call failure handling
old_rzp_fail = '''        if not link:
            # Exhausted retries, release reservations explicitly
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "failed", f"Razorpay API failed: {last_error}")
            return PaymentGateResult(False, None, f"Payment API failed: {last_error}")'''

new_rzp_fail = '''        if not link:
            self.audit.commit_idempotency_key(idempotency_key, failed=True)
            # Exhausted retries, release reservations explicitly
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "failed", f"Razorpay API failed: {last_error}")
            return PaymentGateResult(False, None, f"Payment API failed: {last_error}")'''

c = c.replace(old_rzp_fail, new_rzp_fail)

# Update guardrail failure handling
old_guard_fail = '''        except (PaymentBlockedError, RuntimeError) as e:
            # Rollback ALL reservations (incoming + newly created)
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "blocked", str(e))
            return PaymentGateResult(False, None, str(e))'''

new_guard_fail = '''        except (PaymentBlockedError, RuntimeError) as e:
            self.audit.commit_idempotency_key(idempotency_key, failed=True)
            # Rollback ALL reservations (incoming + newly created)
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "blocked", str(e))
            return PaymentGateResult(False, None, str(e))'''

c = c.replace(old_guard_fail, new_guard_fail)

# Update success commit
old_commit = 'self.idempotency.put(idempotency_key, link)'
new_commit = 'self.audit.commit_idempotency_key(idempotency_key, link)'
c = c.replace(old_commit, new_commit)

with open('agentic_storefront_guardrails/payment_gate.py', 'w', encoding='utf-8') as f:
    f.write(c)
