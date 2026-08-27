with open('src/storefront_server.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = '''        if not result.success:
            return json.dumps({"error": f"Checkout blocked or failed: {result.reason}"})
        
        return json.dumps({"status": "order_created", "payment_link_url": result.payment_link, "amount_display": f"Rs.{cart.total/100:.2f}"}, indent=2)'''

replacement = '''        if not result.success:
            return json.dumps({"error": f"Checkout blocked or failed: {result.reason}"})
            
        status = "order_created_with_warnings" if result.needs_reconciliation else "order_created"
        return json.dumps({"status": status, "payment_link_url": result.payment_link, "amount_display": f"Rs.{cart.total/100:.2f}", "message": result.reason}, indent=2)'''

if pattern in c:
    c = c.replace(pattern, replacement)
    with open('src/storefront_server.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Replaced!")
else:
    print("Pattern not found!")
