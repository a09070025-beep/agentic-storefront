import re

with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

# find the sys.exit(0) and the block at the end, and swap them.
# The easiest way is just to insert the rollback test before sys.exit(0)

test_code = '''
def _rollback_test():
    from src.guardrail_factory import get_guardrail_stack
    from agentic_storefront_guardrails.schemas import CheckoutItem
    stack = get_guardrail_stack()
    res1 = stack.inventory.reserve("prod_001", "test-rollback", quantity=1)
    items = [
        CheckoutItem(sku="prod_001", agreed_price=20000.0, quantity=1, reservation_id=res1),
        CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1) 
    ]
    result = stack.payment_gate.finalize_deal("test-rollback", items, "idem-rollback-001")
    assert result.success == False, f"Expected rollback, got {result}"
    try:
        stack.inventory.confirm(res1)
        assert False, "res1 was not released!"
    except RuntimeError:
        pass 
    print("  [PASS] PaymentGate rolls back all reservations if one item fails guardrail")
    
run_test("rollback_test", _rollback_test)
'''

c = c.replace('if len(errors) > 0:', test_code + '\nif len(errors) > 0:')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
