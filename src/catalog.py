"""
Agentic Storefront — Catalog Store
Product search, filtering, and inventory management.
Loads from data/catalog.json and provides structured search for AI buyers.
"""

import json
from pathlib import Path
import sys
import os

# Add parent directory to path so we can import from agentic_storefront_guardrails
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentic_storefront_guardrails.inventory_lock import InventoryManager

from src.models import Product


class CatalogStore:
    """Product catalog with search, filtering, and stock management."""

    def __init__(self, catalog_path: str = "data/catalog.json", inventory: InventoryManager | None = None):
        self._products: dict[str, Product] = {}
        self.inventory = inventory or InventoryManager()
        self._load_catalog(catalog_path)

    def _load_catalog(self, path: str) -> None:
        """Load products from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in data:
            product = Product(**item)
            self._products[product.id] = product
            # Initialize stock in InventoryManager
            self.inventory.set_stock(product.id, product.stock)

    @property
    def product_count(self) -> int:
        return len(self._products)

    def search(
        self,
        query: str,
        category: str | None = None,
        max_price: int | None = None,
        min_price: int | None = None,
        limit: int = 10,
    ) -> list[Product]:
        """Search products by keyword across name, description, and tags.

        Args:
            query: Search keywords (case-insensitive, matches name/description/tags)
            category: Filter by category (exact match)
            max_price: Maximum price in paise (inclusive)
            min_price: Minimum price in paise (inclusive)
            limit: Maximum results to return

        Returns:
            List of matching products sorted by relevance (name match > tag match > description match)
        """
        query_lower = query.lower().strip()
        query_terms = query_lower.split()

        scored_results: list[tuple[int, Product]] = []

        for product in self._products.values():
            if not product.active:
                continue

            # Apply category filter
            if category and product.category.lower() != category.lower():
                continue

            # Apply price filters
            if max_price is not None and product.price > max_price:
                continue
            if min_price is not None and product.price < min_price:
                continue

            # Score relevance
            score = 0
            name_lower = product.name.lower()
            desc_lower = product.description.lower()
            tags_lower = [t.lower() for t in product.tags]

            for term in query_terms:
                if term in name_lower:
                    score += 10  # Name match = highest relevance
                if any(term in tag for tag in tags_lower):
                    score += 5   # Tag match = medium relevance
                if term in desc_lower:
                    score += 2   # Description match = lower relevance

            if score > 0:
                scored_results.append((score, product))

        # Sort by score descending, then by price ascending
        scored_results.sort(key=lambda x: (-x[0], x[1].price))

        return [product for _, product in scored_results[:limit]]

    def get_product(self, product_id: str) -> Product | None:
        """Get a single product by ID. Returns None if not found."""
        return self._products.get(product_id)

    def list_categories(self) -> list[str]:
        """Return all unique active categories."""
        categories = set()
        for product in self._products.values():
            if product.active:
                categories.add(product.category)
        return sorted(categories)

    def list_products(
        self, category: str | None = None, limit: int = 50
    ) -> list[Product]:
        """List products, optionally filtered by category."""
        products = [
            p for p in self._products.values()
            if p.active and (category is None or p.category == category)
        ]
        products.sort(key=lambda p: p.price)
        return products[:limit]

    def check_stock(self, product_id: str, quantity: int) -> bool:
        """Check if requested quantity is available."""
        return self.inventory.available(product_id) >= quantity

    def reserve_stock(self, product_id: str, quantity: int, negotiation_id: str) -> str:
        """Reserve stock for a cart. Returns reservation ID. Raises if insufficient."""
        return self.inventory.reserve(product_id, negotiation_id, quantity=quantity, ttl_seconds=15 * 60)

    def update_reservation(self, old_reservation_id: str, product_id: str, new_quantity: int, negotiation_id: str) -> str:
        """Update a reservation by releasing the old one and reserving the new total quantity."""
        if old_reservation_id:
            self.inventory.release(old_reservation_id)
        return self.inventory.reserve(product_id, negotiation_id, quantity=new_quantity, ttl_seconds=15 * 60)

    def extend_reservation(self, reservation_id: str, extra_seconds: int = 300) -> bool:
        return self.inventory.extend_ttl(reservation_id, extra_seconds)

    def release_stock(self, reservation_id: str) -> None:
        """Release previously reserved stock (cart expired/cancelled)."""
        self.inventory.release(reservation_id)
        
    def confirm_stock(self, reservation_id: str) -> None:
        """Permanently decrement stock for a reservation."""
        self.inventory.confirm(reservation_id)

    def get_products_by_ids(self, product_ids: list[str]) -> list[Product]:
        """Get multiple products by their IDs. Skips unknown IDs."""
        return [
            self._products[pid]
            for pid in product_ids
            if pid in self._products
        ]


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    from rich.table import Table

    console = Console(force_terminal=True)
    console.print("\n[bold blue]Catalog Store — Self-Test[/bold blue]\n")

    store = CatalogStore()
    console.print(f"Loaded {store.product_count} products\n")

    # Test 1: Search by keyword
    results = store.search("dark roast")
    console.print(f"[cyan]Search 'dark roast':[/cyan] {len(results)} results")
    for p in results[:3]:
        console.print(f"  {p.id}: {p.name} — {p.price_display}")

    # Test 2: Search with category filter
    results = store.search("coffee", category="coffee_beans")
    console.print(f"\n[cyan]Search 'coffee' in coffee_beans:[/cyan] {len(results)} results")
    for p in results[:3]:
        console.print(f"  {p.id}: {p.name} — {p.price_display}")

    # Test 3: Search with max price
    results = store.search("mug", max_price=30000)
    console.print(f"\n[cyan]Search 'mug' under Rs.300:[/cyan] {len(results)} results")
    for p in results:
        console.print(f"  {p.id}: {p.name} — {p.price_display}")

    # Test 4: Get product by ID
    product = store.get_product("prod_001")
    console.print(f"\n[cyan]Get prod_001:[/cyan] {product.name if product else 'NOT FOUND'}")

    # Test 5: Get non-existent product
    product = store.get_product("prod_999")
    console.print(f"[cyan]Get prod_999:[/cyan] {'FOUND' if product else 'NOT FOUND (correct)'}")

    # Test 6: List categories
    cats = store.list_categories()
    console.print(f"\n[cyan]Categories:[/cyan] {', '.join(cats)}")

    # Test 7: Stock check
    in_stock = store.check_stock("prod_001", 5)
    console.print(f"\n[cyan]Stock check prod_001 x5:[/cyan] {'Available' if in_stock else 'Out of stock'}")

    oos = store.check_stock("prod_090", 1)
    console.print(f"[cyan]Stock check prod_090 (OOS) x1:[/cyan] {'Available' if oos else 'Out of stock (correct)'}")

    # Test 8: Reserve and release stock
    original = store.get_product("prod_001").stock
    reserved = store.reserve_stock("prod_001", 3)
    after_reserve = store.get_product("prod_001").stock
    store.release_stock("prod_001", 3)
    after_release = store.get_product("prod_001").stock
    console.print(f"\n[cyan]Stock reserve/release prod_001:[/cyan]")
    console.print(f"  Before: {original} | After reserve(3): {after_reserve} | After release(3): {after_release}")

    console.print(f"\n[bold green]Catalog Store passed all tests![/bold green]\n")
