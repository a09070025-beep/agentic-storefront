import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from src.merchant_ai import MerchantAI
from src.models import Product

p = Product(id='prod_062', name='Travel Tumbler', description='Tumbler', price=75000, category='mugs_drinkware', stock=30, active=True)
merchant = MerchantAI(products=[p])

print('--- Testing Merchant Prompt Loading ---')
print('SYSTEM PROMPT SNIPPET:')
print(merchant.system_prompt[:250])

print('\n--- Testing AI Conversation (Checking tone & disclosure) ---')
from src.models import NegotiationMessage
history = [NegotiationMessage(role='buyer', message='Hi, are you a human or a robot? I am just asking, no need to negotiate right now.')]
msg = merchant.generate_message(conversation_history=history)
print('AI RESPONSE:')
print(msg.message)

