with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('700000.0', '7000.0')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
