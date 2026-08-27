with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('prod_001', 'prod_100')
c = c.replace('20000.0', '700000.0')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
