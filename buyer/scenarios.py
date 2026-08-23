"""
Agentic Storefront — Purchase Scenarios
50+ deterministic test scenarios for batch metrics computation.
Each scenario defines a complete purchase flow with expected outcomes.
"""

from src.models import CustomerInfo, PurchaseScenario


def get_scenarios() -> list[PurchaseScenario]:
    """Return 50+ test scenarios covering all paths."""

    # Default test customers
    c1 = CustomerInfo(name="Arjun Sharma", email="arjun@test.com", phone="9123456780")
    c2 = CustomerInfo(name="Priya Patel", email="priya@test.com", phone="9234567801")
    c3 = CustomerInfo(name="Rahul Verma", email="rahul@test.com", phone="9345678012")
    c4 = CustomerInfo(name="Ananya Singh", email="ananya@test.com", phone="9456780123")
    c5 = CustomerInfo(name="Vikram Kumar", email="vikram@test.com", phone="9567801234")

    scenarios = [
        # ─── HAPPY PATH: Coffee purchases with upsell ────────────
        PurchaseScenario(
            id="s001", name="Dark roast + accept grinder upsell",
            search_query="dark roast", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s002", name="Light roast + accept filters upsell",
            search_query="light roast", select_product_index=0,
            accept_upsell=True, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s003", name="Medium roast + decline upsell",
            search_query="medium roast", select_product_index=0,
            accept_upsell=False, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s004", name="Ethiopian single-origin + upsell",
            search_query="ethiopian", select_product_index=0,
            accept_upsell=True, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s005", name="Espresso blend + decline upsell",
            search_query="espresso", select_product_index=0,
            accept_upsell=False, customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s006", name="Decaf coffee + accept upsell",
            search_query="decaf", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s007", name="Indian Malabar + upsell",
            search_query="indian", select_product_index=0,
            accept_upsell=True, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s008", name="Kenyan AA premium + decline upsell",
            search_query="kenya", select_product_index=0,
            accept_upsell=False, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s009", name="House blend everyday + upsell",
            search_query="house blend", select_product_index=0,
            accept_upsell=True, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s010", name="Colombian supremo + decline",
            search_query="colombian", select_product_index=0,
            accept_upsell=False, customer=c5, expected_outcome="success"
        ),

        # ─── EQUIPMENT PURCHASES ─────────────────────────────────
        PurchaseScenario(
            id="s011", name="V60 pour over + accept full setup",
            search_query="v60 pour over", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s012", name="French press + accept morning kit",
            search_query="french press", select_product_index=0,
            accept_upsell=True, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s013", name="AeroPress + accept travel pack",
            search_query="aeropress", select_product_index=0,
            accept_upsell=True, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s014", name="Moka pot + decline upsell",
            search_query="moka pot", select_product_index=0,
            accept_upsell=False, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s015", name="Cold brew kit + accept summer pack",
            search_query="cold brew", select_product_index=0,
            accept_upsell=True, customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s016", name="Chemex + accept elegance bundle",
            search_query="chemex", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s017", name="Electric kettle + decline upsell",
            search_query="gooseneck kettle", select_product_index=0,
            accept_upsell=False, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s018", name="Siphon brewer + accept premium beans",
            search_query="siphon", select_product_index=0,
            accept_upsell=True, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s019", name="Turkish cezve + accept set",
            search_query="turkish", select_product_index=0,
            accept_upsell=True, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s020", name="Drip coffee maker + accept station",
            search_query="drip coffee", select_product_index=0,
            accept_upsell=True, customer=c5, expected_outcome="success"
        ),

        # ─── ACCESSORIES PURCHASES ───────────────────────────────
        PurchaseScenario(
            id="s021", name="Coffee grinder + accept upsell",
            search_query="grinder", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s022", name="Digital scale + accept precision kit",
            search_query="scale", select_product_index=0,
            accept_upsell=True, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s023", name="Coffee canister + decline",
            search_query="canister", select_product_index=0,
            accept_upsell=False, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s024", name="Milk frother + accept latte art",
            search_query="frother", select_product_index=0,
            accept_upsell=True, customer=c4, expected_outcome="success"
        ),

        # ─── MUG & DRINKWARE PURCHASES ──────────────────────────
        PurchaseScenario(
            id="s025", name="Ceramic mug + decline upsell",
            search_query="ceramic mug", select_product_index=0,
            accept_upsell=False, customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s026", name="Travel tumbler + decline",
            search_query="travel tumbler", select_product_index=0,
            accept_upsell=False, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s027", name="Espresso cup set + accept upsell",
            search_query="espresso cup", select_product_index=0,
            accept_upsell=True, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s028", name="Double-wall glass cup + decline",
            search_query="double wall glass", select_product_index=0,
            accept_upsell=False, customer=c3, expected_outcome="success"
        ),

        # ─── GIFT SET PURCHASES ──────────────────────────────────
        PurchaseScenario(
            id="s029", name="Coffee starter kit",
            search_query="starter kit", select_product_index=0,
            accept_upsell=False, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s030", name="Premium sampler gift",
            search_query="sampler", select_product_index=0,
            accept_upsell=False, customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s031", name="Pour over master bundle",
            search_query="pour over master", select_product_index=0,
            accept_upsell=False, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s032", name="Home barista pro kit",
            search_query="barista pro", select_product_index=0,
            accept_upsell=False, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s033", name="Date night coffee set",
            search_query="date night", select_product_index=0,
            accept_upsell=False, customer=c3, expected_outcome="success"
        ),

        # ─── COUPON SCENARIOS ────────────────────────────────────
        PurchaseScenario(
            id="s034", name="Dark roast + WELCOME10 coupon",
            search_query="dark roast", select_product_index=0,
            accept_upsell=True, coupon_code="WELCOME10",
            customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s035", name="Equipment + COFFEE20 coupon",
            search_query="french press", select_product_index=0,
            accept_upsell=True, coupon_code="COFFEE20",
            customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s036", name="Big order + BUNDLE15 coupon",
            search_query="aeropress", select_product_index=0,
            additional_product_ids=["prod_041", "prod_062"],
            accept_upsell=True, coupon_code="BUNDLE15",
            customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s037", name="First buy + FIRSTBUY coupon",
            search_query="ethiopian", select_product_index=0,
            accept_upsell=True, coupon_code="FIRSTBUY",
            customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s038", name="Summer sale + SUMMER25 coupon",
            search_query="cold brew", select_product_index=0,
            additional_product_ids=["prod_003", "prod_060"],
            accept_upsell=True, coupon_code="SUMMER25",
            customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s039", name="Loyalty + LOYALTY5 coupon",
            search_query="house blend", select_product_index=0,
            accept_upsell=False, coupon_code="LOYALTY5",
            customer=c4, expected_outcome="success"
        ),

        # ─── FAILURE SCENARIOS (expected) ────────────────────────
        PurchaseScenario(
            id="s040", name="FAIL: Out of stock product",
            search_query="out of stock", select_product_index=0,
            accept_upsell=False, customer=c5, expected_outcome="out_of_stock"
        ),
        PurchaseScenario(
            id="s041", name="FAIL: Expired coupon EXPIRED01",
            search_query="dark roast", select_product_index=0,
            accept_upsell=False, coupon_code="EXPIRED01",
            customer=c1, expected_outcome="invalid_coupon"
        ),
        PurchaseScenario(
            id="s042", name="FAIL: Non-existent coupon FAKE99",
            search_query="medium roast", select_product_index=0,
            accept_upsell=False, coupon_code="FAKE99",
            customer=c2, expected_outcome="invalid_coupon"
        ),
        PurchaseScenario(
            id="s043", name="FAIL: MAXED100 coupon bounded to 30%",
            search_query="aeropress", select_product_index=0,
            accept_upsell=False, coupon_code="MAXED100",
            customer=c3, expected_outcome="success"
        ),

        # ─── MULTI-ITEM SCENARIOS ────────────────────────────────
        PurchaseScenario(
            id="s044", name="Coffee + equipment combo",
            search_query="dark roast", select_product_index=0,
            additional_product_ids=["prod_021"],
            accept_upsell=True, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s045", name="3 coffees bulk discount",
            search_query="coffee",
            search_filters={"category": "coffee_beans"},
            select_product_index=0,
            additional_product_ids=["prod_002", "prod_003"],
            accept_upsell=False, customer=c5, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s046", name="Gift set + mug combo",
            search_query="starter kit", select_product_index=0,
            additional_product_ids=["prod_060"],
            accept_upsell=False, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s047", name="Full brewing setup",
            search_query="v60", select_product_index=0,
            additional_product_ids=["prod_040", "prod_042", "prod_001"],
            accept_upsell=False, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s048", name="Espresso full kit",
            search_query="moka pot", select_product_index=0,
            additional_product_ids=["prod_009", "prod_063"],
            accept_upsell=True, customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s049", name="Office setup large order",
            search_query="drip coffee", select_product_index=0,
            additional_product_ids=["prod_012", "prod_043", "prod_060"],
            accept_upsell=False, coupon_code="BUNDLE15",
            customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s050", name="Weekend gift shopping",
            search_query="date night", select_product_index=0,
            additional_product_ids=["prod_062"],
            accept_upsell=False, coupon_code="WELCOME10",
            customer=c5, expected_outcome="success"
        ),

        # ─── ADDITIONAL VARIETY ──────────────────────────────────
        PurchaseScenario(
            id="s051", name="Guatemala coffee + upsell",
            search_query="guatemala", select_product_index=0,
            accept_upsell=True, customer=c1, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s052", name="Rwanda bourbon + decline",
            search_query="rwanda", select_product_index=0,
            accept_upsell=False, customer=c2, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s053", name="Costa Rica + coupon + upsell",
            search_query="costa rica", select_product_index=0,
            accept_upsell=True, coupon_code="FIRSTBUY",
            customer=c3, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s054", name="Camp mug + cold brew bottle",
            search_query="camp mug", select_product_index=0,
            additional_product_ids=["prod_069"],
            accept_upsell=False, customer=c4, expected_outcome="success"
        ),
        PurchaseScenario(
            id="s055", name="Latte art cup + frother bundle",
            search_query="latte art", select_product_index=0,
            accept_upsell=True, customer=c5, expected_outcome="success"
        ),
    ]

    return scenarios


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    scenarios = get_scenarios()
    print(f"Total scenarios: {len(scenarios)}")

    # Count by expected outcome
    outcomes = {}
    for s in scenarios:
        outcomes[s.expected_outcome] = outcomes.get(s.expected_outcome, 0) + 1

    print(f"\nBy expected outcome:")
    for outcome, count in sorted(outcomes.items()):
        print(f"  {outcome}: {count}")

    # Count upsell acceptance
    upsell_yes = sum(1 for s in scenarios if s.accept_upsell)
    upsell_no = sum(1 for s in scenarios if not s.accept_upsell)
    print(f"\nUpsell scenarios: {upsell_yes} accept, {upsell_no} decline")

    # Count coupon scenarios
    with_coupon = sum(1 for s in scenarios if s.coupon_code)
    print(f"Coupon scenarios: {with_coupon}")

    # Count multi-item scenarios
    multi = sum(1 for s in scenarios if s.additional_product_ids)
    print(f"Multi-item scenarios: {multi}")

    print(f"\nAll {len(scenarios)} scenarios validated!")
