import json, sys
sys.stdout.reconfigure(encoding="utf-8")

catalog = json.load(open("data/catalog.json"))
costs = json.load(open("data/cost_prices.json"))

from agentic_storefront_guardrails.guardrails import ProductCatalog, ProductRules, PriceGuard

pc = ProductCatalog()
for prod in catalog:
    pid = prod["id"]
    cost = costs.get(pid, 0)
    if cost == 0:
        continue
    pc.upsert(ProductRules(
        sku=pid,
        list_price=prod["price"],
        cost_floor=cost,
        max_discount_pct=0.60,
    ))

pg = PriceGuard(pc)

print("Framing B Candidate Products (list > Rs.550, stock > 0):")
fmt = "{:12s} {:40s} {:>8s} {:>8s} {:>8s}  {:>5s}"
print(fmt.format("ID", "Name", "List", "Cost", "Floor", "Stock"))
print("-" * 85)

cands = []
for prod in sorted(catalog, key=lambda p: p["price"]):
    pid = prod["id"]
    cost = costs.get(pid, 0)
    stock = prod.get("stock", 0)
    if cost == 0 or stock <= 0:
        continue
    r = pg.authoritative_check(pid, prod["price"])
    if prod["price"] > 55000 and r.floor_price < prod["price"]:
        n = prod["name"][:40]
        print(fmt.format(
            pid, n,
            "Rs.{:.0f}".format(prod["price"]/100),
            "Rs.{:.0f}".format(cost/100),
            "Rs.{:.0f}".format(r.floor_price/100),
            str(stock),
        ))
        cands.append({
            "id": pid,
            "name": prod["name"],
            "list_price": prod["price"],
            "cost": cost,
            "floor": r.floor_price,
            "stock": stock,
        })

print("\nTotal: {} candidate products".format(len(cands)))

# Propose 12 scenarios with buyer budgets in the sweet spot
print("\n\nPROPOSED FRAMING B SCENARIOS:")
print(fmt.format("ID", "Name", "List", "Floor", "Budget", ""))
print("-" * 85)
import random
random.seed(42)
selected = cands[:12]  # take 12 cheapest above-budget products
for c in selected:
    # Budget = midpoint of floor and list (ensures floor <= budget < list)
    budget = (c["floor"] + c["list_price"]) // 2
    print(fmt.format(
        c["id"], c["name"][:40],
        "Rs.{:.0f}".format(c["list_price"]/100),
        "Rs.{:.0f}".format(c["floor"]/100),
        "Rs.{:.0f}".format(budget/100),
        "OK" if c["floor"] <= budget < c["list_price"] else "BAD",
    ))
