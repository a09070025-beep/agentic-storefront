"""
e2e_demo_verify.py -- End-to-end verification of all demo flows against current codebase.

Runs 4 scenarios and asserts the exact properties that matter for a demo:
  1. Single-item normal deal
  2. Injection attack blocked
  3. Gateway retry succeeds
  4. Multi-item cart with reservation + guardrail failure + rollback
"""
import sys
import os
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from agentic_storefront_guardrails.guardrails import ProductCatalog, ProductRules, PriceGuard
from agentic_storefront_guardrails.inventory_lock import InventoryManager
from agentic_storefront_guardrails.audit_log import AuditLog
from agentic_storefront_guardrails.payment_gate import PaymentGate
from agentic_storefront_guardrails.schemas import CheckoutItem


def build_fresh_stack(db_path, razorpay_fn=None):
    catalog = ProductCatalog()
    catalog.upsert(ProductRules(sku="DEMO-A", list_price=10000.0, cost_floor=7000.0, max_discount_pct=0.40))
    catalog.upsert(ProductRules(sku="DEMO-B", list_price=5000.0, cost_floor=3500.0, max_discount_pct=0.40))
    
    pg = PriceGuard(catalog)
    inv = InventoryManager()
    inv.set_stock("DEMO-A", 5)
    inv.set_stock("DEMO-B", 5)
    audit = AuditLog(db_path=db_path)
    
    gate = PaymentGate(
        price_guard=pg, inventory=inv, audit=audit,
        razorpay_create_link_fn=razorpay_fn or (lambda items, amt, cust=None: f"https://rzp.io/l/e2e-{int(amt)}")
    )
    return pg, inv, audit, gate


passed = 0
failed = 0

def scenario(name):
    def decorator(fn):
        global passed, failed
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
    return decorator


print("\n" + "="*60)
print("END-TO-END DEMO VERIFICATION")
print("="*60)

# Fresh DB for each run
db = os.path.join(tempfile.gettempdir(), "e2e_verify.sqlite3")
if os.path.exists(db):
    os.remove(db)


@scenario("1. Single-item normal deal -- price passes, inventory reserved, link created")
def test_normal():
    pg, inv, audit, gate = build_fresh_stack(db)
    items = [CheckoutItem(sku="DEMO-A", agreed_price=8500.0, quantity=1)]
    result = gate.finalize_deal("e2e-normal", items, "e2e-normal-key")
    assert result.success == True, f"Expected success: {result}"
    assert result.payment_link is not None, f"Expected link: {result}"
    assert result.needs_reconciliation == False
    # Verify inventory was consumed
    assert inv.available("DEMO-A") == 4, f"Expected 4 available, got {inv.available('DEMO-A')}"
    # Verify audit trail exists
    trace = audit.full_trace("e2e-normal")
    assert len(trace['guardrail_events']) == 1
    assert trace['guardrail_events'][0]['allowed'] == 1
    assert len(trace['payment_events']) == 1
    assert trace['payment_events'][0]['status'] == 'created'


@scenario("2. Injection blocked -- price=0 rejected, no link, no inventory consumed")
def test_injection():
    pg, inv, audit, gate = build_fresh_stack(db)
    before_stock = inv.available("DEMO-A")
    items = [CheckoutItem(sku="DEMO-A", agreed_price=0.0, quantity=1)]
    result = gate.finalize_deal("e2e-inject", items, "e2e-inject-key")
    assert result.success == False, f"Expected failure: {result}"
    assert result.payment_link is None
    assert "Blocked" in result.reason or "positive" in result.reason.lower(), f"Expected guardrail message: {result.reason}"
    # Stock untouched
    assert inv.available("DEMO-A") == before_stock


@scenario("3. Gateway retry -- first 2 calls fail, 3rd succeeds, link created")
def test_retry():
    state = {"calls": 0}
    def flaky(items, amount, customer=None):
        state["calls"] += 1
        if state["calls"] < 3:
            raise ConnectionError("Simulated timeout")
        return f"https://rzp.io/l/retry-{int(amount)}"
    
    pg, inv, audit, gate = build_fresh_stack(db, razorpay_fn=flaky)
    items = [CheckoutItem(sku="DEMO-A", agreed_price=8500.0, quantity=1)]
    result = gate.finalize_deal("e2e-retry", items, "e2e-retry-key")
    assert result.success == True, f"Expected success after retry: {result}"
    assert "retry" in result.payment_link


@scenario("4. Multi-item cart -- item 1 OK, item 2 fails guard, both reservations rolled back")
def test_multi_item_rollback():
    pg, inv, audit, gate = build_fresh_stack(db)
    
    # Reserve item A upfront (simulates negotiation flow)
    res_a = inv.reserve("DEMO-A", "e2e-multi", quantity=1)
    before_a = inv.available("DEMO-A")  # Should be 4 after reserve
    before_b = inv.available("DEMO-B")  # Should be 5, untouched
    
    items = [
        # Item with below-floor price -- will fail guardrail
        CheckoutItem(sku="DEMO-B", agreed_price=1.0, quantity=1),
        # Item with valid price and pre-existing reservation
        CheckoutItem(sku="DEMO-A", agreed_price=8500.0, quantity=1, reservation_id=res_a),
    ]
    result = gate.finalize_deal("e2e-multi", items, "e2e-multi-key")
    assert result.success == False, f"Expected failure from guardrail: {result}"
    
    # CRITICAL: res_a must have been released (rollback)
    # Trying to confirm it should fail because it was released
    try:
        inv.confirm(res_a)
        assert False, "res_a should have been released by rollback!"
    except RuntimeError:
        pass  # Expected -- reservation was released
    
    # Stock should be fully restored
    assert inv.available("DEMO-A") == before_a + 1, f"DEMO-A stock not restored: {inv.available('DEMO-A')}"
    assert inv.available("DEMO-B") == before_b, f"DEMO-B stock should be untouched: {inv.available('DEMO-B')}"


@scenario("5. Idempotent replay -- same key on completed deal returns same link, no double-charge")
def test_idempotent_replay():
    pg, inv, audit, gate = build_fresh_stack(db)
    items = [CheckoutItem(sku="DEMO-B", agreed_price=4000.0, quantity=1)]
    
    r1 = gate.finalize_deal("e2e-idem", items, "e2e-idem-key")
    assert r1.success == True
    stock_after_first = inv.available("DEMO-B")
    
    r2 = gate.finalize_deal("e2e-idem", items, "e2e-idem-key")
    assert r2.success == True
    assert r2.payment_link == r1.payment_link, f"Replay should return same link: {r1.payment_link} vs {r2.payment_link}"
    assert r2.reason == "idempotent replay"
    # Stock should NOT have decreased again
    assert inv.available("DEMO-B") == stock_after_first, f"Double-charge! Stock went from {stock_after_first} to {inv.available('DEMO-B')}"


print("\n" + "="*60)
print(f"E2E RESULTS: {passed} passed, {failed} failed")
print("="*60)

if os.path.exists(db):
    os.remove(db)

if failed:
    sys.exit(1)
else:
    print("\n[PASS] ALL E2E SCENARIOS VERIFIED")
    sys.exit(0)
