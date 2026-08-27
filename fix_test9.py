with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

import re

# Strip everything from print("\n" + "="*60) to the end of the file.
c = re.sub(r'print\("\\n" \+ "="\*60\).*$', '', c, flags=re.DOTALL)

end_code = '''
def _rollback_test():
    try:
        from src.guardrail_factory import get_guardrail_stack
        from agentic_storefront_guardrails.schemas import CheckoutItem
        stack = get_guardrail_stack()
        res1 = stack.inventory.reserve("prod_001", "test-rollback", quantity=1)
        items = [
            CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1),
            CheckoutItem(sku="prod_001", agreed_price=20000.0, quantity=1, reservation_id=res1)
        ]
        result = stack.payment_gate.finalize_deal("test-rollback", items, "idem-rollback-001")
        assert result.success == False, f"Expected rollback, got {result}"
        try:
            stack.inventory.confirm(res1)
            assert False, "res1 was not released!"
        except RuntimeError:
            pass 
        passes.append("PaymentGate rolls back all reservations if one item fails guardrail")
    except Exception as e:
        errors.append(("rollback_test", str(e)))

_rollback_test()

print("\\n" + "="*60)
print(f"RESULTS: {len(passes)} passed, {len(errors)} failed")
print("="*60)

if errors:
    print("\\n[FAIL] FAILURES:")
    for name, msg in errors:
        print(f"  - {name}: {msg}")
    sys.exit(1)
else:
    print("\\n[PASS] ALL TESTS PASSED")
    sys.exit(0)
'''

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c + end_code)
