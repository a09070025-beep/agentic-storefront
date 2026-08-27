with open('src/cart_manager.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from src.audit_logger import AuditLogger', 'from agentic_storefront_guardrails.audit_log import AuditLog')
c = c.replace('audit: AuditLogger,', 'audit: AuditLog,')
c = c.replace('audit = AuditLogger(output_path="output/test_cart_audit.jsonl")', 'audit = AuditLog("data/pg_audit.sqlite3")')

with open('src/cart_manager.py', 'w', encoding='utf-8') as f:
    f.write(c)
