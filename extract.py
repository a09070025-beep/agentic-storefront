import json
import re

out = ""
with open(r'C:\Users\Ayush Rai\.gemini\antigravity\brain\52265bbb-921c-4b9b-a756-523fe004afd2\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'GENERIC':
            content = data.get('content', '')
            if 'def test(name):' in content and 'Full integration test' in content:
                # We found a cat command that output the file!
                out = content
                
with open('extracted_test.txt', 'w', encoding='utf-8') as f:
    f.write(out)
