"""
schemas.py
----------
Structured-output contracts for anything the Merchant AI produces that
touches money. The core rule this file enforces:

    NEVER parse a price out of the LLM's freeform negotiation text.
    ALWAYS require the LLM to return a small, strictly-typed JSON object,
    and validate every field server-side before it is trusted.

This is deliberately dependency-free (no pydantic) so it drops into any
stack (FastAPI, plain scripts, Cloud Functions, etc.) without needing
`pip install` in an environment that may not have network access.
If you already use pydantic in your project, port these to BaseModel —
the validation rules matter more than the library.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
import re

Currency = Literal["INR"]


class SchemaValidationError(ValueError):
    """Raised when the LLM's structured output fails validation."""


@dataclass(frozen=True)
class NegotiationOffer:
    """
    The ONLY shape a Merchant AI's pricing decision is allowed to take.
    Ask your LLM (via response_format / JSON mode / tool-calling) to return
    exactly this shape. Free text ("I can do that for you at nine
    thousand rupees!") must never be trusted as the source of truth for
    an actual transaction.
    """
    sku: str
    proposed_price: float
    currency: Currency
    negotiation_id: str
    round_number: int
    action: Literal["counter_offer", "accept", "reject", "escalate_bundle"]
    rationale: str = ""  # for the audit trail / explainability, not for trust

    @staticmethod
    def from_llm_json(data: dict) -> "NegotiationOffer":
        required = ["sku", "proposed_price", "currency", "negotiation_id",
                    "round_number", "action"]
        missing = [f for f in required if f not in data]
        if missing:
            raise SchemaValidationError(f"Missing required fields: {missing}")

        sku = str(data["sku"]).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", sku):
            raise SchemaValidationError(f"Malformed sku: {sku!r}")

        try:
            price = float(data["proposed_price"])
        except (TypeError, ValueError):
            raise SchemaValidationError(
                f"proposed_price is not a number: {data['proposed_price']!r}")

        if price != price or price in (float("inf"), float("-inf")):
            raise SchemaValidationError("proposed_price is NaN/Infinity")

        if data["currency"] != "INR":
            raise SchemaValidationError(
                f"Unsupported currency: {data['currency']!r}")

        if data["action"] not in (
            "counter_offer", "accept", "reject", "escalate_bundle"
        ):
            raise SchemaValidationError(f"Unknown action: {data['action']!r}")

        try:
            round_number = int(data["round_number"])
        except (TypeError, ValueError):
            raise SchemaValidationError("round_number must be an integer")

        return NegotiationOffer(
            sku=sku,
            proposed_price=round(price, 2),
            currency=data["currency"],
            negotiation_id=str(data["negotiation_id"]),
            round_number=round_number,
            action=data["action"],
            rationale=str(data.get("rationale", ""))[:500],
        )


@dataclass(frozen=True)
class PriceCheckResult:
    """Result of an authoritative, server-side price check."""
    allowed: bool
    reason: str
    floor_price: float
    list_price: float
    checked_price: float
