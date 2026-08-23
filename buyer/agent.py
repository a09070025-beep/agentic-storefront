"""
Agentic Storefront — AI Buyer Agent
Deterministic buyer that executes purchase scenarios through the MCP server tools.
Computes AOV uplift, conversion rate, and other metrics from real output.
"""

import json
import sys
import time

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.models import AuditAction, BatchResult, ScenarioResult
from src.catalog import CatalogStore
from src.upsell_engine import UpsellEngine
from src.cart_manager import (
    CartManager, OutOfStockError, InvalidProductError,
    InvalidCouponError, MinCartValueError, BoundsExceededError,
)
from src.audit_logger import AuditLogger
from src.razorpay_service import RazorpayService
from config import get_settings, get_razorpay_client
from buyer.scenarios import get_scenarios, PurchaseScenario


class AgenticBuyer:
    """Deterministic AI buyer that executes purchase flows.

    Calls the same business logic the MCP server uses, but directly
    (not via MCP transport) for reliable batch testing.
    """

    def __init__(self, use_razorpay: bool = False, verbose: bool = True):
        self.settings = get_settings()
        self.audit = AuditLogger(output_path=self.settings.audit_output_path)
        self.audit.clear()
        self.catalog = CatalogStore(catalog_path=self.settings.catalog_path)
        self.upsell = UpsellEngine(self.catalog, rules_path=self.settings.bundle_rules_path)
        self.cart_mgr = CartManager(
            self.catalog, self.upsell, self.audit, self.settings,
        )
        self.rzp_service = None
        self.use_razorpay = use_razorpay
        self.verbose = verbose
        self.console = Console(force_terminal=True)

        if use_razorpay:
            try:
                client = get_razorpay_client(self.settings)
                self.rzp_service = RazorpayService(
                    client=client, audit=self.audit, settings=self.settings,
                )
            except ValueError:
                self.console.print(
                    "[yellow]Razorpay keys not set — checkout will simulate order creation[/yellow]"
                )
                self.use_razorpay = False

    def run_scenario(self, scenario: PurchaseScenario) -> ScenarioResult:
        """Execute a single purchase scenario end-to-end."""
        result = ScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            outcome="pending",
        )

        try:
            # Step 1: Search catalog
            search_results = self.catalog.search(
                scenario.search_query,
                category=scenario.search_filters.get("category"),
                max_price=scenario.search_filters.get("max_price"),
            )

            if not search_results:
                result.outcome = "failed_unexpected"
                result.error_message = f"No products found for '{scenario.search_query}'"
                return result

            self.audit.log(
                AuditAction.CATALOG_SEARCH, actor="buyer_agent",
                details={"query": scenario.search_query, "results": len(search_results)},
                reason=f"[{scenario.id}] Searched '{scenario.search_query}' — {len(search_results)} results"
            )

            # Step 2: Select product
            idx = min(scenario.select_product_index, len(search_results) - 1)
            selected_product = search_results[idx]

            # Build item list
            items = [{"product_id": selected_product.id, "quantity": 1}]
            base_value = selected_product.price

            # Add any additional products
            for pid in scenario.additional_product_ids:
                product = self.catalog.get_product(pid)
                if product and product.stock > 0:
                    items.append({"product_id": pid, "quantity": 1})
                    base_value += product.price

            result.cart_value_without_upsell = base_value

            # Step 3: Get recommendations
            product_ids = [item["product_id"] for item in items]
            recs = self.upsell.get_recommendations(product_ids)

            self.audit.log(
                AuditAction.UPSELL_OFFERED, actor="system",
                details={"products": product_ids, "recommendations": len(recs)},
                reason=f"[{scenario.id}] Offered {len(recs)} recommendations"
            )

            # Step 4: Accept or decline upsell
            upsell_value = 0
            if scenario.accept_upsell and recs:
                # Accept first recommendation
                rec = recs[0]
                items.append({"product_id": rec.product.id, "quantity": 1})
                upsell_value = rec.product.price

                self.audit.log(
                    AuditAction.UPSELL_ACCEPTED, actor="buyer_agent",
                    details={"product": rec.product.name, "savings": rec.potential_savings},
                    reason=f"[{scenario.id}] Accepted upsell: {rec.product.name}"
                )
            elif recs:
                self.audit.log(
                    AuditAction.UPSELL_DECLINED, actor="buyer_agent",
                    details={"recommendations_declined": len(recs)},
                    reason=f"[{scenario.id}] Declined {len(recs)} recommendations"
                )

            result.cart_value_with_upsell = base_value + upsell_value

            # Step 5: Create cart
            cart = self.cart_mgr.create_cart(items)

            # Step 6: Apply coupon if specified
            if scenario.coupon_code:
                cart = self.cart_mgr.apply_coupon(cart.id, scenario.coupon_code)

            # Step 7: Checkout
            if self.use_razorpay and self.rzp_service:
                # Real Razorpay API call
                self.cart_mgr.finalize_cart(cart.id)

                self.audit.log(
                    AuditAction.BOUNDS_CHECK, actor="system",
                    details={"cart_id": cart.id, "total": cart.total},
                    amount=cart.total,
                    reason=f"[{scenario.id}] Order Rs.{cart.total/100:.2f} within bounds"
                )

                order_result = self.rzp_service.create_order_with_payment_link(
                    amount=cart.total, currency="INR",
                    description=f"Scenario {scenario.id}: {scenario.name}",
                    customer={
                        "name": scenario.customer.name,
                        "email": scenario.customer.email,
                        "contact": scenario.customer.phone,
                    },
                    receipt=cart.id,
                    notes={"scenario": scenario.id},
                )
                result.razorpay_order_id = order_result.order_id
                result.payment_link_url = order_result.payment_link_url
                # Rate limit: Razorpay test mode has API limits
                time.sleep(3)
            else:
                # Simulate checkout (no Razorpay keys)
                self.cart_mgr.finalize_cart(cart.id)
                self.audit.log(
                    AuditAction.ORDER_CREATED, actor="system",
                    details={"cart_id": cart.id, "total": cart.total, "simulated": True},
                    amount=cart.total,
                    reason=f"[{scenario.id}] Simulated order for Rs.{cart.total/100:.2f}"
                )
                result.razorpay_order_id = f"sim_order_{scenario.id}"

            # Calculate AOV uplift
            if result.cart_value_without_upsell > 0:
                result.aov_uplift_pct = (
                    (result.cart_value_with_upsell - result.cart_value_without_upsell)
                    / result.cart_value_without_upsell * 100
                )

            result.outcome = "success"

        except OutOfStockError as e:
            result.outcome = "failed_expected" if scenario.expected_outcome == "out_of_stock" else "failed_unexpected"
            result.error_message = str(e)

        except (InvalidCouponError, MinCartValueError) as e:
            result.outcome = "failed_expected" if scenario.expected_outcome == "invalid_coupon" else "failed_unexpected"
            result.error_message = str(e)

        except BoundsExceededError as e:
            result.outcome = "failed_expected" if scenario.expected_outcome == "bounds_exceeded" else "failed_unexpected"
            result.error_message = str(e)

        except Exception as e:
            result.outcome = "failed_unexpected"
            result.error_message = str(e)

        result.audit_entry_count = self.audit.entry_count
        return result

    def run_batch(self, scenarios: list[PurchaseScenario] | None = None) -> BatchResult:
        """Run all scenarios and compute aggregate metrics."""
        if scenarios is None:
            scenarios = get_scenarios()

        results: list[ScenarioResult] = []

        self.console.print(f"\n[bold blue]Running {len(scenarios)} scenarios...[/bold blue]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Processing...", total=len(scenarios))

            for scenario in scenarios:
                progress.update(task, description=f"[cyan]{scenario.id}[/cyan]: {scenario.name}")

                # Reload catalog for each scenario to reset stock
                self.catalog = CatalogStore(catalog_path=self.settings.catalog_path)
                self.upsell = UpsellEngine(self.catalog, rules_path=self.settings.bundle_rules_path)
                self.cart_mgr = CartManager(
                    self.catalog, self.upsell, self.audit, self.settings,
                )

                result = self.run_scenario(scenario)
                results.append(result)
                progress.advance(task)

        # Compute batch metrics
        successful = [r for r in results if r.outcome == "success"]
        failed_expected = [r for r in results if r.outcome == "failed_expected"]
        failed_unexpected = [r for r in results if r.outcome == "failed_unexpected"]

        # AOV calculations — only from successful scenarios
        with_upsell = [r for r in successful if r.aov_uplift_pct > 0]
        without_upsell = [r for r in successful if r.aov_uplift_pct == 0]

        avg_without = (
            sum(r.cart_value_without_upsell for r in successful) / len(successful)
            if successful else 0
        )
        avg_with = (
            sum(r.cart_value_with_upsell for r in successful) / len(successful)
            if successful else 0
        )
        aov_uplift = (
            (avg_with - avg_without) / avg_without * 100
            if avg_without > 0 else 0
        )

        total_gmv = sum(r.cart_value_with_upsell for r in successful)

        # Upsell acceptance rate
        upsell_scenarios = [s for s in scenarios if s.accept_upsell and s.expected_outcome == "success"]
        upsell_accepted = [r for r in results if r.aov_uplift_pct > 0]
        upsell_rate = (
            len(upsell_accepted) / len(upsell_scenarios) * 100
            if upsell_scenarios else 0
        )

        # Conversion rate
        total_carts = len(successful) + len(failed_unexpected)
        conversion = (
            len(successful) / total_carts * 100
            if total_carts > 0 else 0
        )

        batch = BatchResult(
            total_scenarios=len(results),
            successful=len(successful),
            failed_expected=len(failed_expected),
            failed_unexpected=len(failed_unexpected),
            avg_aov_without_upsell=avg_without,
            avg_aov_with_upsell=avg_with,
            aov_uplift_pct=round(aov_uplift, 2),
            total_gmv=total_gmv,
            conversion_rate=round(conversion, 2),
            upsell_acceptance_rate=round(upsell_rate, 2),
            scenario_results=results,
        )

        self._print_results(batch, results)
        return batch

    def _print_results(self, batch: BatchResult, results: list[ScenarioResult]) -> None:
        """Print formatted batch results."""

        # Summary table
        self.console.print("\n[bold]BATCH RESULTS[/bold]")
        summary = Table(title="Summary")
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="bold green", justify="right")

        summary.add_row("Total Scenarios", str(batch.total_scenarios))
        summary.add_row("Successful", f"[green]{batch.successful}[/green]")
        summary.add_row("Failed (Expected)", f"[yellow]{batch.failed_expected}[/yellow]")
        summary.add_row("Failed (Unexpected)", f"[red]{batch.failed_unexpected}[/red]")
        summary.add_row("", "")
        summary.add_row("Avg AOV (without upsell)", f"Rs.{batch.avg_aov_without_upsell/100:,.2f}")
        summary.add_row("Avg AOV (with upsell)", f"Rs.{batch.avg_aov_with_upsell/100:,.2f}")
        summary.add_row("AOV Uplift", f"[bold]{batch.aov_uplift_pct:.1f}%[/bold]")
        summary.add_row("", "")
        summary.add_row("Total GMV", f"Rs.{batch.total_gmv/100:,.2f}")
        summary.add_row("Conversion Rate", f"{batch.conversion_rate:.1f}%")
        summary.add_row("Upsell Acceptance Rate", f"{batch.upsell_acceptance_rate:.1f}%")
        summary.add_row("Audit Trail Entries", str(self.audit.entry_count))

        self.console.print(summary)

        # Failed scenarios detail
        failures = [r for r in results if r.outcome == "failed_unexpected"]
        if failures:
            self.console.print("\n[bold red]UNEXPECTED FAILURES:[/bold red]")
            for f in failures:
                self.console.print(f"  {f.scenario_id}: {f.scenario_name}")
                self.console.print(f"    Error: {f.error_message}")

        # Expected failures (honest reporting)
        expected = [r for r in results if r.outcome == "failed_expected"]
        if expected:
            self.console.print("\n[bold yellow]HANDLED FAILURES (expected):[/bold yellow]")
            for f in expected:
                self.console.print(f"  {f.scenario_id}: {f.scenario_name}")
                self.console.print(f"    Handled: {f.error_message}")

        # Export metrics
        self._export_metrics(batch)

    def _export_metrics(self, batch: BatchResult) -> None:
        """Export metrics to JSON file."""
        import json
        from pathlib import Path

        output = {
            "summary": {
                "total_scenarios": batch.total_scenarios,
                "successful": batch.successful,
                "failed_expected": batch.failed_expected,
                "failed_unexpected": batch.failed_unexpected,
                "avg_aov_without_upsell_paise": batch.avg_aov_without_upsell,
                "avg_aov_with_upsell_paise": batch.avg_aov_with_upsell,
                "aov_uplift_pct": batch.aov_uplift_pct,
                "total_gmv_paise": batch.total_gmv,
                "total_gmv_display": f"Rs.{batch.total_gmv/100:,.2f}",
                "conversion_rate_pct": batch.conversion_rate,
                "upsell_acceptance_rate_pct": batch.upsell_acceptance_rate,
            },
            "scenarios": [
                {
                    "id": r.scenario_id,
                    "name": r.scenario_name,
                    "outcome": r.outcome,
                    "cart_without_upsell": r.cart_value_without_upsell,
                    "cart_with_upsell": r.cart_value_with_upsell,
                    "aov_uplift_pct": r.aov_uplift_pct,
                    "order_id": r.razorpay_order_id,
                    "error": r.error_message,
                }
                for r in batch.scenario_results
            ],
        }

        path = Path("output/metrics_report.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

        self.console.print(f"\n[dim]Metrics exported to: {path}[/dim]")

        # Also export audit trail
        audit_path = self.audit.export_json("output/audit_trail.json")
        self.console.print(f"[dim]Audit trail exported to: {audit_path}[/dim]")


# --- Quick self-test ---
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    buyer = AgenticBuyer(use_razorpay=False, verbose=True)
    batch = buyer.run_batch()
