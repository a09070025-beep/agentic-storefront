"""
Agentic Storefront — Configuration
Loads environment variables and initializes the Razorpay client.
Single source of truth for all settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import razorpay


# Load .env from project root
_PROJECT_ROOT = Path(__file__).parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings(BaseModel):
    """Application settings with safety bounds."""

    # Razorpay credentials
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    razorpay_webhook_secret: str = Field(default="")

    # OSS API (for Buyer AI / open-source models)
    oss_api_key: str = Field(default="")
    oss_base_url: str = Field(default="")

    # Gemini API (for Merchant AI agents)
    gemini_api_key: str = Field(default="")

    # Safety bounds — every financial action is bounded
    max_order_amount: int = Field(
        default=5_000_000,
        description="Maximum order amount in paise (₹50,000)"
    )
    max_discount_pct: float = Field(
        default=30.0,
        description="Maximum discount percentage allowed"
    )
    max_item_quantity: int = Field(
        default=10,
        description="Maximum quantity per item in cart"
    )
    cart_expiry_minutes: int = Field(
        default=30,
        description="Cart expires after this many minutes"
    )
    shipping_flat_rate: int = Field(
        default=5000,
        description="Flat shipping rate in paise (₹50)"
    )
    free_shipping_threshold: int = Field(
        default=100_000,
        description="Free shipping above this amount in paise (₹1,000)"
    )

    # Paths
    catalog_path: str = Field(default="data/catalog.json")
    coupons_path: str = Field(default="data/coupons.json")
    bundle_rules_path: str = Field(default="data/bundle_rules.json")
    audit_output_path: str = Field(default="output/audit_trail.jsonl")


def get_settings() -> Settings:
    """Load settings from environment variables."""
    return Settings(
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", ""),
        razorpay_webhook_secret=os.getenv("RAZORPAY_WEBHOOK_SECRET", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        oss_api_key=os.getenv("OSS_API_KEY", ""),
        oss_base_url=os.getenv("OSS_BASE_URL", ""),
    )


def get_razorpay_client(settings: Settings | None = None) -> razorpay.Client:
    """Initialize and return a Razorpay client.

    Uses test-mode keys from environment.
    Raises ValueError if keys are not configured.
    """
    if settings is None:
        settings = get_settings()

    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise ValueError(
            "Razorpay API keys not configured. "
            "Copy .env.example to .env and add your test-mode keys. "
            "Get keys: https://razorpay.com → Dashboard → Test Mode → API Keys"
        )

    client = razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )
    return client


# --- Quick self-test ---
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()

    console.print("\n[bold blue]⚙️  Agentic Storefront — Configuration[/bold blue]\n")

    settings = get_settings()

    table = Table(title="Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Razorpay Key ID", settings.razorpay_key_id[:15] + "..." if len(settings.razorpay_key_id) > 15 else settings.razorpay_key_id or "[red]NOT SET[/red]")
    table.add_row("Razorpay Secret", "****" + settings.razorpay_key_secret[-4:] if len(settings.razorpay_key_secret) > 4 else "[red]NOT SET[/red]")
    table.add_row("Max Order Amount", f"₹{settings.max_order_amount / 100:,.2f}")
    table.add_row("Max Discount %", f"{settings.max_discount_pct}%")
    table.add_row("Max Item Quantity", str(settings.max_item_quantity))
    table.add_row("Cart Expiry", f"{settings.cart_expiry_minutes} minutes")
    table.add_row("Shipping Rate", f"₹{settings.shipping_flat_rate / 100:.2f}")
    table.add_row("Free Shipping Above", f"₹{settings.free_shipping_threshold / 100:,.2f}")

    console.print(table)

    # Test Razorpay client initialization
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        try:
            client = get_razorpay_client(settings)
            console.print("\n[bold green]✅ Razorpay client initialized successfully[/bold green]")
        except Exception as e:
            console.print(f"\n[bold red]❌ Razorpay client error: {e}[/bold red]")
    else:
        console.print("\n[yellow]⚠️  Razorpay keys not set — copy .env.example to .env and add your test keys[/yellow]")

    console.print("\n[bold green]✅ Config module loaded successfully[/bold green]\n")
