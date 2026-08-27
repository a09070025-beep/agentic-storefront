with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('res1 = stack.inventory.reserve("prod_100", "test-rollback", quantity=1)', 'res1 = stack.inventory.reserve("prod_080", "test-rollback", quantity=1)')
c = c.replace('CheckoutItem(sku="prod_100", agreed_price=7000.0, quantity=1, reservation_id=res1)', 'CheckoutItem(sku="prod_080", agreed_price=2000.0, quantity=1, reservation_id=res1)')
c = c.replace('CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1)', 'CheckoutItem(sku="prod_081", agreed_price=10.0, quantity=1)')


with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
