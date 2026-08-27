with open('src/razorpay_service.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from src.audit_logger import AuditLogger', 'from agentic_storefront_guardrails.audit_log import AuditLog')
c = c.replace('audit: AuditLogger', 'audit: AuditLog')

with open('src/razorpay_service.py', 'w', encoding='utf-8') as f:
    f.write(c)
