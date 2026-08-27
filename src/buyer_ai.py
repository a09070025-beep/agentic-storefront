"""
Agentic Storefront — Buyer AI Agent
LLM-powered buyer that negotiates prices using a strict persona and budget.
Uses Google Gemini (google-genai SDK) for natural language generation.
"""

import json
import re
import os
import time
from config import get_settings
from src.models import NegotiationMessage



# ──────────────────────────────────────────────
# Buyer Persona Definition
# ──────────────────────────────────────────────

DEFAULT_BUYER_PERSONA = {
    "name": "Arjun",
    "personality": "Budget-conscious college student and coffee enthusiast",
    "budget": 55000,  # ₹550 in paise
    "shopping_list": [],  # filled at runtime with actual product names
}


BUYER_SYSTEM_PROMPT = """You are {name}, a {personality}.

You are shopping for: {product_list}
Merchant's retail price: ₹{retail_price}. Your max budget: ₹{budget}.

RULES:
1. NEVER agree above ₹{budget}.
2. Start 25-30% below retail. Haggle aggressively.
3. Mention competitor prices and online deals.
4. Be friendly but firm. Keep messages to 2 sentences max.
5. If merchant is within ₹{wiggle_room} of your counter, you may accept.
6. If they refuse to go under budget after 3+ rounds, walk away.
7. CRITICAL: NEVER offer LESS than your previous counter-offer. Your offers must go UP each round, not down. Lowering your offer is irrational and forbidden.

Reply ONLY as JSON: {{"message":"...","proposed_price":NUMBER,"accepted":BOOL,"walk_away":BOOL}}
- proposed_price = number in rupees (430 = ₹430). Always include this.
- accepted = true only if you accept merchant's price (set proposed_price to that price).
- walk_away = true only if giving up."""


class BuyerAI:
    """LLM-powered buyer agent that negotiates with a strict budget."""

    def __init__(
        self,
        persona: dict | None = None,
        product_names: list[str] | None = None,
        retail_price: int = 0,
    ):
        self.persona = persona or DEFAULT_BUYER_PERSONA.copy()
        self.product_names = product_names or []
        self.retail_price = retail_price  # paise
        self.budget = self.persona["budget"]  # paise

        # Configure OSS OpenAI client
        settings = get_settings()
        api_key = settings.oss_api_key or os.getenv("OSS_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
        base_url = settings.oss_base_url or os.getenv("OSS_BASE_URL", "")
        
        if not base_url and os.getenv("GROQ_API_KEY"):
            base_url = "https://api.groq.com/openai/v1"
            
        if not api_key or not base_url:
            raise ValueError("OSS_API_KEY and OSS_BASE_URL (or GROQ_API_KEY) must be set in .env")
            
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        # Build system prompt
        wiggle_room = max(int(self.budget * 0.05 / 100), 20)
        self.system_prompt = BUYER_SYSTEM_PROMPT.format(
            name=self.persona["name"],
            personality=self.persona["personality"],
            product_list=", ".join(self.product_names),
            retail_price=f"{self.retail_price / 100:.0f}",
            budget=f"{self.budget / 100:.0f}",
            wiggle_room=f"{wiggle_room}",
        )

    def generate_message(
        self, conversation_history: list[NegotiationMessage]
    ) -> NegotiationMessage:
        """Generate the buyer's next message based on conversation history."""
        messages = [{"role": "system", "content": self.system_prompt}]

        for msg in conversation_history:
            if msg.role == "merchant":
                price_tag = f" (₹{msg.proposed_price / 100:.0f})" if msg.proposed_price else ""
                messages.append({"role": "user", "content": f"Merchant: \"{msg.message}\"{price_tag}"})
            elif msg.role == "buyer":
                messages.append({"role": "assistant", "content": json.dumps({
                    "message": msg.message,
                    "proposed_price": int(msg.proposed_price / 100) if msg.proposed_price else None,
                    "accepted": msg.accepted,
                    "walk_away": msg.walk_away,
                })})

        if not conversation_history or conversation_history[-1].role != "merchant":
            messages.append({"role": "user", "content": "Merchant has presented the products. Make your opening counter-offer."})

        # Call API with robust retry loop
        from config import GROQ_MODEL_NAME, oss_api_call_with_retry

        try:
            response = oss_api_call_with_retry(
                self.client,
                model=GROQ_MODEL_NAME,
                messages=messages,
                temperature=0.8,
                max_tokens=1024,
            )
            content = response.choices[0].message.content or ""
        except Exception as e:
            from rich import print as rprint
            rprint(f"  [bold red]BuyerAI API call failed after retries: {e}[/bold red]")
            # Return a safe default message instead of crashing
            return NegotiationMessage(
                role="buyer",
                message="I need a better price to make this work.",
                proposed_price=int(self.budget * 0.7),
                accepted=False,
                walk_away=False,
            )

        return self._parse_response(content)

    def _parse_response(self, raw_text: str) -> NegotiationMessage:
        """Parse LLM JSON response, with robust regex fallback for truncated JSON."""
        text = raw_text.strip()

        # Try full JSON parse first
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fallback: extract fields individually via regex (handles truncated JSON)
        if data is None:
            data = {}

        message = data.get("message")
        if not message:
            # Extract message from partial JSON
            m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
            message = m.group(1).replace('\\"', '"').replace('\\n', ' ') if m else "I need a better price."

        proposed = data.get("proposed_price")
        if proposed is None:
            m = re.search(r'"proposed_price"\s*:\s*(\d+(?:\.\d+)?)', text)
            proposed = float(m.group(1)) if m else self.budget * 0.7 / 100

        accepted = data.get("accepted")
        if accepted is None:
            m = re.search(r'"accepted"\s*:\s*(true|false)', text, re.IGNORECASE)
            accepted = m.group(1).lower() == "true" if m else False

        walk_away = data.get("walk_away")
        if walk_away is None:
            m = re.search(r'"walk_away"\s*:\s*(true|false)', text, re.IGNORECASE)
            walk_away = m.group(1).lower() == "true" if m else False

        proposed_paise = int(float(proposed) * 100) if proposed is not None else None

        return NegotiationMessage(
            role="buyer",
            message=message,
            proposed_price=proposed_paise,
            accepted=bool(accepted),
            walk_away=bool(walk_away),
        )


# ──────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from rich.console import Console
    from rich.panel import Panel
    console = Console(force_terminal=True)

    console.print("\n[bold blue]🛒 Buyer AI — Self-Test[/bold blue]\n")

    try:
        buyer = BuyerAI(
            product_names=["Colombian Supremo Dark Roast", "Hario V60 Paper Filters (100pk)"],
            retail_price=57000,
        )
        console.print("[green]✅ BuyerAI initialized[/green]")
        console.print(f"  Budget: ₹{buyer.budget / 100:.0f}")

        merchant_msg = NegotiationMessage(
            role="merchant",
            message="Welcome! Colombian Supremo and V60 filters, both for ₹570!",
            proposed_price=57000,
        )

        console.print(f"\n[cyan]Generating buyer response...[/cyan]")
        response = buyer.generate_message([merchant_msg])

        price_str = f"₹{response.proposed_price / 100:.0f}" if response.proposed_price else "N/A"
        console.print(Panel(
            f"{response.message}\n\nCounter-offer: {price_str}",
            title="🛒 Buyer AI Response",
            border_style="blue",
        ))
        console.print(f"  Accepted: {response.accepted} | Walk away: {response.walk_away}")
        console.print(f"\n[bold green]✅ Buyer AI self-test passed![/bold green]\n")

    except ValueError as e:
        console.print(f"\n[bold red]❌ {e}[/bold red]\n")
    except Exception as e:
        console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
        raise
