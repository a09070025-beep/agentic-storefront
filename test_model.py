import os
from openai import OpenAI
from config import get_settings
settings = get_settings()

client = OpenAI(
    api_key=settings.oss_api_key or os.getenv('OSS_API_KEY'),
    base_url=settings.oss_base_url or os.getenv('OSS_BASE_URL')
)

model = 'openai/gpt-oss-20b'
print(f'Testing {model}...')
r = client.chat.completions.create(
    model=model,
    messages=[
        {'role': 'system', 'content': 'You are a JSON simulation engine. Output ONLY a valid JSON array. No explanation.'},
        {'role': 'user', 'content': 'Simulate a 2-message negotiation. Output JSON array:\n[{\"role\":\"merchant\",\"message\":\"Welcome! Coffee set for 570.\",\"proposed_price\":570,\"accepted\":false,\"walk_away\":false,\"bundle_offer\":null},{\"role\":\"buyer\",\"message\":\"Deal!\",\"proposed_price\":570,\"accepted\":true,\"walk_away\":false,\"bundle_offer\":null}]'}
    ],
    temperature=0.5,
    max_tokens=500,
)
print('Result:')
print(r.choices[0].message.content)
