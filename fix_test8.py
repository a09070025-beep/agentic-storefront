with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('print("\\n" + "="*60)\nprint(f"RESULTS: {len(passes)} passed, {len(errors)} failed")', '_rollback_test()\nprint("\\n" + "="*60)\nprint(f"RESULTS: {len(passes)} passed, {len(errors)} failed")')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
