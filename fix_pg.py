import re

with open('agentic_storefront_guardrails/payment_gate.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace everything from '# 4. Call Razorpay' up to the next method or end of function
pattern = r'# 4\. Call Razorpay with retry \+ graceful degradation.*?(?=\n\n# -|$)'
replacement = r'''# 4. Call Razorpay with retry + graceful degradation
        link = None
        last_error = ""
        for attempt in range(1, max_retries + 2):
            try:
                link = self._create_link(items, total_amount, customer_details)
                break  # Success, exit retry loop
            except Exception as e:
                last_error = str(e)

        if not link:
            # Exhausted retries, release reservations explicitly
            for res_id in active_reservations:
                self.inventory.release(res_id)
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", 0, "failed", f"Razorpay API failed: {last_error}")
            return PaymentGateResult(False, None, f"Payment API failed: {last_error}")

        self.idempotency.put(idempotency_key, link)
        
        # 5. Confirm ALL
        try:
            for res_id in active_reservations:
                self.inventory.confirm(res_id)
        except Exception as e:
            # FATAL: Payment link created but confirm failed. 
            # Do NOT retry. Alert for manual reconciliation.
            self.audit.log_payment(negotiation_id, idempotency_key, "CART", total_amount, "fatal", f"Payment created but inventory confirm failed: {e}")
            return PaymentGateResult(True, link, f"WARNING: Payment created but stock confirmation failed ({e})")
            
        self.audit.log_payment(negotiation_id, idempotency_key, "CART",
                               total_amount, "created",
                               f"deal verified, {len(items)} items locked and paid")
        return PaymentGateResult(True, link, "Payment link created")'''

new_c = re.sub(pattern, replacement, c, flags=re.DOTALL)

with open('agentic_storefront_guardrails/payment_gate.py', 'w', encoding='utf-8') as f:
    f.write(new_c)
