with open('src/cart_manager.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = '''        if result.success:
            cart.status = CartStatus.CHECKED_OUT
        else:'''

replacement = '''        if result.success:
            if getattr(result, "needs_reconciliation", False):
                cart.status = CartStatus.CHECKED_OUT_NEEDS_RECONCILIATION
            else:
                cart.status = CartStatus.CHECKED_OUT
        else:'''

c = c.replace(pattern, replacement)

with open('src/cart_manager.py', 'w', encoding='utf-8') as f:
    f.write(c)
