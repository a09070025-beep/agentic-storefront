import sys
sys.stdout.reconfigure(encoding='utf-8')
from src.merchant_ai import MerchantAI, NegotiationMessage
from src.models import Product
from agentic_storefront_guardrails.guardrails import PriceCheckResult
class PG:
    def check_price_tool(self, s, p):
        return PriceCheckResult(allowed=p>=6900, reason='ok', cost_floor=0, list_price=0, proposed_price=p)

m = MerchantAI([Product(id='SKU1', name='Coffee Maker', price=10000, description='Maker', category='Equipment', stock=10)])
m.set_price_guard(PG())
print(m.generate_message([NegotiationMessage(role='buyer', message='Hi, I want the Coffee Maker for 5000.')], None).message)