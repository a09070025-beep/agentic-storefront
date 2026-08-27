import os

files_to_fix = [
    'buyer/agent.py',
    'src/negotiation_arena.py',
    'src/webhook_handler.py',
]

for file_path in files_to_fix:
    with open(file_path, 'r', encoding='utf-8') as f:
        c = f.read()

    c = c.replace('from src.audit_logger import AuditLogger', 'from agentic_storefront_guardrails.audit_log import AuditLog')
    c = c.replace('AuditLogger(output_path=self.settings.audit_output_path)', 'AuditLog("data/pg_audit.sqlite3")')
    c = c.replace('AuditLogger(output_path="output/negotiation_audit.jsonl")', 'AuditLog("data/pg_audit.sqlite3")')
    c = c.replace('AuditLogger(output_path="output/test_webhook_audit.jsonl")', 'AuditLog("data/pg_audit.sqlite3")')
    c = c.replace('audit: AuditLogger', 'audit: AuditLog')
    c = c.replace('audit or AuditLogger()', 'audit or AuditLog("data/pg_audit.sqlite3")')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(c)
