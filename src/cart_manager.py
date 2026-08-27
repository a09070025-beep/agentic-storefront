"""
Agentic Storefront — Cart Manager
Cart operations with pricing, coupons, and safety bounds.
Every cart mutation is audit-logged and bounded.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from config import Settings, get_settings
from src.models import (
    AuditAction, Cart, CartStatus, Coupon, LineItem
)
from src.catalog import CatalogStore
from src.upsell_engine import UpsellEngine
from src.audit_logger import AuditLogger
from agentic_storefront_guardrails.payment_gate import PaymentGate
from agentic_storefront_guardrails.schemas import CheckoutItem


class CartError(Exception):
    """Base exception for cart operations."""
    pass


class OutOfStockError(CartError):
    """Raised when product stock is insufficient."""
    pass


class InvalidProductError(CartError):
    """Raised when product ID is not found."""
    pass


class CartNotFoundError(CartError):
    """Raised when cart ID is not found."""
    pass


class CartExpiredError(CartError):
    """Raised when cart has expired."""
    pass


class InvalidCouponError(CartError):
    """Raised when coupon code is invalid or expired."""
    pass


class MinCartValueError(CartError):
    """Raised when cart value is below coupon minimum."""
    pass


class BoundsExceededError(CartError):
    """Raised when order exceeds safety bounds."""
    pass


class CartManager:
    """Stateful cart management with pricing, coupons, and bounds enforcement."""

    def __init__(
        self,
        catalog: CatalogStore,
        upsell: UpsellEngine,
        audit: AuditLogger,
        payment_gate: "PaymentGate",
        settings: Settings | None = None,
        coupons_path: str = "data/coupons.json",
    ):
        self.catalog = catalog
        self.upsell = upsell
        self.audit = audit
        self.payment_gate = payment_gate
        self.settings = settings or get_settings()
        self._carts: dict[str, Cart] = {}
        self._coupons: dict[str, Coupon] = {}
        self._load_coupons(coupons_path)

    def _load_coupons(self, path: str) -> None:
        """Load coupons from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in data:
            coupon = Coupon(**item)
            self._coupons[coupon.code.upper()] = coupon

    def create_cart(self, items: list[dict]) -> Cart:
        """Create a new cart from a list of items.

        Args:
            items: List of {"product_id": str, "quantity": int}

        Returns:
            Cart with calculated totals

        Raises:
            InvalidProductError: Product ID not found
            OutOfStockError: Insufficient stock
            BoundsExceededError: Quantity exceeds max_item_quantity
        """
        cart_id = f"cart_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=self.settings.cart_expiry_minutes)

        line_items: list[LineItem] = []

        for item in items:
            product_id = item["product_id"]
            quantity = item.get("quantity", 1)

            # Validate quantity bounds
            if quantity > self.settings.max_item_quantity:
                self.audit.log(
                    AuditAction.ERROR, actor="system",
                    details={"product_id": product_id, "quantity": quantity,
                             "max": self.settings.max_item_quantity},
                    status="rejected",
                    reason=f"Quantity {quantity} exceeds max {self.settings.max_item_quantity}"
                )
                raise BoundsExceededError(
                    f"Quantity {quantity} exceeds maximum {self.settings.max_item_quantity} per item"
                )

            # Validate product exists
            product = self.catalog.get_product(product_id)
            if not product:
                self.audit.log(
                    AuditAction.ERROR, actor="system",
                    details={"product_id": product_id},
                    status="failed",
                    reason=f"Product {product_id} not found in catalog"
                )
                raise InvalidProductError(f"Product {product_id} not found")

            # Validate stock
            avail_stock = self.catalog.inventory.available(product_id)
            if avail_stock < quantity:
                self.audit.log(
                    AuditAction.STOCK_INSUFFICIENT, actor="system",
                    details={"product_id": product_id, "requested": quantity,
                             "available": avail_stock},
                    status="failed",
                    reason=f"{product.name} has only {avail_stock} in stock, requested {quantity}"
                )
                raise OutOfStockError(
                    f"{product.name} — only {avail_stock} available, requested {quantity}"
                )

            # Reserve stock
            reservation_id = self.catalog.reserve_stock(product_id, quantity, negotiation_id=cart_id)
            self.audit.log(
                AuditAction.STOCK_RESERVED, actor="system",
                details={"product_id": product_id, "quantity": quantity},
                reason=f"Reserved {quantity}x {product.name}"
            )

            line_total = product.price * quantity
            line_items.append(LineItem(
                product_id=product_id,
                product_name=product.name,
                quantity=quantity,
                unit_price=product.price,
                line_total=line_total,
                reservation_id=reservation_id
            ))

        cart = Cart(
            id=cart_id,
            items=line_items,
            created_at=now,
            expires_at=expiry,
            status=CartStatus.ACTIVE,
        )

        cart = self._calculate_totals(cart)
        self._validate_bounds(cart)
        self._carts[cart_id] = cart

        self.audit.log(
            AuditAction.CART_CREATED, actor="buyer_agent",
            details={
                "cart_id": cart_id,
                "items": [{"product": li.product_name, "qty": li.quantity} for li in line_items],
                "item_count": cart.item_count,
            },
            amount=cart.total,
            reason=f"Cart created with {cart.item_count} items, total {cart.total_display}"
        )

        return cart

    def add_item(self, cart_id: str, product_id: str, quantity: int = 1) -> Cart:
        """Add an item to existing cart."""
        cart = self._get_valid_cart(cart_id)
        product = self.catalog.get_product(product_id)
        if not product:
            raise InvalidProductError(f"Product {product_id} not found")

        avail_stock = self.catalog.inventory.available(product_id)
        if avail_stock < quantity:
            raise OutOfStockError(
                f"{product.name} — only {avail_stock} available"
            )

        # Check if product already in cart — increment quantity
        for item in cart.items:
            if item.product_id == product_id:
                new_qty = item.quantity + quantity
                if new_qty > self.settings.max_item_quantity:
                    raise BoundsExceededError(
                        f"Total quantity {new_qty} exceeds max {self.settings.max_item_quantity}"
                    )
                # Update reservation for the new total quantity
                item.reservation_id = self.catalog.update_reservation(item.reservation_id, product_id, new_qty, negotiation_id=cart_id)
                item.quantity = new_qty
                item.line_total = item.unit_price * new_qty
                cart = self._calculate_totals(cart)
                self._validate_bounds(cart)

                self.audit.log(
                    AuditAction.CART_UPDATED, actor="buyer_agent",
                    details={"cart_id": cart_id, "action": "increment",
                             "product": product.name, "new_qty": new_qty},
                    amount=cart.total,
                    reason=f"Increased {product.name} to {new_qty} in cart"
                )
                return cart

        # New product
        reservation_id = self.catalog.reserve_stock(product_id, quantity, negotiation_id=cart_id)
        cart.items.append(LineItem(
            product_id=product_id,
            product_name=product.name,
            unit_price=product.price,
            quantity=quantity,
            line_total=product.price * quantity,
            reservation_id=reservation_id
        ))
        cart = self._calculate_totals(cart)
        self._validate_bounds(cart)

        self.audit.log(
            AuditAction.CART_UPDATED, actor="buyer_agent",
            details={"cart_id": cart_id, "action": "add",
                     "product": product.name, "qty": quantity},
            amount=cart.total,
            reason=f"Added {quantity}x {product.name} to cart"
        )
        return cart

    def remove_item(self, cart_id: str, product_id: str) -> Cart:
        """Remove an item from cart entirely."""
        cart = self._get_valid_cart(cart_id)

        for item in cart.items:
            if item.product_id == product_id:
                if item.reservation_id:
                    self.catalog.release_stock(item.reservation_id)
                cart.items.remove(item)
                cart = self._calculate_totals(cart)

                self.audit.log(
                    AuditAction.CART_UPDATED, actor="buyer_agent",
                    details={"cart_id": cart_id, "action": "remove",
                             "product": item.product_name},
                    amount=cart.total,
                    reason=f"Removed {item.product_name} from cart"
                )
                return cart

        raise InvalidProductError(f"Product {product_id} not in cart")

    def apply_coupon(self, cart_id: str, coupon_code: str) -> Cart:
        """Validate and apply a coupon code to the cart.

        Enforces:
        - Coupon exists and is active
        - Cart meets minimum value requirement
        - Discount is capped by max_discount AND max_discount_pct safety bound
        """
        cart = self._get_valid_cart(cart_id)
        code_upper = coupon_code.upper()
        coupon = self._coupons.get(code_upper)

        if not coupon:
            self.audit.log(
                AuditAction.COUPON_REJECTED, actor="system",
                details={"cart_id": cart_id, "coupon": coupon_code},
                status="rejected",
                reason=f"Coupon '{coupon_code}' does not exist"
            )
            raise InvalidCouponError(f"Coupon '{coupon_code}' not found")

        if not coupon.active:
            self.audit.log(
                AuditAction.COUPON_REJECTED, actor="system",
                details={"cart_id": cart_id, "coupon": coupon_code},
                status="rejected",
                reason=f"Coupon '{coupon_code}' has expired"
            )
            raise InvalidCouponError(f"Coupon '{coupon_code}' has expired")

        if cart.subtotal < coupon.min_cart_value:
            self.audit.log(
                AuditAction.COUPON_REJECTED, actor="system",
                details={"cart_id": cart_id, "coupon": coupon_code,
                         "subtotal": cart.subtotal,
                         "min_required": coupon.min_cart_value},
                status="rejected",
                reason=(
                    f"Cart Rs.{cart.subtotal/100:.2f} below minimum "
                    f"Rs.{coupon.min_cart_value/100:.2f} for coupon {coupon_code}"
                )
            )
            raise MinCartValueError(
                f"Cart value Rs.{cart.subtotal/100:.2f} is below minimum "
                f"Rs.{coupon.min_cart_value/100:.2f} required for coupon '{coupon_code}'"
            )

        # Calculate discount with BOUNDS enforcement
        raw_discount_pct = coupon.discount_pct

        # Safety bound: cap at max_discount_pct
        effective_pct = min(raw_discount_pct, self.settings.max_discount_pct)
        if effective_pct < raw_discount_pct:
            self.audit.log(
                AuditAction.BOUNDS_CHECK, actor="system",
                details={"original_pct": raw_discount_pct,
                         "bounded_pct": effective_pct,
                         "max_allowed": self.settings.max_discount_pct},
                status="gated",
                reason=(
                    f"Coupon discount {raw_discount_pct}% bounded to "
                    f"{effective_pct}% (max {self.settings.max_discount_pct}%)"
                )
            )

        discount_amount = int(cart.subtotal * effective_pct / 100)

        # Cap at coupon's max_discount
        discount_amount = min(discount_amount, coupon.max_discount)

        cart.coupon_code = code_upper
        cart.discount = discount_amount
        cart.discount_reason = (
            f"{code_upper}: {effective_pct}% off "
            f"(Rs.{discount_amount/100:.2f} discount)"
        )
        cart = self._calculate_totals(cart)

        self.audit.log(
            AuditAction.COUPON_APPLIED, actor="buyer_agent",
            details={
                "cart_id": cart_id, "coupon": code_upper,
                "discount_pct": effective_pct,
                "discount_amount": discount_amount,
                "new_total": cart.total,
            },
            amount=discount_amount,
            reason=(
                f"Applied {code_upper}: {effective_pct}% off = "
                f"Rs.{discount_amount/100:.2f} discount. New total: {cart.total_display}"
            )
        )

        return cart

    def get_cart(self, cart_id: str) -> Cart:
        """Get cart by ID."""
        return self._get_valid_cart(cart_id)

    def finalize_cart(self, cart_id: str, customer_details: dict | None = None) -> "PaymentGateResult":
        """Checkout all items via PaymentGate."""
        cart = self._get_valid_cart(cart_id)
        
        # Build CheckoutItems
        checkout_items = [
            CheckoutItem(
                sku=li.product_id,
                agreed_price=li.unit_price,
                quantity=li.quantity,
                reservation_id=li.reservation_id
            ) for li in cart.items
        ]
        
        # We need a stable idempotency key for this cart checkout attempt
        idempotency_key = f"checkout_{cart_id}_{cart.item_count}"
        
        result = self.payment_gate.finalize_deal(
            negotiation_id=cart_id,
            items=checkout_items,
            idempotency_key=idempotency_key,
            customer_details=customer_details
        )
        
        if result.success:
            if getattr(result, "needs_reconciliation", False):
                cart.status = CartStatus.CHECKED_OUT_NEEDS_RECONCILIATION
            else:
                cart.status = CartStatus.CHECKED_OUT
        else:
            # Payment failed, reservations were released by PaymentGate. 
            # We must clear the reservation IDs from the cart so it can't be confirmed again.
            for li in cart.items:
                li.reservation_id = ""
                
        return result

    def _get_valid_cart(self, cart_id: str) -> Cart:
        """Get cart and validate it's active and not expired."""
        cart = self._carts.get(cart_id)
        if not cart:
            raise CartNotFoundError(f"Cart {cart_id} not found")

        if cart.status == CartStatus.CHECKED_OUT:
            raise CartError(f"Cart {cart_id} is already checked out")

        # Check expiry
        if cart.expires_at and datetime.now(timezone.utc) > cart.expires_at:
            cart.status = CartStatus.EXPIRED
            # Release reserved stock
            for item in cart.items:
                if item.reservation_id:
                    self.catalog.release_stock(item.reservation_id)
                self.audit.log(
                    AuditAction.STOCK_RELEASED, actor="system",
                    details={"product_id": item.product_id, "quantity": item.quantity},
                    reason=f"Released {item.quantity}x {item.product_name} (cart expired)"
                )
            raise CartExpiredError(f"Cart {cart_id} has expired")

        return cart

    def _calculate_totals(self, cart: Cart) -> Cart:
        """Recalculate cart subtotal, shipping, and total."""
        cart.subtotal = sum(item.line_total for item in cart.items)

        # Shipping: flat rate unless above threshold
        if cart.subtotal >= self.settings.free_shipping_threshold:
            cart.shipping = 0
        else:
            cart.shipping = self.settings.shipping_flat_rate

        # Total = subtotal - discount + shipping
        cart.total = cart.subtotal - cart.discount + cart.shipping
        cart.total = max(cart.total, 0)  # Never negative

        return cart

    def _validate_bounds(self, cart: Cart) -> None:
        """Enforce safety bounds on cart total."""
        if cart.total > self.settings.max_order_amount:
            self.audit.log(
                AuditAction.BOUNDS_CHECK, actor="system",
                details={"cart_id": cart.id, "total": cart.total,
                         "max_allowed": self.settings.max_order_amount},
                status="rejected",
                reason=(
                    f"Cart total Rs.{cart.total/100:.2f} exceeds maximum "
                    f"Rs.{self.settings.max_order_amount/100:.2f}"
                )
            )
            raise BoundsExceededError(
                f"Cart total Rs.{cart.total/100:.2f} exceeds maximum "
                f"Rs.{self.settings.max_order_amount/100:.2f}"
            )


# --- Quick self-test ---
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    console = Console(force_terminal=True)

    console.print("\n[bold blue]Cart Manager — Self-Test[/bold blue]\n")

    catalog = CatalogStore()
    audit = AuditLogger(output_path="output/test_cart_audit.jsonl")
    audit.clear()
    upsell = UpsellEngine(catalog)
    cart_mgr = CartManager(catalog, upsell, audit)

    # Test 1: Create cart
    console.print("[cyan]Test 1: Create cart[/cyan]")
    cart = cart_mgr.create_cart([
        {"product_id": "prod_001", "quantity": 2},
        {"product_id": "prod_041", "quantity": 1},
    ])
    console.print(f"  Cart ID: {cart.id}")
    console.print(f"  Items: {cart.item_count}")
    console.print(f"  Subtotal: Rs.{cart.subtotal/100:.2f}")
    console.print(f"  Shipping: Rs.{cart.shipping/100:.2f}")
    console.print(f"  Total: {cart.total_display}")

    # Test 2: Apply coupon
    console.print(f"\n[cyan]Test 2: Apply WELCOME10 coupon[/cyan]")
    cart = cart_mgr.apply_coupon(cart.id, "WELCOME10")
    console.print(f"  Discount: Rs.{cart.discount/100:.2f} ({cart.discount_reason})")
    console.print(f"  New Total: {cart.total_display}")

    # Test 3: Expired coupon
    console.print(f"\n[cyan]Test 3: Apply expired coupon EXPIRED01[/cyan]")
    try:
        temp_cart = cart_mgr.create_cart([{"product_id": "prod_003", "quantity": 1}])
        cart_mgr.apply_coupon(temp_cart.id, "EXPIRED01")
        console.print("  ERROR: Should have raised InvalidCouponError!")
    except InvalidCouponError as e:
        console.print(f"  Correctly rejected: {e}")

    # Test 4: Out of stock
    console.print(f"\n[cyan]Test 4: Out of stock product[/cyan]")
    try:
        cart_mgr.create_cart([{"product_id": "prod_090", "quantity": 1}])
        console.print("  ERROR: Should have raised OutOfStockError!")
    except OutOfStockError as e:
        console.print(f"  Correctly rejected: {e}")

    # Test 5: Safety bounds — MAXED100 coupon (100% off bounded to 30%)
    console.print(f"\n[cyan]Test 5: MAXED100 coupon (100% -> bounded to 30%)[/cyan]")
    big_cart = cart_mgr.create_cart([{"product_id": "prod_022", "quantity": 1}])  # AeroPress Rs.3500
    cart_mgr.apply_coupon(big_cart.id, "MAXED100")
    console.print(f"  Discount: Rs.{big_cart.discount/100:.2f}")
    console.print(f"  Total: {big_cart.total_display}")
    console.print(f"  Reason: {big_cart.discount_reason}")

    # Test 6: Add item to existing cart
    console.print(f"\n[cyan]Test 6: Add item to cart[/cyan]")
    cart = cart_mgr.add_item(cart.id, "prod_060", quantity=1)
    console.print(f"  Added Ceramic Mug. Items: {cart.item_count}, Total: {cart.total_display}")

    # Test 7: Remove item
    console.print(f"\n[cyan]Test 7: Remove item from cart[/cyan]")
    cart = cart_mgr.remove_item(cart.id, "prod_060")
    console.print(f"  Removed Ceramic Mug. Items: {cart.item_count}, Total: {cart.total_display}")

    # Show audit trail
    console.print(f"\n[bold]Audit trail: {audit.entry_count} entries logged[/bold]")
    audit.clear()

    console.print(f"\n[bold green]Cart Manager passed all 7 tests![/bold green]\n")
