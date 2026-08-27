with open('agentic_storefront_guardrails/payment_gate.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = '''                try:
                    self.inventory.confirm(res_id)
                    confirm_success = True
                    break
                except Exception as e:
                    time.sleep(0.5)'''

replacement = '''                try:
                    self.inventory.confirm(res_id)
                    confirm_success = True
                    break
                except RuntimeError as e:
                    if "not found" in str(e).lower():
                        break # Permanent failure, don't retry
                    time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)'''

c = c.replace(pattern, replacement)

with open('agentic_storefront_guardrails/payment_gate.py', 'w', encoding='utf-8') as f:
    f.write(c)
