"""
Agentic Storefront  WhatsApp Bot Server (Twilio Integration)
Connects the Merchant AI negotiation engine to WhatsApp via Twilio webhooks.
A real human can haggle with the AI from their phone and receive a Razorpay
payment link when a deal is struck.

Run:
    uvicorn whatsapp_server:app --reload

Then expose via ngrok:
    ngrok http 8000

Set the ngrok URL as the Twilio Sandbox webhook:
    https://<your-id>.ngrok-free.app/whatsapp
"""

import re
import time
import logging
import os
from typing import Optional
from dataclasses import dataclass, field

from fastapi import FastAPI, Form, Request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from config import get_settings, get_razorpay_client
from src.catalog import CatalogStore
from src.merchant_ai import MerchantAI, load_cost_prices
from src.models import NegotiationMessage
from src.razorpay_service import RazorpayService
from agentic_storefront_guardrails.audit_log import AuditLog
from src.guardrail_factory import get_guardrail_stack, make_idempotency_key

# 
# Logging
# 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("whatsapp_bot")


# 
# Session Management
# 

@dataclass
class WhatsAppSession:
    """Holds the negotiation state for a single WhatsApp user (by phone number)."""

    phone: str
    merchant: MerchantAI
    conversation: list[NegotiationMessage] = field(default_factory=list)
    round_number: int = 0
    deal_closed: bool = False
    deal_failed: bool = False
    last_buyer_price_paise: int | None = None
    final_price_paise: int | None = None
    payment_link_url: str | None = None
    order_id: str | None = None
    created_at: float = field(default_factory=time.time)


# In-memory session store: phone number  session
sessions: dict[str, WhatsAppSession] = {}


def _create_session(phone: str) -> WhatsAppSession:
    """Create a fresh negotiation session for a phone number."""
    catalog = CatalogStore()
    cost_prices = load_cost_prices()

    # Default negotiation products (same as `main.py negotiate`)
    p1 = catalog.get_product("prod_002")  # Colombian Supremo Dark Roast 420
    p2 = catalog.get_product("prod_040")  # Hario V60 Paper Filters 150
    products = [p for p in [p1, p2] if p is not None]

    if not products:
        raise RuntimeError("Could not load products from catalog")

    # Wire guardrail stack into the MerchantAI
    stack = get_guardrail_stack()
    merchant = MerchantAI(
        products=products, cost_prices=cost_prices, catalog=catalog,
        inventory_manager=stack.inventory,
    )
    merchant.set_price_guard(stack.price_guard)

    session = WhatsAppSession(phone=phone, merchant=merchant)

    # Generate the merchant's opening message
    opening = merchant.generate_opening()
    session.conversation.append(opening)
    session.round_number = 1

    logger.info(
        "New session for %s | Products: %s | Retail: %.0f",
        phone,
        ", ".join(p.name for p in products),
        merchant.retail_price / 100,
    )

    return session


def get_or_create_session(phone: str) -> WhatsAppSession:
    """Retrieve an existing session or create a new one."""
    if phone not in sessions:
        sessions[phone] = _create_session(phone)
    return sessions[phone]


def reset_session(phone: str) -> WhatsAppSession:
    """Clear the existing session and start fresh."""
    if phone in sessions:
        del sessions[phone]
    sessions[phone] = _create_session(phone)
    return sessions[phone]


# 
# Price Extraction
# 

def extract_price_from_message(text: str) -> int | None:
    """
    Try to extract a price (in rupees) from the user's message.
    Returns the price in paise, or None if no price found.

    Handles formats like:
        450, Rs 450, Rs.450, 450 rupees, I'll pay 450, my budget is 500
    """
    # Pattern: optional /Rs/Rs. prefix, then digits (with optional commas)
    patterns = [
        r'\s*([\d,]+)',
        r'[Rr][Ss]\.?\s*([\d,]+)',
        r'([\d,]+)\s*(?:rupees|rs|inr)',
        r'(?:pay|offer|budget|afford|spend|give|do)\s*(?:is\s*)??\s*([\d,]+)',
        r'(?:how\s*about|what\s*about|let\'?s?\s*(?:do|say))\s*?\s*([\d,]+)',
        r'\b(\d{3,5})\b',  # Bare 3-5 digit number as last resort
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price_rupees = int(price_str)
                # Sanity check: price should be between 50 and 50,000
                if 50 <= price_rupees <= 50000:
                    return price_rupees * 100  # Convert to paise
            except ValueError:
                continue

    return None


# 
# Catalog Display
# 

def get_catalog_text() -> str:
    """Build a WhatsApp-friendly product catalog string."""
    catalog = CatalogStore()
    lines = [" *Ravi's Premium Coffee Shop*\n"]

    categories = {
        "coffee_beans": " Coffee Beans",
        "brewing_equipment": " Brewing Equipment",
        "accessories": " Accessories",
        "mugs_drinkware": " Mugs & Drinkware",
    }

    for cat_id, cat_name in categories.items():
        products = catalog.list_products(category=cat_id, limit=5)
        if products:
            lines.append(f"\n*{cat_name}*")
            for p in products:
                lines.append(f"   {p.name}  {p.price / 100:.0f}")

    lines.append("\n _Just tell me what you're interested in and let's negotiate!_")
    return "\n".join(lines)


# 
# Payment Link Generation
# 

def create_payment_link(session: WhatsAppSession) -> str | None:
    """
    Generate a Razorpay payment link for the agreed deal.
    ALL payment links go through PaymentGate.finalize_deal() — the single
    choke point that re-checks the price, reserves inventory, and retries
    on failure. No code path may bypass this.
    Returns the short_url or None on failure.
    """
    if not session.final_price_paise or session.final_price_paise <= 0:
        return None

    try:
        stack = get_guardrail_stack()

        # Use first product's ID as the SKU for guardrail checks
        sku = session.merchant.products[0].id if session.merchant.products else "unknown"
        negotiation_id = f"wa-{session.phone}-{int(session.created_at)}"
        agreed_price_rupees = session.final_price_paise / 100

        # Idempotency key derived from phone + round — prevents double-charge on retry
        idem_key = make_idempotency_key(negotiation_id, session.round_number)

        result = stack.payment_gate.finalize_deal(
            negotiation_id=negotiation_id,
            sku=sku,
            agreed_price=agreed_price_rupees,
            idempotency_key=idem_key,
        )

        if result.success and result.payment_link:
            session.payment_link_url = result.payment_link
            logger.info(
                "Payment link created via PaymentGate for %s: %s (₹%.0f)",
                session.phone, result.payment_link, agreed_price_rupees,
            )
            return result.payment_link
        else:
            logger.warning(
                "PaymentGate blocked/failed for %s: %s",
                session.phone, result.reason,
            )
            return None

    except Exception as e:
        logger.error("Payment link creation failed for %s: %s", session.phone, e)
        return None


# 
# Core Message Processing
# 

# --- P1-7: Per-phone rate limiter ---
_rate_limit_window: dict[str, list[float]] = {}
RATE_LIMIT_MAX_MESSAGES = 30      # max messages per window
RATE_LIMIT_WINDOW_SECONDS = 600   # 10-minute window


def _is_rate_limited(phone: str) -> bool:
    """Check if a phone number has exceeded the rate limit."""
    now = time.time()
    timestamps = _rate_limit_window.get(phone, [])
    # Purge old timestamps outside the window
    timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(timestamps) >= RATE_LIMIT_MAX_MESSAGES:
        _rate_limit_window[phone] = timestamps
        return True
    timestamps.append(now)
    _rate_limit_window[phone] = timestamps
    return False


def process_message(phone: str, incoming_msg: str) -> str:
    """
    Process an incoming WhatsApp message and return the merchant's response.
    This is the main orchestrator that ties together session management,
    the Merchant AI, and Razorpay payment link generation.
    """
    # --- Rate limit check ---
    if _is_rate_limited(phone):
        logger.warning("Rate limited: %s", phone)
        return (
            "⏱️ You're sending messages a bit too quickly! "
            "Please wait a moment and try again."
        )

    msg_lower = incoming_msg.strip().lower()

    #  Special Commands 

    if msg_lower in ("reset", "new", "restart", "start over"):
        session = reset_session(phone)
        opening = session.conversation[0].message if session.conversation else ""
        return f" _Starting a fresh negotiation!_\n\n{opening}"

    if msg_lower in ("catalog", "menu", "products", "shop", "list"):
        return get_catalog_text()

    if msg_lower in ("help", "hi", "hello", "hey"):
        session = get_or_create_session(phone)
        if session.round_number <= 1 and len(session.conversation) <= 1:
            # First interaction  return the opening
            opening = session.conversation[0].message if session.conversation else ""
            return (
                f" Welcome to *Ravi's Premium Coffee Shop*!\n\n"
                f"{opening}\n\n"
                f" _Commands:_\n"
                f"   Type *catalog* to see all products\n"
                f"   Type *reset* to start a new negotiation\n"
                f"   Just chat naturally to negotiate!"
            )
        # Already in a session
        return (
            " _Commands:_\n"
            "   Type *catalog* to see all products\n"
            "   Type *reset* to start a new negotiation\n"
            "   Just chat naturally to negotiate the price!"
        )

    #  Get or create session 

    session = get_or_create_session(phone)

    #  Already closed? 

    if session.deal_closed:
        return (
            f" We already have a deal at *{session.final_price_paise / 100:.0f}*!\n\n"
            f" Pay here: {session.payment_link_url or 'Link generation failed'}\n\n"
            f"_Type *reset* to start a new negotiation._"
        )

    if session.deal_failed:
        return (
            " Our last negotiation didn't work out.\n\n"
            "_Type *reset* to start a fresh negotiation!_"
        )

    #  Extract buyer's price offer 

    buyer_price_paise = extract_price_from_message(incoming_msg)
    if buyer_price_paise is not None:
        session.last_buyer_price_paise = buyer_price_paise

    #  Build buyer message 

    buyer_msg = NegotiationMessage(
        role="buyer",
        message=incoming_msg.strip(),
        proposed_price=buyer_price_paise,
    )
    session.conversation.append(buyer_msg)
    session.round_number += 1

    # --- Audit: log every inbound buyer message ---
    negotiation_id = f"wa-{phone}-{int(session.created_at)}"
    try:
        stack = get_guardrail_stack()
        stack.audit.log_turn(
            negotiation_id=negotiation_id,
            round_number=session.round_number,
            actor="buyer",
            action="message",
            proposed_price=buyer_price_paise / 100 if buyer_price_paise else None,
            rationale=incoming_msg.strip()[:200],
        )
    except Exception:
        pass  # Audit failure must not break the negotiation

    #  Call the Merchant AI 

    is_final_round = session.round_number >= 4
    max_rounds = 4

    try:
        merchant_response = session.merchant.generate_message(
            conversation_history=session.conversation,
            is_final_round=is_final_round,
        )
    except Exception as e:
        logger.error("Merchant AI error for %s: %s", phone, e)
        return (
            " Give me just a moment, my friend  "
            "I'm having a small technical issue. Please try again!"
        )

    # Append merchant response to conversation
    session.conversation.append(merchant_response)

    # --- Audit: log every outbound merchant message ---
    try:
        action = "accept" if merchant_response.accepted else (
            "walk_away" if merchant_response.walk_away else "counter_offer"
        )
        stack = get_guardrail_stack()
        stack.audit.log_turn(
            negotiation_id=negotiation_id,
            round_number=session.round_number,
            actor="merchant_ai",
            action=action,
            proposed_price=merchant_response.proposed_price / 100 if merchant_response.proposed_price else None,
            rationale=merchant_response.message[:200],
        )
    except Exception:
        pass

    logger.info(
        "Round %d/%d | %s | Buyer: %s | Merchant: %.0f | Accepted: %s",
        session.round_number,
        max_rounds,
        phone,
        f"{buyer_price_paise / 100:.0f}" if buyer_price_paise else "no price",
        merchant_response.proposed_price / 100 if merchant_response.proposed_price else 0,
        merchant_response.accepted,
    )

    #  Build response text 

    response_text = merchant_response.message

    # Add price tag if the merchant made a counter-offer
    if merchant_response.proposed_price and not merchant_response.accepted:
        price_rupees = merchant_response.proposed_price / 100
        response_text += f"\n\n *My offer: {price_rupees:.0f}*"

    if merchant_response.final_offer and not merchant_response.accepted:
        response_text += "\n _This is my final offer._"

    #  Handle deal acceptance 

    if merchant_response.accepted:
        agreed_price = (
            merchant_response.proposed_price
            or session.last_buyer_price_paise
            or session.merchant.floor_price
        )
        session.final_price_paise = agreed_price
        session.deal_closed = True

        response_text += f"\n\n *DEAL! Final Price: {agreed_price / 100:.0f}*"

        # Generate Razorpay payment link
        payment_url = create_payment_link(session)
        if payment_url:
            response_text += f"\n\n Complete your payment here:\n{payment_url}"
        else:
            response_text += (
                "\n\n_(Payment link generation failed. "
                "Please contact us to complete your purchase.)_"
            )

        response_text += "\n\n_Type *reset* to start a new negotiation._"

    #  Handle walk away 

    elif merchant_response.walk_away:
        session.deal_failed = True
        response_text += (
            "\n\n _I'm sorry we couldn't reach a deal today. "
            "Type *reset* to try again!_"
        )

    return response_text


# 
# FastAPI Application
# 

app = FastAPI(
    title="Agentic Storefront  WhatsApp Bot",
    description="Merchant AI negotiation engine connected to WhatsApp via Twilio",
    version="1.0.0",
)


@app.get("/")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Agentic Storefront WhatsApp Bot",
        "active_sessions": len(sessions),
    }


@app.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    NumMedia: str = Form("0"),
):
    """
    Twilio WhatsApp webhook endpoint.

    Twilio sends a POST with form-encoded data including:
      - Body: The text message content
      - From: Sender's WhatsApp number (e.g., 'whatsapp:+919876543210')
      - To: Your Twilio WhatsApp number
      - NumMedia: Number of media attachments

    We process the message through the Merchant AI and return TwiML XML.
    """
    # --- P1-6: Twilio webhook signature verification ---
    settings = get_settings()
    twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if twilio_auth_token:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(twilio_auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        # Reconstruct the full URL Twilio used to sign
        url = str(request.url)
        form_data = await request.form()
        params = {k: v for k, v in form_data.items()}
        if not validator.validate(url, params, signature):
            logger.warning("Twilio signature verification FAILED from %s", From)
            return Response(content="Forbidden", status_code=403)
    else:
        logger.debug("TWILIO_AUTH_TOKEN not set — skipping signature verification (dev mode)")

    phone = From.strip()
    incoming_msg = Body.strip()

    logger.info(" Message from %s: %s", phone, incoming_msg[:100])

    # Ignore empty messages or media-only messages
    if not incoming_msg:
        resp = MessagingResponse()
        resp.message(
            " Welcome to Ravi's Premium Coffee Shop! "
            "Send me a text message to start negotiating. "
            "Type *help* for options."
        )
        return Response(content=str(resp), media_type="text/xml")

    # Process through the Merchant AI
    try:
        reply_text = process_message(phone, incoming_msg)
    except Exception as e:
        logger.error("Error processing message from %s: %s", phone, e, exc_info=True)
        reply_text = (
            " Sorry, something went wrong on our end. "
            "Please try again in a moment!"
        )

    logger.info(" Generating reply to %s: %s", phone, reply_text[:100])

    # Return TwiML so Twilio sends the reply directly
    # MUST set charset=utf-8 so Twilio doesn't use Latin-1 and crash on Rupee (,1) symbols!
    resp = MessagingResponse()
    resp.message(reply_text)
    return Response(content=str(resp).encode("utf-8"), media_type="text/xml; charset=utf-8")


# 
# Startup Event
# 

@app.on_event("startup")
async def startup_event():
    """Log server startup."""
    logger.info("=" * 60)
    logger.info(" Agentic Storefront  WhatsApp Bot Server")
    logger.info("=" * 60)
    logger.info("Endpoint: POST /whatsapp")
    logger.info("Health:   GET  /")
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Run:  ngrok http 8000")
    logger.info("  2. Set Twilio Sandbox webhook to:")
    logger.info("     https://<your-ngrok-id>.ngrok-free.app/whatsapp")
    logger.info("  3. Send a WhatsApp message to your Twilio Sandbox number!")
    logger.info("=" * 60)
