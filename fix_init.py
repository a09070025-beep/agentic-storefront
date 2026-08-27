with open('agentic_storefront_guardrails/__init__.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(', IdempotencyStore', '')

with open('agentic_storefront_guardrails/__init__.py', 'w', encoding='utf-8') as f:
    f.write(c)
