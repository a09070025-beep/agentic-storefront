import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from fastapi.testclient import TestClient
from web_app import app

client = TestClient(app)

def run_tests():
    print('--- Testing ACP Protocol ---')
    # Valid ACP request
    payload = {'buyer_agent_id': 'agent_007', 'sku': 'prod_062', 'proposed_price': 750.0, 'message': 'I want this tumbler'}
    resp = client.post('/api/agent-protocol', json=payload)
    print('ACP Status:', resp.status_code)
    print('ACP Response:', resp.json())

    print('\n--- Testing x402 Protocol ---')
    # 1. Request without auth -> 402
    resp2 = client.get('/api/x402/purchase/prod_062')
    print('x402 Without Auth Status:', resp2.status_code)
    print('x402 Without Auth Response:', resp2.text)

    # 2. Request with valid auth -> 200
    resp3 = client.get('/api/x402/purchase/prod_062', headers={'Authorization': 'Payment pay_1234567890'})
    print('x402 With Auth Status:', resp3.status_code)
    print('x402 With Auth Response:', resp3.json())

if __name__ == '__main__':
    run_tests()

