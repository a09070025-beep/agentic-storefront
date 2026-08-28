import sys
import time
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catalog import CatalogStore
from src.buyer_ai import BuyerAI
from src.merchant_ai import MerchantAI
from src.models import NegotiationMessage, NegotiationResult
from agentic_storefront_guardrails.guardrails import PriceGuard, ProductCatalog

def main():
    import json
    from agentic_storefront_guardrails.guardrails import ProductRules
    
    with open("data/catalog.json", encoding="utf-8") as f:
        catalog_data = json.load(f)
    with open("data/cost_prices.json", encoding="utf-8") as f:
        costs = json.load(f)
        
    pc = ProductCatalog()
    for prod in catalog_data:
        pid = prod["id"]
        if pid in costs:
            pc.upsert(ProductRules(sku=pid, list_price=prod["price"], cost_floor=costs[pid], max_discount_pct=0.60))
    pg = PriceGuard(pc)
    catalog = CatalogStore()

    target_skus = [
        "prod_024", "prod_063", "prod_062", "prod_023", 
        "prod_021", "prod_042", "prod_020", "prod_101", 
        "prod_084", "prod_041", "prod_081", "prod_103"
    ]
    
    results = []
    
    for sku in target_skus:
        p = catalog.get_product(sku)
        if not p:
            continue
            
        list_price = p.price
        floor_price = pg.authoritative_check(sku, list_price).floor_price
        
        buyer_budget = ((floor_price + list_price) // 200) * 100
        
        print(f"\nRunning PROD AI for {p.name} (List: Rs.{list_price/100:.0f} | Floor: Rs.{floor_price/100:.0f} | Budget: Rs.{buyer_budget/100:.0f})")
        
        buyer = BuyerAI(
            product_names=[p.name],
            retail_price=list_price,
            persona={
                "name": "Test Buyer",
                "personality": "Budget-conscious, strict limit.",
                "budget": buyer_budget,
                "shopping_list": [p.name]
            }
        )
        
        merchant = MerchantAI(products=[p])
        merchant.set_price_guard(pg)
        
        merchant.bundle_context = "CRITICAL INSTRUCTION: DO NOT offer any bundles, combos, or upsells under ANY circumstances. Negotiate ONLY the price of the requested item."
        merchant._build_system_prompt()
        
        history = []
        agreed = False
        final_price = 0
        walked_away = False
        
        rounds = 1
        max_rounds = 4
        try:
            time.sleep(60)
            merchant_msg = merchant.generate_opening()
            history.append(merchant_msg)
            print(f"M: {merchant_msg.message.encode('ascii', 'ignore').decode()} (Offer: {merchant_msg.proposed_price})")
            
            while rounds <= max_rounds:
                buyer_msg = buyer.generate_message(history)
                history.append(buyer_msg)
                print(f"B: {buyer_msg.message.encode('ascii', 'ignore').decode()} (Offer: {buyer_msg.proposed_price})")
                
                if buyer_msg.walk_away:
                    walked_away = True
                    break
                    
                if buyer_msg.accepted:
                    agreed = True
                    final_price = buyer_msg.proposed_price or history[-2].proposed_price
                    break
                    
                time.sleep(60)
                merchant_msg = merchant.generate_message(history)
                history.append(merchant_msg)
                print(f"M: {merchant_msg.message.encode('ascii', 'ignore').decode()} (Offer: {merchant_msg.proposed_price})")
                
                if merchant_msg.walk_away:
                    walked_away = True
                    break
                    
                if merchant_msg.accepted:
                    agreed = True
                    final_price = merchant_msg.proposed_price or buyer_msg.proposed_price
                    break
                    
                rounds += 1
                
        except Exception as e:
            print(f"API Error: {e}")
            walked_away = True
            
        success = False
        if agreed:
            if floor_price <= final_price <= buyer_budget:
                success = True
                
        results.append({
            "sku": sku,
            "name": p.name[:35],
            "list": list_price,
            "floor": floor_price,
            "budget": buyer_budget,
            "agreed": agreed,
            "final_price": final_price,
            "success": success,
            "rounds": rounds
        })
        
        if success:
            print(f"  -> SUCCESS: Deal closed at Rs.{final_price/100:.0f} (Round {rounds})")
        elif agreed:
            print(f"  -> FAILED: Deal closed at Rs.{final_price/100:.0f} (Violated bounds!)")
        else:
            print(f"  -> FAILED: Walked away")

    print("\n" + "="*80)
    print("  FRAMING B RESULTS: TRUE PRODUCTION MERCHANT_AI")
    print("="*80)
    print(f"{'Product':35s} {'List_P':>7s}  {'Floor_P':>7s}  {'Budg_P':>7s}  {'Final_P':>7s}  {'Status':>10s}")
    print("-" * 80)
    
    success_count = sum(1 for r in results if r["success"])
    
    for r in results:
        f_final = str(r['final_price']) if r["agreed"] else "WALK"
        
        if r["success"]:
            status = "SUCCESS"
        elif r["agreed"]:
            status = "FAIL(PRICE)"
        else:
            status = "FAIL(WALK)"
            
        print(f"{r['name']:35s} {r['list']:>7d}  {r['floor']:>7d}  {r['budget']:>7d}  {f_final:>7s}  {status:>10s}")
        
    print("-" * 80)
    print(f"Conversion Rate: {success_count}/12 ({success_count/12*100:.1f}%)")
    
if __name__ == "__main__":
    main()
