with open('whatsapp_server.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from src.audit_logger import AuditLogger', 'from agentic_storefront_guardrails.audit_log import AuditLog')
c = c.replace('audit = AuditLogger(output_path=settings.audit_output_path)', 'audit = AuditLog("data/pg_audit.sqlite3")')

with open('whatsapp_server.py', 'w', encoding='utf-8') as f:
    f.write(c)
