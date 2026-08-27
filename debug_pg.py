from src.guardrail_factory import get_guardrail_stack
stack = get_guardrail_stack()
try:
    res = stack.price_guard.authoritative_check("prod_100", 700000.0)
    print(res)
except Exception as e:
    print(e)
