import re

with open('src/schemas.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('CHECKED_OUT = "checked_out"', 'CHECKED_OUT = "checked_out"\n    CHECKED_OUT_NEEDS_RECONCILIATION = "checked_out_needs_reconciliation"')

with open('src/schemas.py', 'w', encoding='utf-8') as f:
    f.write(c)
