import re

with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = r'''(print\("\\n" \+ "="\*60\))'''
replacement = r'''_rollback_test()
\1'''
c = re.sub(pattern, replacement, c)
c = c.replace('_rollback_test()\n\n\nif errors:', '\n\nif errors:')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
