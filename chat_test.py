import sys
sys.stdout.reconfigure(encoding='utf-8')
from src.merchant_ai import MerchantAI, NegotiationMessage
from src.models import Product
class PG:
    def check_price_tool(self, s, p):
        return {'allowed': p>=6900, 'reason': 'ok' if p>=6900 else 'too low'}

m = MerchantAI([Product(id='SKU1', name='Coffee Maker', price=10000, description='Maker', category='Equipment', stock=10)])
m.set_price_guard(PG())
msgs = [NegotiationMessage(role='buyer', message='Hi, I want the Coffee Maker for 5000.')]
r = m.generate_message(msgs, None)
print(f'Merchant: {r.message}')