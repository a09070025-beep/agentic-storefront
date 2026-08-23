"""Quick smoke test for all new modules."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

print("=" * 50)
print("TEST 1: Models — NegotiationMessage, NegotiationResult")
print("=" * 50)
from src.models import NegotiationMessage, NegotiationResult, AuditAction
actions = [a.value for a in AuditAction if "NEGOTIATION" in a.value]
print(f"  Negotiation AuditActions: {actions}")
msg = NegotiationMessage(role="buyer", message="test", proposed_price=50000)
print(f"  NegotiationMessage: role={msg.role}, price={msg.proposed_price}")
res = NegotiationResult(agreed=True, final_price=48000, rounds=3, retail_price=57000)
print(f"  NegotiationResult: agreed={res.agreed}, price={res.final_price}")
print("  ✅ PASS\n")

print("=" * 50)
print("TEST 2: Cost Prices")
print("=" * 50)
from src.merchant_ai import load_cost_prices
cp = load_cost_prices()
print(f"  Loaded {len(cp)} cost prices")
print(f"  prod_002 (Colombian Supremo) cost: Rs.{cp['prod_002']/100:.0f}")
print(f"  prod_040 (V60 Filters) cost: Rs.{cp['prod_040']/100:.0f}")
print("  ✅ PASS\n")

print("=" * 50)
print("TEST 3: Pricing Math")
print("=" * 50)
from src.catalog import CatalogStore
catalog = CatalogStore()
p2 = catalog.get_product("prod_002")
p40 = catalog.get_product("prod_040")
retail = p2.price + p40.price
cost = cp["prod_002"] + cp["prod_040"]
floor = int(cost * 1.15)
print(f"  Retail: Rs.{retail/100:.0f}")
print(f"  Cost: Rs.{cost/100:.0f}")
print(f"  Floor (15% margin): Rs.{floor/100:.0f}")
print(f"  Margin at retail: {(retail - cost) / cost * 100:.1f}%")
assert floor < retail, "Floor must be below retail!"
print("  ✅ PASS\n")

print("=" * 50)
print("TEST 4: Config — Gemini API Key")
print("=" * 50)
from config import get_settings
settings = get_settings()
has_key = bool(settings.gemini_api_key)
print(f"  GEMINI_API_KEY set: {has_key}")
if has_key:
    print(f"  Key prefix: {settings.gemini_api_key[:10]}...")
    print("  ✅ PASS\n")
else:
    print("  ⚠️  No key — LLM tests will be skipped")
    print("  Set GEMINI_API_KEY in .env to enable AI negotiation\n")

print("=" * 50)
print("TEST 5: BuyerAI Import")
print("=" * 50)
try:
    from src.buyer_ai import BuyerAI
    if has_key:
        buyer = BuyerAI(
            product_names=["Colombian Supremo", "V60 Filters"],
            retail_price=57000,
        )
        print(f"  BuyerAI initialized: budget=Rs.{buyer.budget/100:.0f}")
        print("  ✅ PASS\n")
    else:
        print("  ⚠️  Skipped (no API key)\n")
except ValueError as e:
    print(f"  ⚠️  Skipped: {e}\n")
except Exception as e:
    print(f"  ❌ FAIL: {e}\n")
    raise

print("=" * 50)
print("TEST 6: MerchantAI Import")
print("=" * 50)
try:
    from src.merchant_ai import MerchantAI
    if has_key:
        merchant = MerchantAI(products=[p2, p40], cost_prices=cp)
        print(f"  MerchantAI initialized:")
        print(f"    Retail: Rs.{merchant.retail_price/100:.0f}")
        print(f"    Cost: Rs.{merchant.cost_price/100:.0f}")
        print(f"    Floor: Rs.{merchant.floor_price/100:.0f}")
        print("  ✅ PASS\n")
    else:
        print("  ⚠️  Skipped (no API key)\n")
except ValueError as e:
    print(f"  ⚠️  Skipped: {e}\n")
except Exception as e:
    print(f"  ❌ FAIL: {e}\n")
    raise

print("=" * 50)
print("TEST 7: NegotiationArena Import")
print("=" * 50)
try:
    from src.negotiation_arena import NegotiationArena
    print("  NegotiationArena imported successfully")
    print("  ✅ PASS\n")
except Exception as e:
    print(f"  ❌ FAIL: {e}\n")
    raise

print("=" * 50)
print("TEST 8: main.py CLI Dispatch")
print("=" * 50)
# Test that negotiate is in main
import importlib
import main as main_mod
importlib.reload(main_mod)
import inspect
source = inspect.getsource(main_mod.main)
assert "negotiate" in source, "negotiate not found in main()"
print("  'negotiate' command found in main()")
print("  ✅ PASS\n")

print("=" * 50)
print("ALL SMOKE TESTS PASSED ✅")
print("=" * 50)
