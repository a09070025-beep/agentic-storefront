import os
for r,d,fl in os.walk('.'):
    if '.venv' in r or '.git' in r: continue
    for f in fl:
        if f.endswith('.py'):
            try:
                if 'PromptRegistry' in open(os.path.join(r,f), encoding='utf-8').read():
                    print(os.path.join(r,f))
            except: pass
