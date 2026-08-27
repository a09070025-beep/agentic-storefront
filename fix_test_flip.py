with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = '''        CheckoutItem(sku="prod_001", agreed_price=20000.0, quantity=1, reservation_id=res1),
        CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1)'''

replacement = '''        CheckoutItem(sku="prod_002", agreed_price=10.0, quantity=1),
        CheckoutItem(sku="prod_001", agreed_price=20000.0, quantity=1, reservation_id=res1)'''

if pattern in c:
    c = c.replace(pattern, replacement)
    with open('test_full_integration.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print("Flipped!")
else:
    print("Pattern not found!")
