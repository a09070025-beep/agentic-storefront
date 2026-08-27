with open('src/storefront_server.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('result.message', 'result.reason')

with open('src/storefront_server.py', 'w', encoding='utf-8') as f:
    f.write(c)
