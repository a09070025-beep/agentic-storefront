import re

with open('agentic_storefront_guardrails/payment_gate.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = r'class PaymentGateResult:\n    success: bool\n    payment_link: str \| None\n    message: str'
replacement = r'''class PaymentGateResult:
    success: bool
    payment_link: str | None
    message: str
    needs_reconciliation: bool = False'''
c = re.sub(pattern, replacement, c)

pattern_confirm = r'''        # 5\. Confirm ALL\n        try:\n            for res_id in active_reservations:\n                self\.inventory\.confirm\(res_id\)\n        except Exception as e:\n            # FATAL: Payment link created but confirm failed\. \n            # Do NOT retry\. Alert for manual reconciliation\.\n            self\.audit\.log_payment\(negotiation_id, idempotency_key, "CART", total_amount, "fatal", f"Payment created but inventory confirm failed: \{e\}"\)\n            return PaymentGateResult\(True, link, f"WARNING: Payment created but stock confirmation failed \(\{e\}\)"\)\n            \n        self\.audit\.log_payment\(negotiation_id, idempotency_key, "CART",\n                               total_amount, "created",\n                               f"deal verified, \{len\(items\)\} items locked and paid"\)\n        return PaymentGateResult\(True, link, "Payment link created"\)'''
replacement_confirm = r'''        # 5. Confirm ALL
        needs_reconciliation = False
        for res_id in active_reservations:
            confirm_success = False
            for confirm_attempt in range(3):
                try:
                    self.inventory.confirm(res_id)
                    confirm_success = True
                    break
                except Exception as e:
                    time.sleep(0.5)
            
            if not confirm_success:
                needs_reconciliation = True
                self.audit.log_payment(negotiation_id, idempotency_key, "CART", total_amount, "fatal", f"Failed to confirm stock for reservation {res_id}")
                
        if needs_reconciliation:
            return PaymentGateResult(True, link, "WARNING: Payment created but some stock confirmations failed.", needs_reconciliation=True)

        self.audit.log_payment(negotiation_id, idempotency_key, "CART",
                               total_amount, "created",
                               f"deal verified, {len(items)} items locked and paid")
        return PaymentGateResult(True, link, "Payment link created")'''
        
c = re.sub(pattern_confirm, replacement_confirm, c)

with open('agentic_storefront_guardrails/payment_gate.py', 'w', encoding='utf-8') as f:
    f.write(c)
