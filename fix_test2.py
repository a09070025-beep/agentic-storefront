with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.split('sys.exit(0)')[0] + 'sys.exit(0)\n'

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
