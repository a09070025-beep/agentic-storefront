with open('src/guardrail_factory.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('get_guardrail_stack(db_path: str = "output/guardrail_audit.sqlite3")', 'get_guardrail_stack(db_path: str = "data/pg_audit.sqlite3")')

with open('src/guardrail_factory.py', 'w', encoding='utf-8') as f:
    f.write(c)
