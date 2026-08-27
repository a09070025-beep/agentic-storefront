with open('src/storefront_server.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from src.audit_logger import AuditLogger', '')
c = c.replace('audit = AuditLogger(output_path=settings.audit_output_path)', 'from agentic_storefront_guardrails.audit_log import AuditLog\naudit = AuditLog("data/pg_audit.sqlite3")')
c = c.replace('from agentic_storefront_guardrails.audit_log import AuditLog', '', 1) # Remove the second one
c = c.replace('pg_audit = AuditLog("data/pg_audit.sqlite3")', 'pg_audit = audit')
c = c.replace('IdempotencyStore', '')
c = c.replace('idempotency=IdempotencyStore(),', '')

with open('src/storefront_server.py', 'w', encoding='utf-8') as f:
    f.write(c)
