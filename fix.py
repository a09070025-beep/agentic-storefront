import re

with open('src/storefront_server.py', 'r', encoding='utf-8') as f:
    c = f.read()

new_c = re.sub(
    r'    try:\n        # Get cart.*?(?=    except CartExpiredError:)',
    r'''    try:
        cart = cart_mgr.get_cart(cart_id)
        audit.log(AuditAction.BOUNDS_CHECK, actor="system", details={"cart_id": cart_id, "total": cart.total, "max_allowed": settings.max_order_amount}, amount=cart.total, reason=f"Order Rs.{cart.total/100:.2f} within bounds")
        customer = {"name": customer_name, "email": customer_email, "contact": customer_phone}
        result = cart_mgr.finalize_cart(cart_id, customer_details=customer)
        if not result.success:
            return json.dumps({"error": f"Checkout blocked or failed: {result.message}"})
        return json.dumps({"status": "order_created", "payment_link_url": result.payment_link, "amount_display": f"Rs.{cart.total/100:.2f}"}, indent=2)
''',
    c, flags=re.DOTALL
)

with open('src/storefront_server.py', 'w', encoding='utf-8') as f:
    f.write(new_c)
