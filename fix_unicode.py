with open('e2e_demo_verify.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('\u2014', '--')
c = c.replace('\u2192', '->')
with open('e2e_demo_verify.py', 'w', encoding='utf-8') as f:
    f.write(c)
