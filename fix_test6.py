with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()
import re
# Remove ALL _rollback_test definitions and calls
c = re.sub(r'def _rollback_test\(\):[\s\S]*?(?=\n\n(?:if errors:|def|print))', '', c)
c = c.replace('_rollback_test()\n', '')

# add it correctly
test_code = '''
@run_test("PaymentGate rolls back all reservations if one item fails guardrail")
def test_paymentgate_rollback():
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
'''

c = c.replace('# -- 5. AuditLog ------------------------------------', test_code + '\n# -- 5. AuditLog ------------------------------------')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
