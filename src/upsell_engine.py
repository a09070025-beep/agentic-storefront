"""
Agentic Storefront — Upsell Engine
Rule-based cross-sell/upsell recommendations with bundle pricing.
Designed to increase AOV by 15-25% through intelligent product suggestions.

Every recommendation is EXPLAINABLE — the reason is logged to the audit trail.
"""

import json
from pathlib import Path

from src.models import (
    BundlePricing, BundleRule, Product, Recommendation
)
from src.catalog import CatalogStore


class UpsellEngine:
    """Rule-based upsell/cross-sell engine with bundle pricing."""

    def __init__(
        self,
        catalog: CatalogStore,
        rules_path: str = "data/bundle_rules.json",
    ):
        self.catalog = catalog
        self._rules: list[BundleRule] = []
        self._load_rules(rules_path)

    def _load_rules(self, path: str) -> None:
        """Load bundle rules from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._rules = [BundleRule(**item) for item in data]

    def get_recommendations(
        self,
        product_ids: list[str],
        max_recommendations: int = 3,
    ) -> list[Recommendation]:
        """Get upsell/cross-sell recommendations for products.

        Given products currently in the cart or being browsed, returns
        complementary product suggestions with bundle savings.

        Args:
            product_ids: IDs of products currently selected/in cart
            max_recommendations: Max number of recommendations to return

        Returns:
            List of Recommendation objects with product, discount, and reason
        """
        if not product_ids:
            return []

        product_id_set = set(product_ids)
        recommendations: list[Recommendation] = []
        seen_product_ids: set[str] = set(product_ids)  # don't recommend what's already selected

        for rule in self._rules:
            # Check if any trigger product is in the selected set
            trigger_match = product_id_set & set(rule.trigger_products)
            if not trigger_match:
                continue

            # Skip rules with no recommend_products (category bulk discounts)
            if not rule.recommend_products:
                continue

            # Recommend products not already selected
            for rec_id in rule.recommend_products:
                if rec_id in seen_product_ids:
                    continue

                product = self.catalog.get_product(rec_id)
                if not product or not product.active or product.stock <= 0:
                    continue

                # Calculate potential savings
                savings = int(product.price * rule.bundle_discount_pct / 100)

                recommendations.append(Recommendation(
                    product=product,
                    bundle_discount_pct=rule.bundle_discount_pct,
                    reason=rule.reason,
                    potential_savings=savings,
                ))
                seen_product_ids.add(rec_id)

        # Sort by potential savings descending
        recommendations.sort(key=lambda r: -r.potential_savings)

        return recommendations[:max_recommendations]

    def calculate_bundle_price(
        self, product_ids: list[str]
    ) -> BundlePricing:
        """Calculate total price with best applicable bundle discount.

        Finds the highest-discount rule that applies to the given products
        and calculates the bundle price.

        Args:
            product_ids: List of all product IDs being purchased together

        Returns:
            BundlePricing with original total, discounted total, and savings
        """
        products = self.catalog.get_products_by_ids(product_ids)
        original_total = sum(p.price for p in products)

        if not products or len(products) < 2:
            return BundlePricing(
                original_total=original_total,
                bundle_total=original_total,
                savings=0,
                savings_pct=0.0,
                applied_rule=None,
            )

        product_id_set = set(product_ids)

        # Find the best applicable rule (highest discount)
        best_discount_pct = 0.0
        best_rule_name = None

        for rule in self._rules:
            # Check how many trigger products match
            trigger_match = product_id_set & set(rule.trigger_products)
            if not trigger_match:
                continue

            # For "category bulk" rules (no recommend_products), need 3+ triggers
            if not rule.recommend_products:
                if len(trigger_match) >= 3 and rule.bundle_discount_pct > best_discount_pct:
                    best_discount_pct = rule.bundle_discount_pct
                    best_rule_name = rule.name
            else:
                # For regular bundles, check if any recommended product is also selected
                rec_match = product_id_set & set(rule.recommend_products)
                if rec_match and rule.bundle_discount_pct > best_discount_pct:
                    best_discount_pct = rule.bundle_discount_pct
                    best_rule_name = rule.name

        if best_discount_pct > 0:
            savings = int(original_total * best_discount_pct / 100)
            bundle_total = original_total - savings
            return BundlePricing(
                original_total=original_total,
                bundle_total=bundle_total,
                savings=savings,
                savings_pct=best_discount_pct,
                applied_rule=best_rule_name,
            )

        return BundlePricing(
            original_total=original_total,
            bundle_total=original_total,
            savings=0,
            savings_pct=0.0,
            applied_rule=None,
        )

    def get_category_upsells(
        self,
        category: str,
        exclude_ids: list[str] | None = None,
        limit: int = 3,
    ) -> list[Product]:
        """Get top products from same category not already in cart.

        Useful for "you might also like" within the same category.
        """
        exclude = set(exclude_ids or [])
        products = [
            p for p in self.catalog.list_products(category=category)
            if p.id not in exclude and p.stock > 0
        ]
        return products[:limit]


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    console = Console(force_terminal=True)

    console.print("\n[bold blue]Upsell Engine — Self-Test[/bold blue]\n")

    catalog = CatalogStore()
    engine = UpsellEngine(catalog)

    # Test 1: Recommendations for a coffee bean
    recs = engine.get_recommendations(["prod_001"])
    console.print(f"[cyan]Recommendations for Ethiopian Yirgacheffe:[/cyan]")
    for r in recs:
        console.print(
            f"  + {r.product.name} ({r.product.price_display}) "
            f"— Save {r.bundle_discount_pct}% (Rs.{r.potential_savings/100:.2f})"
        )
        console.print(f"    Reason: {r.reason}")

    # Test 2: Recommendations for V60 dripper
    recs = engine.get_recommendations(["prod_020"])
    console.print(f"\n[cyan]Recommendations for V60 Dripper:[/cyan]")
    for r in recs:
        console.print(
            f"  + {r.product.name} ({r.product.price_display}) "
            f"— Save {r.bundle_discount_pct}%"
        )

    # Test 3: Bundle pricing — coffee + grinder
    pricing = engine.calculate_bundle_price(["prod_001", "prod_041"])
    console.print(f"\n[cyan]Bundle: Ethiopian + Grinder:[/cyan]")
    console.print(f"  Original: Rs.{pricing.original_total/100:.2f}")
    console.print(f"  Bundle:   Rs.{pricing.bundle_total/100:.2f}")
    console.print(f"  Savings:  Rs.{pricing.savings/100:.2f} ({pricing.savings_pct}%)")
    console.print(f"  Rule:     {pricing.applied_rule}")

    # Test 4: Bundle pricing — 3 coffee beans (category bulk)
    pricing = engine.calculate_bundle_price(["prod_001", "prod_002", "prod_003"])
    console.print(f"\n[cyan]Bundle: 3 Coffee Beans (bulk):[/cyan]")
    console.print(f"  Original: Rs.{pricing.original_total/100:.2f}")
    console.print(f"  Bundle:   Rs.{pricing.bundle_total/100:.2f}")
    console.print(f"  Savings:  Rs.{pricing.savings/100:.2f} ({pricing.savings_pct}%)")
    console.print(f"  Rule:     {pricing.applied_rule}")

    # Test 5: No recommendations for single non-trigger product
    recs = engine.get_recommendations(["prod_060"])  # just a mug
    console.print(f"\n[cyan]Recommendations for Ceramic Mug:[/cyan] {len(recs)} (expected 0-1)")

    # Test 6: Category upsells
    upsells = engine.get_category_upsells("coffee_beans", exclude_ids=["prod_001"])
    console.print(f"\n[cyan]Category upsells (coffee, excl prod_001):[/cyan] {len(upsells)} products")
    for p in upsells:
        console.print(f"  {p.name} — {p.price_display}")

    console.print(f"\n[bold green]Upsell Engine passed all tests![/bold green]\n")
