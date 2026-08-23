"""
Agentic Storefront — Merchant AI Agent (v3: Smart Counter-Offer)
LLM-powered merchant with cost awareness, margin protection, AND bundle upsell intelligence.
If buyer bids below the absolute floor, the Merchant pivots to offering a bundle deal.
Uses Google Gemini (google-genai SDK) for natural language generation.
"""

import json
import re
import os
import time
import warnings
from google import genai
from google.genai import types

from config import get_settings
from src.models import Product, NegotiationMessage
from src.upsell_engine import UpsellEngine
from src.catalog import CatalogStore

# Suppress AFC warning (printed to stderr by google-genai SDK)
import sys as _sys
import io as _io
_original_stderr = _sys.stderr


def _gemini_call_with_retry(client, **kwargs):
    """Call Gemini API with retry on 503/429 errors. Parses retry delay from error."""
    import re as _re
    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            _sys.stderr = _io.StringIO()
            try:
                result = client.models.generate_content(**kwargs)
            finally:
                _sys.stderr = _original_stderr
            return result
        except Exception as e:
            _sys.stderr = _original_stderr
            err = str(e)
            err_lower = err.lower()
            retryable = any(x in err_lower for x in ["503", "unavailable", "429", "resource_exhausted", "overloaded", "quota", "timeout", "deadline"])
            if retryable and attempt < max_retries:
                delay_match = _re.search(r'retry\s*(?:in|after)\s*(\d+)', err_lower)
                if delay_match:
                    delay = int(delay_match.group(1)) + 5
                else:
                    delay = 15 * (2 ** attempt)
                from rich import print as rprint
                rprint(f"  [dim]⏳ Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})...[/dim]",
                      flush=True)
                time.sleep(delay)
                continue
            raise


# ──────────────────────────────────────────────
# Cost Price Loader
# ──────────────────────────────────────────────

def load_cost_prices(path: str = "data/cost_prices.json") -> dict[str, int]:
    """Load cost prices from JSON. Returns {product_id: cost_paise}."""
    with open(path, "r") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ──────────────────────────────────────────────
# Dynamic Prompt Loader
# ──────────────────────────────────────────────

DEFAULT_PROMPT_PATH = "prompts/merchant_system.txt"


def load_merchant_prompt(path: str = DEFAULT_PROMPT_PATH) -> str:
    """Load merchant system prompt from file. Falls back to embedded default if file not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Embedded fallback (v1 — no emotion/scarcity)
        return """You are a charismatic premium coffee merchant and master salesman.

PRODUCTS BEING SOLD:
{product_details}

PRICING:
- Retail price: ₹{retail_price}
- Your cost: ₹{cost_price}
- Absolute floor (15% margin): ₹{floor_price}

NEGOTIATION RULES:
1. NEVER sell below ₹{floor_price}. This is non-negotiable.
2. Start at ₹{retail_price}. Give small concessions (₹20-40) only when pushed.
3. BUYER CEILING DETECTION: If the buyer says "my budget is X" and X >= floor, ACCEPT X immediately.
4. Keep messages to 2-3 sentences max. Be warm, confident, and professional.

SMART COUNTER-OFFER RULE (CRITICAL):
5. If buyer offers BELOW ₹{floor_price}, PIVOT to a BUNDLE UPSELL:
{bundle_context}

SCARCITY AWARENESS:
{scarcity_alerts}

INSTANT CLOSE RULE:
6. If buyer accepts or offers at/above retail, close IMMEDIATELY. Set accepted=true.

WALK AWAY RULE:
7. If buyer refuses floor AND rejects bundle, set walk_away=true.

Reply ONLY as JSON:
{{"message":"...","offered_price":NUMBER,"accepted":BOOL,"final_offer":BOOL,"walk_away":BOOL,"bundle_offer":STRING_OR_NULL,"buyer_emotion":STRING}}"""



class MerchantAI:
    """LLM-powered merchant agent with cost awareness, margin protection, upsell intelligence,
    scarcity signalling, and emotion-adaptive responses. v4."""

    def __init__(
        self,
        products: list[Product],
        cost_prices: dict[str, int] | None = None,
        catalog: CatalogStore | None = None,
        prompt_path: str = DEFAULT_PROMPT_PATH,
    ):
        self.products = products
        self.cost_prices = cost_prices or load_cost_prices()
        self.catalog = catalog or CatalogStore()
        self.prompt_path = prompt_path

        self.retail_price = sum(p.price for p in products)
        self.cost_price = sum(
            self.cost_prices.get(p.id, int(p.price * 0.6))
            for p in products
        )
        self.floor_price = int(self.cost_price * 1.15)

        # Initialize upsell engine and get available bundles
        self.upsell_engine = UpsellEngine(self.catalog)
        product_ids = [p.id for p in products]
        self.available_recommendations = self.upsell_engine.get_recommendations(
            product_ids, max_recommendations=5
        )

        # Configure Gemini client
        settings = get_settings()
        api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Add it to .env or set the environment variable.\n"
                "Get a free key: https://aistudio.google.com/apikey"
            )
        self.client = genai.Client(api_key=api_key)

        # Build product details (with stock level)
        product_lines = []
        for p in products:
            cost = self.cost_prices.get(p.id, int(p.price * 0.6))
            stock_lvl = p.stock_level if p.stock_level is not None else p.stock
            product_lines.append(
                f"  • {p.name}: Retail ₹{p.price / 100:.0f}, Cost ₹{cost / 100:.0f}, "
                f"Stock: {stock_lvl} units"
            )

        # Build scarcity alerts for products with critically low stock
        scarcity_lines = []
        for p in products:
            stock_lvl = p.stock_level if p.stock_level is not None else p.stock
            if 0 < stock_lvl <= 5:
                scarcity_lines.append(
                    f"  ⚠️  CRITICAL SCARCITY: \"{p.name}\" — ONLY {stock_lvl} unit(s) left in stock! "
                    f"Use urgency to drive the sale."
                )
            elif 5 < stock_lvl <= 10:
                scarcity_lines.append(
                    f"  ⚡ LOW STOCK: \"{p.name}\" — Only {stock_lvl} units remaining. "
                    f"Mention limited availability."
                )

        self.scarcity_alerts = (
            "\n".join(scarcity_lines)
            if scarcity_lines
            else "  (All items well-stocked — no scarcity urgency needed)"
        )

        # Build bundle context
        bundle_lines = []
        if self.available_recommendations:
            for rec in self.available_recommendations:
                bundle_lines.append(
                    f"  • Bundle: Add \"{rec.product.name}\" (₹{rec.product.price / 100:.0f}) "
                    f"→ {rec.bundle_discount_pct}% off entire order. "
                    f"Reason: {rec.reason}"
                )
        else:
            bundle_lines.append("  • No specific bundles available — offer a general combo discount of 5-8%.")

        self.bundle_context = "\n".join(bundle_lines)
        self._build_system_prompt()

    def _build_system_prompt(self) -> None:
        """(Re-)build the system prompt from the prompt file. Call after reloading prompt_path."""
        product_lines = []
        for p in self.products:
            cost = self.cost_prices.get(p.id, int(p.price * 0.6))
            stock_lvl = p.stock_level if p.stock_level is not None else p.stock
            product_lines.append(
                f"  • {p.name}: Retail ₹{p.price / 100:.0f}, Cost ₹{cost / 100:.0f}, "
                f"Stock: {stock_lvl} units"
            )

        prompt_template = load_merchant_prompt(self.prompt_path)

        # Use explicit replace() instead of str.format() to avoid KeyError
        # when the prompt contains JSON examples with literal curly braces.
        self.system_prompt = (
            prompt_template
            .replace("{product_details}", "\n".join(product_lines))
            .replace("{retail_price}", f"{self.retail_price / 100:.0f}")
            .replace("{cost_price}", f"{self.cost_price / 100:.0f}")
            .replace("{floor_price}", f"{self.floor_price / 100:.0f}")
            .replace("{bundle_context}", self.bundle_context)
            .replace("{scarcity_alerts}", self.scarcity_alerts)
        )

        json_instructions = """
OUTPUT FORMAT:
Respond with a valid JSON object strictly matching this schema:
{
  "buyer_emotion": "aggressive" | "hesitant" | "impatient" | "friendly" | "analytical",
  "offered_price": number,
  "bundle_offer": string or null,
  "final_offer": boolean,
  "accepted": boolean,
  "walk_away": boolean,
  "message": "Your merchant response message text here"
}"""
        self.system_prompt += "\n\n" + json_instructions

    def reload_prompt(self) -> None:
        """Reload the system prompt from disk (used by self-improvement loop after rewrite)."""
        self._build_system_prompt()

    def generate_opening(self) -> NegotiationMessage:
        """Generate the merchant's opening pitch."""
        contents = [
            types.Content(role="user", parts=[
                types.Part(text="Customer has walked in interested in your products. "
                                "Greet them and offer at full retail price.")
            ])
        ]

        response = _gemini_call_with_retry(
            self.client,
            model="gemini-3.6-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.7,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )

        return self._parse_response(response.text)

    def generate_message(
        self, conversation_history: list[NegotiationMessage], is_final_round: bool = False,
    ) -> NegotiationMessage:
        """Generate the merchant's response based on conversation history."""
        contents = []

        for msg in conversation_history:
            if msg.role == "buyer":
                price_tag = f" (₹{msg.proposed_price / 100:.0f})" if msg.proposed_price else ""
                contents.append(
                    types.Content(role="user", parts=[
                        types.Part(text=f"Buyer: \"{msg.message}\"{price_tag}")
                    ])
                )
            elif msg.role == "merchant":
                contents.append(
                    types.Content(role="model", parts=[
                        types.Part(text=json.dumps({
                            "message": msg.message,
                            "offered_price": int(msg.proposed_price / 100) if msg.proposed_price else None,
                            "accepted": msg.accepted,
                            "final_offer": msg.final_offer,
                        }))
                    ])
                )

        if is_final_round:
            last_buyer_price = None
            for msg in reversed(conversation_history):
                if msg.role == "buyer" and msg.proposed_price:
                    last_buyer_price = msg.proposed_price
                    break

            if last_buyer_price and last_buyer_price >= self.floor_price:
                hint = (f"FINAL ROUND. Buyer offers ₹{last_buyer_price / 100:.0f}, "
                        f"above your floor ₹{self.floor_price / 100:.0f}. ACCEPT the deal.")
            else:
                hint = (f"FINAL ROUND. Make your absolute best offer or pitch a bundle. "
                        f"Floor: ₹{self.floor_price / 100:.0f}.")

            contents.append(
                types.Content(role="user", parts=[types.Part(text=hint)])
            )

        response = _gemini_call_with_retry(
            self.client,
            model="gemini-3.6-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.7,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )

        result = self._parse_response(response.text)

        # Safety: NEVER allow price below floor
        if result.proposed_price and result.proposed_price < self.floor_price:
            result.proposed_price = self.floor_price

        return result

    def _parse_response(self, raw_text: str) -> NegotiationMessage:
        """Parse LLM JSON response, with robust regex fallback for truncated JSON."""
        text = raw_text.strip()
        
        # Strip markdown fences
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()

        # Try full JSON parse
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            from rich import print as rprint
            rprint(f"\n[bold yellow]JSON Parse Error from Merchant: {e}[/bold yellow]")
            rprint(f"[yellow]Raw text:[/yellow]\n{raw_text}\n")
            pass

        if data is None:
            data = {}

        # Extract each field robustly (handles truncated JSON)
        message = data.get("message")
        if not message:
            m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
            message = m.group(1).replace('\\"', '"').replace('\\n', ' ') if m else "I have a great offer for you."

        offered = data.get("offered_price")
        if offered is None:
            m = re.search(r'"offered_price"\s*:\s*(\d+(?:\.\d+)?)', text)
            offered = float(m.group(1)) if m else self.retail_price / 100

        accepted = data.get("accepted")
        if accepted is None:
            m = re.search(r'"accepted"\s*:\s*(true|false)', text, re.IGNORECASE)
            accepted = m.group(1).lower() == "true" if m else False

        final_offer = data.get("final_offer")
        if final_offer is None:
            m = re.search(r'"final_offer"\s*:\s*(true|false)', text, re.IGNORECASE)
            final_offer = m.group(1).lower() == "true" if m else False

        walk_away = data.get("walk_away")
        if walk_away is None:
            m = re.search(r'"walk_away"\s*:\s*(true|false)', text, re.IGNORECASE)
            walk_away = m.group(1).lower() == "true" if m else False

        bundle_offer = data.get("bundle_offer")

        # New: extract buyer_emotion classification
        buyer_emotion = data.get("buyer_emotion")
        if not buyer_emotion:
            m = re.search(r'"buyer_emotion"\s*:\s*"([^"]+)"', text)
            buyer_emotion = m.group(1) if m else "unknown"

        offered_paise = int(float(offered) * 100) if offered is not None else self.retail_price

        # Safety floor
        if offered_paise < self.floor_price:
            offered_paise = self.floor_price

        msg = NegotiationMessage(
            role="merchant",
            message=message,
            proposed_price=offered_paise,
            accepted=bool(accepted),
            final_offer=bool(final_offer),
            walk_away=bool(walk_away),
        )

        # Store extra metadata (not in pydantic model, but useful for evaluator)
        msg._bundle_offer = bundle_offer      # type: ignore
        msg._buyer_emotion = buyer_emotion    # type: ignore

        return msg

    def get_simulation_context(self) -> dict:
        """Return all merchant context needed for the 1-shot simulation prompt."""
        return {
            "retail_price": self.retail_price,
            "cost_price": self.cost_price,
            "floor_price": self.floor_price,
            "product_names": [p.name for p in self.products],
            "product_ids": [p.id for p in self.products],
            "bundle_context": self.bundle_context,
            "scarcity_alerts": self.scarcity_alerts,
            "system_prompt": self.system_prompt,
        }


# ──────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    from rich.panel import Panel
    console = Console(force_terminal=True)

    console.print("\n[bold green]🏪 Merchant AI (v3 — Smart Counter-Offer) — Self-Test[/bold green]\n")

    try:
        catalog = CatalogStore()
        p1 = catalog.get_product("prod_002")
        p2 = catalog.get_product("prod_040")
        products = [p for p in [p1, p2] if p is not None]

        merchant = MerchantAI(products=products, catalog=catalog)
        console.print("[green]✅ MerchantAI initialized with upsell context[/green]")
        console.print(f"  Retail: ₹{merchant.retail_price / 100:.0f}")
        console.print(f"  Cost:   ₹{merchant.cost_price / 100:.0f}")
        console.print(f"  Floor:  ₹{merchant.floor_price / 100:.0f}")
        console.print(f"  Available bundles: {len(merchant.available_recommendations)}")
        for rec in merchant.available_recommendations:
            console.print(f"    • {rec.product.name} ({rec.bundle_discount_pct}% off) — {rec.reason}")

        console.print(f"\n[bold green]✅ Merchant AI v3 self-test passed![/bold green]\n")

    except ValueError as e:
        console.print(f"\n[bold red]❌ {e}[/bold red]\n")
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        raise
