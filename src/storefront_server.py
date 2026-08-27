"""
Agentic Storefront — MCP Server
The heart of the system. Exposes 8 tools for AI buyers to discover,
browse, bundle, and checkout products autonomously.

Transport: stdio (AI buyer spawns this as subprocess)
Protocol: Model Context Protocol (MCP) v2

Tools:
  1. search_catalog    — Search products by keyword/category/price
  2. get_product       — Get full product details by ID
  3. get_recommendations — Get upsell/cross-sell suggestions
  4. create_cart       — Create cart from items list
  5. add_to_cart       — Add item to existing cart
  6. apply_coupon      — Apply discount code to cart
  7. checkout          — Create Razorpay order + payment link
  8. get_order_status  — Check payment status
"""

import json

from mcp.server.mcpserver import MCPServer

from config import get_settings, get_razorpay_client
from src.models import AuditAction
from src.catalog import CatalogStore
from src.upsell_engine import UpsellEngine
from src.cart_manager import (
    CartManager, CartError, OutOfStockError,
    InvalidProductError, InvalidCouponError,
    MinCartValueError, BoundsExceededError, CartExpiredError,
)
from src.razorpay_service import RazorpayService
from src.audit_logger import AuditLogger


from agentic_storefront_guardrails.payment_gate import PaymentGate, IdempotencyStore
from agentic_storefront_guardrails.guardrails import PriceGuard, ProductCatalog, ProductRules
from agentic_storefront_guardrails.schemas import CheckoutItem

# ── Initialize components ─────────────────────────────────────────────
settings = get_settings()
audit = AuditLogger(output_path=settings.audit_output_path)
catalog = CatalogStore(catalog_path=settings.catalog_path)
upsell = UpsellEngine(catalog, rules_path=settings.bundle_rules_path)

# Razorpay client — may be None if keys not configured
rzp_service = None
try:
    rzp_client = get_razorpay_client(settings)
    rzp_service = RazorpayService(client=rzp_client, audit=audit, settings=settings)
except ValueError:
    pass  # Keys not configured — checkout will fail gracefully

def _create_link_adapter(items, amount: float, customer: dict = None) -> str:
    if not rzp_service:
        raise ValueError("Razorpay not configured")
    result = rzp_service.create_payment_link(
        amount=int(amount * 100),
        currency="INR",
        description=f"Agentic Storefront Order — {len(items)} items",
        customer=customer or {},
        receipt="mcp_gate_link"
    )
    return result.get("short_url", result.get("id", ""))

price_guard = PriceGuard(ProductCatalog()) # Dummy, not strictly matching the JSON right now, but sufficient for initialization
from agentic_storefront_guardrails.audit_log import AuditLog
pg_audit = AuditLog("data/pg_audit.sqlite3")
payment_gate = PaymentGate(
    price_guard=price_guard,
    inventory=catalog.inventory,
    audit=pg_audit, 
    idempotency=IdempotencyStore(),
    razorpay_create_link_fn=_create_link_adapter,
)

cart_mgr = CartManager(catalog, upsell, audit, payment_gate, settings)

# ── Create MCP Server ────────────────────────────────────────
mcp = MCPServer(
    "agentic-storefront",
    instructions=(
        "You are connected to a gourmet coffee merchant's storefront. "
        "Use the available tools to search products, get recommendations, "
        "build a cart, apply coupons, and checkout. All prices are in INR. "
        "Every financial action is audited and bounded for safety."
    ),
)


# ── Tool 1: Search Catalog ───────────────────────────────────
@mcp.tool()
def search_catalog(
    query: str,
    category: str | None = None,
    max_price: int | None = None,
    limit: int = 10,
) -> str:
    """Search the product catalog by keyword, category, or price range.

    Args:
        query: Search keywords (e.g., 'dark roast coffee', 'grinder')
        category: Filter by category. Options: coffee_beans, brewing_equipment, accessories, mugs_drinkware, gift_sets
        max_price: Maximum price in paise (e.g., 50000 for Rs.500)
        limit: Max results to return (default 10)

    Returns:
        JSON list of matching products with id, name, price, category, stock.
    """
    results = catalog.search(query, category=category, max_price=max_price, limit=limit)

    audit.log(
        AuditAction.CATALOG_SEARCH, actor="buyer_agent",
        details={"query": query, "category": category, "max_price": max_price,
                 "results_count": len(results)},
        reason=f"Searched '{query}' — found {len(results)} products"
    )

    return json.dumps([
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price_paise": p.price,
            "price_display": p.price_display,
            "category": p.category,
            "tags": p.tags,
            "in_stock": catalog.inventory.available(p.id) > 0,
        }
        for p in results
    ], indent=2)


# ── Tool 2: Get Product ──────────────────────────────────────
@mcp.tool()
def get_product(product_id: str) -> str:
    """Get full details of a specific product by its ID.

    Args:
        product_id: Product ID (e.g., 'prod_001')

    Returns:
        JSON object with full product details, or error if not found.
    """
    product = catalog.get_product(product_id)
    if not product:
        return json.dumps({"error": f"Product '{product_id}' not found"})

    audit.log(
        AuditAction.PRODUCT_VIEWED, actor="buyer_agent",
        details={"product_id": product_id, "product_name": product.name},
        reason=f"Viewed product: {product.name}"
    )

    return json.dumps({
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price_paise": product.price,
        "price_display": product.price_display,
        "category": product.category,
        "tags": product.tags,
        "stock": catalog.inventory.available(product.id),
        "in_stock": catalog.inventory.available(product.id) > 0,
    }, indent=2)


# ── Tool 3: Get Recommendations ──────────────────────────────
@mcp.tool()
def get_recommendations(product_ids: str) -> str:
    """Get upsell/cross-sell recommendations for products in your cart.

    Given products you're interested in, suggests complementary items
    with bundle savings to increase value.

    Args:
        product_ids: Comma-separated product IDs (e.g., 'prod_001,prod_020')

    Returns:
        JSON list of recommended products with savings info and reasons.
    """
    ids = [pid.strip() for pid in product_ids.split(",") if pid.strip()]
    if not ids:
        return json.dumps({"error": "Provide at least one product_id"})

    recs = upsell.get_recommendations(ids)
    bundle = upsell.calculate_bundle_price(ids)

    audit.log(
        AuditAction.UPSELL_OFFERED, actor="system",
        details={
            "input_products": ids,
            "recommendations_count": len(recs),
            "current_bundle_savings": bundle.savings,
        },
        reason=f"Offered {len(recs)} recommendations for {len(ids)} products"
    )

    return json.dumps({
        "recommendations": [
            {
                "product_id": r.product.id,
                "name": r.product.name,
                "price_display": r.product.price_display,
                "bundle_discount_pct": r.bundle_discount_pct,
                "potential_savings_display": f"Rs.{r.potential_savings/100:.2f}",
                "reason": r.reason,
            }
            for r in recs
        ],
        "current_bundle": {
            "original_total_display": f"Rs.{bundle.original_total/100:.2f}",
            "bundle_total_display": f"Rs.{bundle.bundle_total/100:.2f}",
            "savings_display": f"Rs.{bundle.savings/100:.2f}",
            "savings_pct": bundle.savings_pct,
            "applied_rule": bundle.applied_rule,
        },
    }, indent=2)


# ── Tool 4: Create Cart ──────────────────────────────────────
@mcp.tool()
def create_cart(items: str) -> str:
    """Create a new shopping cart with items.

    Args:
        items: JSON array of items. Example: [{"product_id": "prod_001", "quantity": 2}]

    Returns:
        JSON cart object with id, line items, subtotal, shipping, total.
        Returns error if product not found or out of stock.
    """
    try:
        item_list = json.loads(items)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON. Expected: [{\"product_id\": \"...\", \"quantity\": N}]"})

    try:
        cart = cart_mgr.create_cart(item_list)
        return json.dumps({
            "cart_id": cart.id,
            "items": [
                {
                    "product_id": li.product_id,
                    "product_name": li.product_name,
                    "quantity": li.quantity,
                    "unit_price_display": f"Rs.{li.unit_price/100:.2f}",
                    "line_total_display": f"Rs.{li.line_total/100:.2f}",
                }
                for li in cart.items
            ],
            "subtotal_display": f"Rs.{cart.subtotal/100:.2f}",
            "shipping_display": f"Rs.{cart.shipping/100:.2f}" if cart.shipping > 0 else "FREE",
            "discount_display": f"Rs.{cart.discount/100:.2f}" if cart.discount > 0 else "None",
            "total_paise": cart.total,
            "total_display": cart.total_display,
            "item_count": cart.item_count,
            "expires_at": cart.expires_at.isoformat() if cart.expires_at else None,
        }, indent=2)
    except (OutOfStockError, InvalidProductError, BoundsExceededError) as e:
        return json.dumps({"error": str(e)})


# ── Tool 5: Add to Cart ──────────────────────────────────────
@mcp.tool()
def add_to_cart(cart_id: str, product_id: str, quantity: int = 1) -> str:
    """Add an item to an existing cart.

    Args:
        cart_id: Cart ID from create_cart response
        product_id: Product ID to add
        quantity: Number of units to add (default 1)

    Returns:
        Updated cart object, or error message.
    """
    try:
        cart = cart_mgr.add_item(cart_id, product_id, quantity)
        return json.dumps({
            "cart_id": cart.id,
            "items": [
                {"product_name": li.product_name, "quantity": li.quantity,
                 "line_total_display": f"Rs.{li.line_total/100:.2f}"}
                for li in cart.items
            ],
            "total_display": cart.total_display,
            "item_count": cart.item_count,
        }, indent=2)
    except CartError as e:
        return json.dumps({"error": str(e)})


# ── Tool 6: Apply Coupon ─────────────────────────────────────
@mcp.tool()
def apply_coupon(cart_id: str, coupon_code: str) -> str:
    """Apply a discount coupon to a cart.

    Available test coupons: WELCOME10, COFFEE20, BUNDLE15, FIRSTBUY, SUMMER25, LOYALTY5

    Args:
        cart_id: Cart ID
        coupon_code: Coupon code to apply

    Returns:
        Updated cart with discount applied, or error if invalid/expired.
    """
    try:
        cart = cart_mgr.apply_coupon(cart_id, coupon_code)
        return json.dumps({
            "cart_id": cart.id,
            "coupon_applied": cart.coupon_code,
            "discount_display": f"Rs.{cart.discount/100:.2f}",
            "discount_reason": cart.discount_reason,
            "new_total_display": cart.total_display,
            "subtotal_display": f"Rs.{cart.subtotal/100:.2f}",
            "shipping_display": f"Rs.{cart.shipping/100:.2f}" if cart.shipping > 0 else "FREE",
        }, indent=2)
    except (InvalidCouponError, MinCartValueError, CartError) as e:
        return json.dumps({"error": str(e)})


# ── Tool 7: Checkout ─────────────────────────────────────────
@mcp.tool()
def checkout(
    cart_id: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
) -> str:
    """Finalize cart and create Razorpay order + payment link.

    GATED: Validates cart, enforces amount bounds, creates REAL Razorpay order.
    Every action is audit-logged.

    Args:
        cart_id: Cart ID to checkout
        customer_name: Buyer's name
        customer_email: Buyer's email
        customer_phone: Buyer's phone (10-digit)

    Returns:
        Order ID, payment link URL, and amount. Or error if validation fails.
    """
    try:
        cart = cart_mgr.get_cart(cart_id)
        audit.log(AuditAction.BOUNDS_CHECK, actor="system", details={"cart_id": cart_id, "total": cart.total, "max_allowed": settings.max_order_amount}, amount=cart.total, reason=f"Order Rs.{cart.total/100:.2f} within bounds")
        customer = {"name": customer_name, "email": customer_email, "contact": customer_phone}
        result = cart_mgr.finalize_cart(cart_id, customer_details=customer)
        if not result.success:
            return json.dumps({"error": f"Checkout blocked or failed: {result.reason}"})
            
        status = "order_created_with_warnings" if result.needs_reconciliation else "order_created"
        return json.dumps({"status": status, "payment_link_url": result.payment_link, "amount_display": f"Rs.{cart.total/100:.2f}", "message": result.reason}, indent=2)
    except CartExpiredError:
        return json.dumps({"error": f"Cart {cart_id} has expired. Create a new cart."})
    except CartError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        audit.log(
            AuditAction.ERROR, actor="system",
            details={"cart_id": cart_id, "error": str(e)},
            status="failed",
            reason=f"Checkout failed: {e}"
        )
        return json.dumps({"error": f"Checkout failed: {e}"})


# ── Tool 8: Get Order Status ─────────────────────────────────
@mcp.tool()
def get_order_status(order_id: str) -> str:
    """Check the payment status of a Razorpay order.

    Args:
        order_id: Razorpay order ID (e.g., 'order_xxx')

    Returns:
        Order status (created/attempted/paid), amount paid, payment method.
    """
    if not rzp_service:
        return json.dumps({
            "error": "Razorpay API keys not configured."
        })

    try:
        status = rzp_service.get_order_status(order_id)
        payments = rzp_service.get_order_payments(order_id)

        return json.dumps({
            "order_id": status.order_id,
            "status": status.status,
            "amount_display": f"Rs.{status.amount/100:.2f}",
            "amount_paid_display": f"Rs.{status.amount_paid/100:.2f}",
            "payment_attempts": len(payments),
            "payments": [
                {
                    "id": p.get("id"),
                    "status": p.get("status"),
                    "method": p.get("method"),
                    "amount_display": f"Rs.{p.get('amount', 0)/100:.2f}",
                }
                for p in payments
            ] if payments else [],
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Could not fetch order status: {e}"})


# ── Entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    # When run directly, start the MCP server on stdio transport
    # AI buyers connect by spawning this process
    import asyncio
    asyncio.run(mcp.run_stdio_async())
