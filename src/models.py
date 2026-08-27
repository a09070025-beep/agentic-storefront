"""
Agentic Storefront — Data Models
All data structures using Pydantic v2 for validation and serialization.
Prices are in PAISE (₹1 = 100 paise) to avoid floating-point errors.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class CartStatus(str, Enum):
    ACTIVE = "active"
    CHECKED_OUT = "checked_out"
    CHECKED_OUT_NEEDS_RECONCILIATION = "checked_out_needs_reconciliation"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AuditAction(str, Enum):
    """All possible audit actions — every financial event is tracked."""
    CATALOG_SEARCH = "CATALOG_SEARCH"
    PRODUCT_VIEWED = "PRODUCT_VIEWED"
    UPSELL_OFFERED = "UPSELL_OFFERED"
    UPSELL_ACCEPTED = "UPSELL_ACCEPTED"
    UPSELL_DECLINED = "UPSELL_DECLINED"
    CART_CREATED = "CART_CREATED"
    CART_UPDATED = "CART_UPDATED"
    COUPON_APPLIED = "COUPON_APPLIED"
    COUPON_REJECTED = "COUPON_REJECTED"
    BOUNDS_CHECK = "BOUNDS_CHECK"
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_LINK_CREATED = "PAYMENT_LINK_CREATED"
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    ORDER_FULFILLED = "ORDER_FULFILLED"
    STOCK_RESERVED = "STOCK_RESERVED"
    STOCK_RELEASED = "STOCK_RELEASED"
    STOCK_INSUFFICIENT = "STOCK_INSUFFICIENT"
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"
    ERROR = "ERROR"
    # Negotiation events
    NEGOTIATION_STARTED = "NEGOTIATION_STARTED"
    NEGOTIATION_ROUND = "NEGOTIATION_ROUND"
    NEGOTIATION_AGREED = "NEGOTIATION_AGREED"
    NEGOTIATION_FAILED = "NEGOTIATION_FAILED"


# ──────────────────────────────────────────────
# Product & Catalog
# ──────────────────────────────────────────────

class Product(BaseModel):
    """A product in the merchant's catalog."""
    id: str
    name: str
    description: str
    price: int = Field(ge=0, description="Price in paise (₹350 = 35000)")
    category: str
    tags: list[str] = Field(default_factory=list)
    stock: int = Field(ge=0)
    stock_level: int | None = Field(
        default=None,
        description="Explicit stock level for scarcity signalling. Defaults to stock if not set."
    )
    active: bool = True

    def model_post_init(self, __context) -> None:
        """Auto-populate stock_level from stock if not explicitly set."""
        if self.stock_level is None:
            object.__setattr__(self, "stock_level", self.stock)

    @property
    def price_display(self) -> str:
        """Human-readable price string."""
        return f"₹{self.price / 100:,.2f}"

    @property
    def is_low_stock(self) -> bool:
        """True if stock_level is critically low (≤ 5)."""
        lvl = self.stock_level if self.stock_level is not None else self.stock
        return 0 < lvl <= 5

    @property
    def is_out_of_stock(self) -> bool:
        """True if stock_level is zero."""
        lvl = self.stock_level if self.stock_level is not None else self.stock
        return lvl == 0


# ──────────────────────────────────────────────
# Cart & Line Items
# ──────────────────────────────────────────────

class LineItem(BaseModel):
    """A single item in the cart."""
    product_id: str
    product_name: str
    quantity: int = Field(ge=1, le=10)
    unit_price: int = Field(ge=0, description="Price per unit in paise")
    line_total: int = Field(ge=0, description="quantity × unit_price in paise")
    reservation_id: str | None = None

    @field_validator("line_total", mode="before")
    @classmethod
    def compute_line_total(cls, v, info):
        """Auto-calculate line_total if not provided."""
        if v is None or v == 0:
            data = info.data
            return data.get("quantity", 0) * data.get("unit_price", 0)
        return v


class Cart(BaseModel):
    """Shopping cart with calculated totals."""
    id: str = Field(default_factory=lambda: f"cart_{uuid4().hex[:12]}")
    items: list[LineItem] = Field(default_factory=list)
    subtotal: int = Field(default=0, description="Sum of line_totals in paise")
    discount: int = Field(default=0, ge=0, description="Discount amount in paise")
    discount_reason: str = ""
    shipping: int = Field(default=0, ge=0, description="Shipping cost in paise")
    total: int = Field(default=0, description="subtotal - discount + shipping in paise")
    coupon_code: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    status: CartStatus = CartStatus.ACTIVE

    @property
    def total_display(self) -> str:
        return f"₹{self.total / 100:,.2f}"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)


# ──────────────────────────────────────────────
# Coupons
# ──────────────────────────────────────────────

class Coupon(BaseModel):
    """Discount coupon with validation rules."""
    code: str
    discount_pct: float = Field(ge=0, le=100)
    max_discount: int = Field(ge=0, description="Maximum discount in paise")
    min_cart_value: int = Field(ge=0, description="Minimum cart subtotal in paise")
    active: bool = True
    description: str = ""


# ──────────────────────────────────────────────
# Upsell / Bundle Rules
# ──────────────────────────────────────────────

class BundleRule(BaseModel):
    """Defines cross-sell / upsell associations."""
    id: str
    name: str
    trigger_products: list[str] = Field(
        description="Product IDs that trigger this bundle recommendation"
    )
    recommend_products: list[str] = Field(
        description="Product IDs to recommend when trigger products are in cart"
    )
    bundle_discount_pct: float = Field(
        ge=0, le=50,
        description="Discount % when all bundle items are bought together"
    )
    reason: str = Field(
        description="Human-readable reason for this recommendation"
    )


class Recommendation(BaseModel):
    """A single upsell/cross-sell recommendation."""
    product: Product
    bundle_discount_pct: float
    reason: str
    potential_savings: int = Field(
        ge=0, description="Savings in paise if bundle is accepted"
    )


class BundlePricing(BaseModel):
    """Pricing calculation for a bundle of products."""
    original_total: int
    bundle_total: int
    savings: int
    savings_pct: float
    applied_rule: str | None = None


# ──────────────────────────────────────────────
# Razorpay / Order
# ──────────────────────────────────────────────

class OrderResult(BaseModel):
    """Result of creating a Razorpay order + payment link."""
    order_id: str
    payment_link_id: str
    payment_link_url: str
    amount: int = Field(description="Amount in paise")
    currency: str = "INR"
    status: str = "created"
    cart_id: str
    receipt: str = ""


class PaymentStatus(BaseModel):
    """Status of a payment/order."""
    order_id: str
    status: str  # created, attempted, paid
    amount: int
    amount_paid: int
    currency: str = "INR"
    payment_id: str | None = None
    method: str | None = None  # card, upi, netbanking, etc.


# ──────────────────────────────────────────────
# Audit Trail
# ──────────────────────────────────────────────

class AuditEntry(BaseModel):
    """A single entry in the audit trail. Every financial action creates one."""
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    action: AuditAction
    actor: str = "system"  # "buyer_agent" or "system"
    details: dict = Field(default_factory=dict)
    amount: int | None = None  # paise, if financial
    status: str = "success"  # success, failed, gated, rejected
    reason: str = ""  # human-readable explanation of why this action happened


# ──────────────────────────────────────────────
# Buyer Scenarios (for batch testing)
# ──────────────────────────────────────────────

class CustomerInfo(BaseModel):
    """Customer details for checkout."""
    name: str
    email: str
    phone: str


class PurchaseScenario(BaseModel):
    """A single test scenario for the AI buyer."""
    id: str
    name: str
    search_query: str
    search_filters: dict = Field(default_factory=dict)
    select_product_index: int = 0
    additional_product_ids: list[str] = Field(default_factory=list)
    accept_upsell: bool = True
    coupon_code: str | None = None
    customer: CustomerInfo
    expected_outcome: Literal["success", "out_of_stock", "invalid_coupon", "bounds_exceeded"]


class ScenarioResult(BaseModel):
    """Result of running a single purchase scenario."""
    scenario_id: str
    scenario_name: str
    outcome: str  # success, failed_expected, failed_unexpected
    cart_value_without_upsell: int = 0  # paise
    cart_value_with_upsell: int = 0  # paise
    aov_uplift_pct: float = 0.0
    razorpay_order_id: str | None = None
    payment_link_url: str | None = None
    error_message: str | None = None
    audit_entry_count: int = 0


class BatchResult(BaseModel):
    """Aggregate metrics from running all scenarios."""
    total_scenarios: int
    successful: int
    failed_expected: int
    failed_unexpected: int
    avg_aov_without_upsell: float  # paise
    avg_aov_with_upsell: float  # paise
    aov_uplift_pct: float
    total_gmv: int  # paise — total order amounts
    conversion_rate: float  # successful / total
    upsell_acceptance_rate: float
    scenario_results: list[ScenarioResult] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Negotiation
# ──────────────────────────────────────────────

class NegotiationMessage(BaseModel):
    """A single message in a negotiation conversation."""
    role: str  # "buyer" or "merchant"
    message: str
    proposed_price: int | None = None  # paise
    accepted: bool = False
    walk_away: bool = False
    final_offer: bool = False


class NegotiationResult(BaseModel):
    """Outcome of an AI vs AI negotiation."""
    agreed: bool = False
    final_price: int = Field(default=0, description="Agreed price in paise (0 if no deal)")
    rounds: int = 0
    retail_price: int = Field(default=0, description="Original retail total in paise")
    buyer_budget: int = Field(default=0, description="Buyer's budget in paise")
    discount_pct: float = 0.0  # percentage discount from retail
    conversation: list[NegotiationMessage] = Field(default_factory=list)
    payment_link_url: str | None = None
    order_id: str | None = None
    products: list[str] = Field(default_factory=list)


# --- Quick self-test ---
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print("\n[bold blue]📋 Agentic Storefront — Models Self-Test[/bold blue]\n")

    # Test Product
    p = Product(
        id="prod_001", name="Dark Roast Coffee", description="Bold and rich",
        price=35000, category="coffee", tags=["dark", "arabica"], stock=50
    )
    console.print(f"✅ Product: {p.name} — {p.price_display}")

    # Test LineItem
    li = LineItem(
        product_id="prod_001", product_name="Dark Roast Coffee",
        quantity=2, unit_price=35000, line_total=70000
    )
    console.print(f"✅ LineItem: {li.product_name} x{li.quantity} = ₹{li.line_total / 100:.2f}")

    # Test Cart
    cart = Cart(items=[li], subtotal=70000, shipping=5000, total=75000)
    console.print(f"✅ Cart: {cart.id} — {cart.item_count} items — {cart.total_display}")

    # Test Coupon
    coupon = Coupon(
        code="WELCOME10", discount_pct=10.0,
        max_discount=10000, min_cart_value=50000
    )
    console.print(f"✅ Coupon: {coupon.code} — {coupon.discount_pct}% off (max ₹{coupon.max_discount / 100:.2f})")

    # Test BundleRule
    rule = BundleRule(
        id="bundle_001", name="Coffee Lovers",
        trigger_products=["prod_001"], recommend_products=["prod_010"],
        bundle_discount_pct=5.0, reason="Frequently bought together"
    )
    console.print(f"✅ BundleRule: {rule.name} — {rule.bundle_discount_pct}% off")

    # Test AuditEntry
    entry = AuditEntry(
        action=AuditAction.CART_CREATED, actor="buyer_agent",
        details={"cart_id": cart.id}, amount=75000,
        status="success", reason="Buyer created cart with 2 items"
    )
    console.print(f"✅ AuditEntry: {entry.action.value} — ₹{entry.amount / 100:.2f} — {entry.reason}")

    # Test OrderResult
    order = OrderResult(
        order_id="order_test123", payment_link_id="plink_test456",
        payment_link_url="https://rzp.io/i/test", amount=75000, cart_id=cart.id
    )
    console.print(f"✅ OrderResult: {order.order_id} — ₹{order.amount / 100:.2f} — {order.payment_link_url}")

    # Test Scenario
    scenario = PurchaseScenario(
        id="s001", name="Happy path",
        search_query="dark roast", select_product_index=0,
        accept_upsell=True,
        customer=CustomerInfo(name="Test User", email="test@example.com", phone="9999999999"),
        expected_outcome="success"
    )
    console.print(f"✅ Scenario: {scenario.name} — expected: {scenario.expected_outcome}")

    console.print(f"\n[bold green]✅ All {7} models created and validated successfully[/bold green]\n")
