import os
import re

for root, dirs, files in os.walk('.'):
    if '.venv' in root or '.git' in root:
        continue
    for f in files:
        if f.endswith(('.py', '.txt', '.json')):
            try:
                for i, line in enumerate(open(os.path.join(root, f), encoding='utf-8', errors='ignore')):
                    if re.search(r'cost_price|floor_price|1\.15', line):
                        print(f'{os.path.relpath(os.path.join(root, f), ".")}:{i+1}:{line.rstrip()}')
            except Exception: pass
