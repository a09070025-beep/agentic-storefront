"""
Agentic Storefront — Main Entry Point
Run modes:
  1. batch   — Run 55 scenarios, compute metrics (default)
  2. server  — Start MCP server on stdio
  3. demo    — Interactive demo showing end-to-end flow
"""

import sys
import asyncio

sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console(force_terminal=True)


def run_batch(use_razorpay: bool = False):
    """Run all 55 scenarios and print metrics."""
    from buyer.agent import AgenticBuyer

    console.print(Panel.fit(
        "[bold]AGENTIC STOREFRONT[/bold]\n"
        "AI-Powered Commerce with Razorpay\n\n"
        "Mode: [cyan]BATCH RUN[/cyan] — 55 scenarios",
        border_style="blue"
    ))

    buyer = AgenticBuyer(use_razorpay=use_razorpay)
    batch = buyer.run_batch()

    # Print verdict
    if batch.failed_unexpected == 0:
        console.print("\n[bold green]ALL SCENARIOS PASSED[/bold green]")
    else:
        console.print(f"\n[bold red]{batch.failed_unexpected} UNEXPECTED FAILURES[/bold red]")

    return batch


def run_server():
    """Start the MCP server on stdio transport."""
    console.print(Panel.fit(
        "[bold]AGENTIC STOREFRONT[/bold]\n"
        "MCP Server starting on stdio...\n\n"
        "Connect via MCP client (e.g., Claude Desktop)",
        border_style="green"
    ))

    from src.storefront_server import mcp
    asyncio.run(mcp.run_stdio_async())


def run_demo():
    """Interactive demo showing a single end-to-end purchase."""
    from config import get_settings
    from src.catalog import CatalogStore
    from src.upsell_engine import UpsellEngine
    from src.cart_manager import CartManager
    from agentic_storefront_guardrails.audit_log import AuditLog
    from src.models import AuditAction

    console.print(Panel.fit(
        "[bold]AGENTIC STOREFRONT[/bold]\n"
        "AI-Powered Commerce with Razorpay\n\n"
        "Mode: [cyan]INTERACTIVE DEMO[/cyan]",
        border_style="magenta"
    ))

    settings = get_settings()
    audit = AuditLog("data/pg_audit.sqlite3")
    audit.clear()
    catalog = CatalogStore()
    upsell_eng = UpsellEngine(catalog)
    cart_mgr = CartManager(catalog, upsell_eng, audit, settings)

    # Step 1: Search
    console.print("\n[bold cyan]Step 1: AI Buyer searches for 'dark roast coffee'[/bold cyan]")
    results = catalog.search("dark roast coffee", limit=5)

    table = Table(title="Search Results")
    table.add_column("#", style="dim")
    table.add_column("Product", style="cyan")
    table.add_column("Price", style="green", justify="right")
    table.add_column("Category")
    for i, p in enumerate(results):
        table.add_row(str(i + 1), p.name, p.price_display, p.category)
    console.print(table)
    audit.log(AuditAction.CATALOG_SEARCH, actor="buyer_agent",
              details={"query": "dark roast coffee", "results": len(results)},
              reason="Demo: Buyer searched for dark roast coffee")

    # Step 2: Select product
    selected = results[0]
    console.print(f"\n[bold cyan]Step 2: AI Buyer selects '{selected.name}' ({selected.price_display})[/bold cyan]")
    audit.log(AuditAction.PRODUCT_VIEWED, actor="buyer_agent",
              details={"product_id": selected.id},
              reason=f"Demo: Selected {selected.name}")

    # Step 3: Get recommendations
    console.print(f"\n[bold cyan]Step 3: Server offers upsell recommendations[/bold cyan]")
    recs = upsell_eng.get_recommendations([selected.id])
    rec_table = Table(title="Recommendations")
    rec_table.add_column("Product", style="cyan")
    rec_table.add_column("Price", style="green", justify="right")
    rec_table.add_column("Save", style="yellow", justify="right")
    rec_table.add_column("Reason")
    for r in recs:
        rec_table.add_row(r.product.name, r.product.price_display,
                          f"{r.bundle_discount_pct}%", r.reason[:40])
    console.print(rec_table)
    audit.log(AuditAction.UPSELL_OFFERED, actor="system",
              details={"recommendations": len(recs)},
              reason=f"Demo: Offered {len(recs)} recommendations")

    # Step 4: Accept first recommendation
    if recs:
        accepted = recs[0]
        console.print(f"\n[bold cyan]Step 4: AI Buyer accepts '{accepted.product.name}'[/bold cyan]")
        audit.log(AuditAction.UPSELL_ACCEPTED, actor="buyer_agent",
                  details={"product": accepted.product.name},
                  reason=f"Demo: Accepted upsell {accepted.product.name}")

        # Create cart with both items
        cart = cart_mgr.create_cart([
            {"product_id": selected.id, "quantity": 2},
            {"product_id": accepted.product.id, "quantity": 1},
        ])
    else:
        cart = cart_mgr.create_cart([{"product_id": selected.id, "quantity": 2}])

    console.print(f"\n[bold cyan]Step 5: Cart created[/bold cyan]")
    cart_table = Table(title=f"Cart ({cart.id})")
    cart_table.add_column("Item", style="cyan")
    cart_table.add_column("Qty", justify="center")
    cart_table.add_column("Total", style="green", justify="right")
    for li in cart.items:
        cart_table.add_row(li.product_name, str(li.quantity),
                           f"Rs.{li.line_total/100:.2f}")
    cart_table.add_row("", "", "")
    cart_table.add_row("[bold]Subtotal[/bold]", "", f"[bold]Rs.{cart.subtotal/100:.2f}[/bold]")
    if cart.shipping > 0:
        cart_table.add_row("Shipping", "", f"Rs.{cart.shipping/100:.2f}")
    else:
        cart_table.add_row("Shipping", "", "[green]FREE[/green]")
    cart_table.add_row("[bold]TOTAL[/bold]", "", f"[bold]{cart.total_display}[/bold]")
    console.print(cart_table)

    # Step 6: Apply coupon
    console.print(f"\n[bold cyan]Step 6: AI Buyer applies coupon 'WELCOME10'[/bold cyan]")
    cart = cart_mgr.apply_coupon(cart.id, "WELCOME10")
    console.print(f"  Discount: Rs.{cart.discount/100:.2f}")
    console.print(f"  Reason: {cart.discount_reason}")
    console.print(f"  New Total: [bold]{cart.total_display}[/bold]")

    # Step 7: Bounds check
    console.print(f"\n[bold cyan]Step 7: Safety bounds check[/bold cyan]")
    audit.log(AuditAction.BOUNDS_CHECK, actor="system",
              details={"total": cart.total, "max": settings.max_order_amount},
              amount=cart.total,
              reason=f"Demo: Rs.{cart.total/100:.2f} within bounds (max Rs.{settings.max_order_amount/100:.2f})")
    console.print(f"  Amount: Rs.{cart.total/100:.2f}")
    console.print(f"  Max Allowed: Rs.{settings.max_order_amount/100:.2f}")
    console.print(f"  [green]PASSED[/green]")

    # Step 8: Checkout
    console.print(f"\n[bold cyan]Step 8: Checkout[/bold cyan]")
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        from src.razorpay_service import RazorpayService
        from config import get_razorpay_client
        rzp = RazorpayService(client=get_razorpay_client(settings), audit=audit)
        cart_mgr.finalize_cart(cart.id)
        result = rzp.create_order_with_payment_link(
            amount=cart.total, currency="INR",
            description="Demo: Dark Roast + Grinder",
            customer={"name": "Demo Buyer", "email": "demo@test.com", "contact": "9123456780"},
            receipt=cart.id,
        )
        console.print(f"  Order ID: [bold]{result.order_id}[/bold]")
        console.print(f"  Payment Link: [bold]{result.payment_link_url}[/bold]")
        console.print(f"  Amount: Rs.{result.amount/100:.2f}")
    else:
        cart_mgr.finalize_cart(cart.id)
        audit.log(AuditAction.ORDER_CREATED, actor="system",
                  amount=cart.total,
                  details={"cart_id": cart.id, "simulated": True},
                  reason=f"Demo: Simulated order Rs.{cart.total/100:.2f}")
        console.print(f"  [yellow]Razorpay keys not set — showing simulated checkout[/yellow]")
        console.print(f"  Simulated Order ID: sim_order_demo")
        console.print(f"  Amount: Rs.{cart.total/100:.2f}")

    # Show audit trail
    console.print(f"\n[bold cyan]Audit Trail ({audit.entry_count} entries):[/bold cyan]")
    trail_table = Table()
    trail_table.add_column("Time", style="dim")
    trail_table.add_column("Action", style="cyan")
    trail_table.add_column("Actor")
    trail_table.add_column("Amount", justify="right")
    trail_table.add_column("Status")
    trail_table.add_column("Reason")
    for entry in audit.get_trail():
        amt = f"Rs.{entry.amount/100:.2f}" if entry.amount else "-"
        trail_table.add_row(
            entry.timestamp.strftime("%H:%M:%S"),
            entry.action.value,
            entry.actor,
            amt,
            entry.status,
            entry.reason[:50],
        )
    console.print(trail_table)

    audit.export_json("output/demo_audit.json")
    console.print(f"\n[bold green]Demo complete! Audit trail saved.[/bold green]\n")


def run_chart():
    """Generate AOV uplift & performance charts."""
    from generate_chart import (
        load_metrics, setup_style, CHARTS_DIR,
        chart_aov_comparison, chart_scenario_uplift,
        chart_upsell_acceptance, chart_gmv_breakdown, chart_dashboard,
    )

    console.print(Panel.fit(
        "[bold]AGENTIC STOREFRONT[/bold]\n"
        "Chart Generator\n\n"
        "Mode: [cyan]GENERATE CHARTS[/cyan]",
        border_style="yellow"
    ))

    setup_style()
    data = load_metrics()
    summary = data["summary"]
    scenarios = data["scenarios"]
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    charts = [
        chart_aov_comparison(summary),
        chart_scenario_uplift(scenarios),
        chart_upsell_acceptance(summary, scenarios),
        chart_gmv_breakdown(summary, scenarios),
        chart_dashboard(summary, scenarios),
    ]

    console.print(f"\n[bold green]✅ {len(charts)} charts saved to {CHARTS_DIR}/[/bold green]")
    for c in charts:
        console.print(f"  📊 {c.name}")
    console.print()


def run_negotiate():
    """Launch a live AI vs AI price negotiation."""
    from src.catalog import CatalogStore
    from src.buyer_ai import BuyerAI
    from src.merchant_ai import MerchantAI, load_cost_prices
    from src.negotiation_arena import NegotiationArena
    from agentic_storefront_guardrails.audit_log import AuditLog

    console.print(Panel.fit(
        "[bold]AGENTIC STOREFRONT[/bold]\n"
        "AI-Powered Commerce with Razorpay\n\n"
        "Mode: [cyan]LIVE AI NEGOTIATION[/cyan] — Buyer AI vs Merchant AI",
        border_style="magenta"
    ))

    # Load catalog and cost prices
    catalog = CatalogStore()
    cost_prices = load_cost_prices()

    # Pick products for the negotiation
    p1 = catalog.get_product("prod_002")  # Colombian Supremo Dark Roast ₹420
    p2 = catalog.get_product("prod_040")  # Hario V60 Paper Filters ₹150
    products = [p for p in [p1, p2] if p is not None]

    if not products:
        console.print("[bold red]Error: Could not load products from catalog.[/bold red]")
        return

    retail_price = sum(p.price for p in products)

    # Create Buyer AI — budget-conscious student
    buyer = BuyerAI(
        product_names=[p.name for p in products],
        retail_price=retail_price,
        persona={
            "name": "Arjun",
            "personality": "Budget-conscious college student and coffee enthusiast",
            "budget": 48000,  # ₹480 — below retail ₹570
            "shopping_list": [p.name for p in products],
        },
    )

    # Create Merchant AI — knows cost prices
    merchant = MerchantAI(products=products, cost_prices=cost_prices)

    # Create arena and run
    audit = AuditLog("data/pg_audit.sqlite3")
    audit.clear()

    arena = NegotiationArena(
        buyer=buyer,
        merchant=merchant,
        products=products,
        max_rounds=4,
        audit=audit,
    )

    result = arena.run()

    # Show audit summary
    console.print(f"\n[dim]Audit trail: {audit.entry_count} entries saved to output/negotiation_audit.jsonl[/dim]")
    audit.export_json("output/negotiation_audit.json")

    return result


def main():
    """Parse arguments and run appropriate mode."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "batch"
    use_razorpay = "--razorpay" in sys.argv or "--live" in sys.argv

    if mode == "server":
        run_server()
    elif mode == "demo":
        run_demo()
    elif mode == "batch":
        run_batch(use_razorpay=use_razorpay)
    elif mode == "chart":
        run_chart()
    elif mode == "negotiate":
        run_negotiate()
    else:
        console.print(f"[bold]Usage:[/bold]")
        console.print(f"  py main.py batch       — Run 55 scenarios + metrics (default)")
        console.print(f"  py main.py batch --live — Run with real Razorpay API calls")
        console.print(f"  py main.py server      — Start MCP server on stdio")
        console.print(f"  py main.py demo        — Interactive demo flow")
        console.print(f"  py main.py chart       — Generate AOV uplift charts")
        console.print(f"  py main.py negotiate   — 🤖 Live AI vs AI price negotiation")


if __name__ == "__main__":
    main()

