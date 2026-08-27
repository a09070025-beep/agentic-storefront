with open('src/guardrail_factory.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from agentic_storefront_guardrails import (\n    ProductCatalog, ProductRules, PriceGuard,\n    InventoryManager, AuditLog, PaymentGate, IdempotencyStore,\n)', 'from agentic_storefront_guardrails import (\n    ProductCatalog, ProductRules, PriceGuard,\n    InventoryManager, AuditLog, PaymentGate,\n)')
c = c.replace('    idempotency: IdempotencyStore\n', '')
c = c.replace('    idempotency = IdempotencyStore()\n', '')
c = c.replace('        idempotency=idempotency,\n', '')

with open('src/guardrail_factory.py', 'w', encoding='utf-8') as f:
    f.write(c)
