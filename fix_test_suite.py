import re

with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

# I need to properly add it to the suite logic.
# The test runner currently just collects passes/errors lists.

c = c.replace('passes.append("rollback_test")', 'passes.append("PaymentGate rolls back all reservations if one item fails guardrail")')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
