from src.guardrail_factory import get_guardrail_stack
from agentic_storefront_guardrails.schemas import CheckoutItem
stack = get_guardrail_stack()
res1 = stack.inventory.reserve("prod_001", "test-rollback", quantity=1)
items = [
    CheckoutItem(sku="prod_001", agreed_price=20000.0, quantity=1, reservation_id=res1),
    CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1) 
]
print("Before finalize, res1 in reservations?", res1 in stack.inventory._reservations)
result = stack.payment_gate.finalize_deal("test-rollback", items, "idem-rollback-001")
print("Result:", result)
print("After finalize, res1 in reservations?", res1 in stack.inventory._reservations)
