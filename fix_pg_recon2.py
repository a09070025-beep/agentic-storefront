import re

with open('agentic_storefront_guardrails/payment_gate.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = r'class PaymentGateResult:\n    success: bool\n    payment_link: Optional\[str\]\n    reason: str'
replacement = r'''class PaymentGateResult:
    success: bool
    payment_link: Optional[str]
    reason: str
    needs_reconciliation: bool = False'''
c = re.sub(pattern, replacement, c)

with open('agentic_storefront_guardrails/payment_gate.py', 'w', encoding='utf-8') as f:
    f.write(c)
