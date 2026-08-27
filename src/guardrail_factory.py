"""
Guardrail Factory — builds the full guardrail stack from real catalog data.

Shared by whatsapp_server.py, web_app.py, and any other entry point that
needs PriceGuard / PaymentGate / InventoryManager / AuditLog.

Usage:
    from src.guardrail_factory import get_guardrail_stack
    stack = get_guardrail_stack()
    # stack.price_guard, stack.payment_gate, stack.inventory, stack.audit, etc.
"""

import json
import hashlib
import os
from dataclasses import dataclass

from agentic_storefront_guardrails import (
    ProductCatalog, ProductRules, PriceGuard,
    InventoryManager, AuditLog, PaymentGate,
)
from src.razorpay_service import RazorpayService
from config import get_settings


@dataclass
class GuardrailStack:
    """All guardrail components, pre-wired and ready to use."""
    catalog: ProductCatalog
    price_guard: PriceGuard
    inventory: InventoryManager
    audit: AuditLog
    payment_gate: PaymentGate


def _build_product_catalog() -> ProductCatalog:
    """Load product rules from data/catalog.json + data/cost_prices.json
    and populate a ProductCatalog with correct floors and discount caps."""
    catalog = ProductCatalog()

    # Load catalog and cost data
    catalog_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "catalog.json")
    costs_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cost_prices.json")

    with open(catalog_path, "r", encoding="utf-8") as f:
        products = json.load(f)

    with open(costs_path, "r", encoding="utf-8") as f:
        cost_data = json.load(f)

    for product in products:
        pid = product["id"]
        list_price_paise = product["price"]
        list_price_rupees = list_price_paise / 100

        # Cost in paise from cost_prices.json, fallback to 60% of retail
        cost_paise = cost_data.get(pid, int(list_price_paise * 0.6))

        # Floor = cost * 1.15 (15% margin), same formula as MerchantAI
        floor_paise = int(cost_paise * 1.15)
        floor_rupees = floor_paise / 100

        # Max discount = (list - floor) / list, capped at 60%
        max_discount = min(0.60, (list_price_rupees - floor_rupees) / list_price_rupees)

        catalog.upsert(ProductRules(
            sku=pid,
            list_price=list_price_rupees,
            cost_floor=floor_rupees,
            max_discount_pct=max_discount,
        ))

    return catalog


def _build_razorpay_create_link_fn():
    """Build the razorpay_create_link_fn injected into PaymentGate.
    This wraps RazorpayService.create_payment_link so PaymentGate stays
    decoupled from the Razorpay SDK."""
    settings = get_settings()

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        # No Razorpay keys — return a stub that logs but doesn't create real links
        def stub_fn(items, amount: float, customer: dict = None) -> str:
            return f"https://rzp.io/l/stub-{items[0].sku}-{int(amount)}"
        return stub_fn

    service = RazorpayService(settings=settings)

    def real_fn(items, amount: float, customer: dict = None) -> str:
        """Call the real Razorpay API to create a payment link."""
        description = f"Agentic Storefront Order — {len(items)} items"
        try:
            plink = service.create_payment_link(
                amount=int(amount * 100),
                currency="INR",
                description=description,
                customer=customer or {},
                receipt="mcp_gate_link"
            )
            return plink.get("short_url", plink.get("id", ""))
        except Exception as e:
            if "limit of 30" in str(e).lower():
                print("WARNING: Razorpay test limit reached. Returning dummy link.")
                return f"https://rzp.io/l/limit-reached-{items[0].sku}"
            raise e

    return real_fn


def _build_inventory(products_json_path: str | None = None) -> InventoryManager:
    """Build an InventoryManager seeded with stock levels from the catalog."""
    inventory = InventoryManager()

    path = products_json_path or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "catalog.json"
    )

    with open(path, "r", encoding="utf-8") as f:
        products = json.load(f)

    for product in products:
        inventory.set_stock(product["id"], product.get("stock", 0))

    return inventory


# Module-level singleton — built lazily
_stack: GuardrailStack | None = None


def get_guardrail_stack(db_path: str = "data/pg_audit.sqlite3") -> GuardrailStack:
    """Get or create the shared guardrail stack singleton."""
    global _stack
    if _stack is not None:
        return _stack

    product_catalog = _build_product_catalog()
    price_guard = PriceGuard(product_catalog)
    inventory = _build_inventory()
    audit = AuditLog(db_path=db_path)
    razorpay_fn = _build_razorpay_create_link_fn()

    payment_gate = PaymentGate(
        price_guard=price_guard,
        inventory=inventory,
        audit=audit,
        razorpay_create_link_fn=razorpay_fn,
    )

    _stack = GuardrailStack(
        catalog=product_catalog,
        price_guard=price_guard,
        inventory=inventory,
        audit=audit,
        payment_gate=payment_gate,
    )
    return _stack


def make_idempotency_key(negotiation_id: str, round_number: int) -> str:
    """Derive a deterministic idempotency key from negotiation_id + round.
    Prevents duplicate payment links on retries."""
    raw = f"{negotiation_id}:{round_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
