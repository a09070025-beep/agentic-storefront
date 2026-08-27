with open('src/razorpay_service.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('self.audit = audit or AuditLogger()', 'self.audit = audit or AuditLog()')
c = c.replace('audit = AuditLogger(output_path="output/test_rzp_audit.jsonl")', 'audit = AuditLog("data/pg_audit.sqlite3")')

with open('src/razorpay_service.py', 'w', encoding='utf-8') as f:
    f.write(c)
