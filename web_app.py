import os
import uuid
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import get_settings
from src.catalog import CatalogStore
from src.merchant_ai import MerchantAI, NegotiationMessage
from src.razorpay_service import RazorpayService
from src.guardrail_factory import get_guardrail_stack, make_idempotency_key
from x402_adapter import x402_router

app = FastAPI(title="Agentic Storefront - Web UI")

# Include the x402 protocol router
# app.include_router(x402_router)

# Initialize shared resources
settings = get_settings()
catalog = CatalogStore()
razorpay_service = RazorpayService()

# In-memory session store
sessions = {}

class ChatSession:
    def __init__(self):
        p1 = catalog.get_product("prod_002")
        p2 = catalog.get_product("prod_040")
        products = [p for p in [p1, p2] if p is not None]
        # Wire guardrail stack into the MerchantAI
        stack = get_guardrail_stack()
        self.merchant = MerchantAI(
            products=products, catalog=catalog,
            inventory_manager=stack.inventory,
        )
        self.merchant.set_price_guard(stack.price_guard)
        self.conversation = []
        self.round_number = 0
        self.deal_closed = False
        self.deal_failed = False
        self.last_buyer_price_paise = None
        self.final_price_paise = None

class ChatRequest(BaseModel):
    session_id: str
    message: str

def extract_price_from_message(msg: str) -> int | None:
    import re
    msg_clean = msg.replace(",", "")
    match = re.search(r'(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)', msg_clean, re.IGNORECASE)
    if not match:
        match = re.search(r'(\d+(?:\.\d+)?)\s*(?:rs\.?|inr|rupees)', msg_clean, re.IGNORECASE)
    if not match:
        match = re.search(r'\b(\d+(?:\.\d{1,2})?)\b', msg_clean)
    if match:
        return int(float(match.group(1)) * 100)
    return None

def create_payment_link(session: ChatSession, session_id: str) -> str | None:
    """Route through PaymentGate.finalize_deal() — the single choke point.
    No direct Razorpay calls from negotiation code."""
    if not session.final_price_paise or session.final_price_paise <= 0:
        return None
    try:
        stack = get_guardrail_stack()
        sku = session.merchant.products[0].id if session.merchant.products else "unknown"
        negotiation_id = f"web-{session_id}"
        agreed_price_rupees = session.final_price_paise / 100
        idem_key = make_idempotency_key(negotiation_id, session.round_number)

        result = stack.payment_gate.finalize_deal(
            negotiation_id=negotiation_id,
            sku=sku,
            agreed_price=agreed_price_rupees,
            idempotency_key=idem_key,
        )
        return result.payment_link if result.success else None
    except Exception:
        return None

@app.get("/", response_class=HTMLResponse)
async def get_chat_page():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ravi's Coffee Shop</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #e5ddd5; margin: 0; padding: 0; display: flex; justify-content: center; height: 100vh; }
            #chat-container { width: 100%; max-width: 450px; background: #fff; display: flex; flex-direction: column; height: 100%; box-shadow: 0 0 15px rgba(0,0,0,0.1); }
            #header { background: #075e54; color: white; padding: 15px; text-align: center; font-size: 1.2em; font-weight: bold; }
            #chat-box { flex: 1; padding: 20px; overflow-y: auto; background: #e5ddd5; display: flex; flex-direction: column; gap: 10px; }
            .msg { max-width: 80%; padding: 10px 15px; border-radius: 15px; font-size: 0.95em; line-height: 1.4; word-wrap: break-word; }
            .msg.bot { background: #fff; align-self: flex-start; border-top-left-radius: 0; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
            .msg.user { background: #dcf8c6; align-self: flex-end; border-top-right-radius: 0; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
            #input-area { display: flex; padding: 10px; background: #f0f0f0; }
            #user-input { flex: 1; padding: 12px; border: none; border-radius: 20px; outline: none; font-size: 1em; }
            #send-btn { background: #075e54; color: white; border: none; padding: 10px 20px; margin-left: 10px; border-radius: 20px; cursor: pointer; font-weight: bold; }
            #send-btn:hover { background: #128c7e; }
            .typing { font-style: italic; color: #888; font-size: 0.8em; align-self: flex-start; margin-left: 10px; display: none; }
        </style>
    </head>
    <body>
        <div id="chat-container">
            <div id="header">Ravi's Coffee Shop ☕</div>
            <div id="chat-box">
                <div class="msg bot">👋 Welcome to Ravi's Premium Coffee Shop! What can I get for you today?</div>
            </div>
            <div id="typing" class="typing">Ravi is typing...</div>
            <div id="input-area">
                <input type="text" id="user-input" placeholder="Type a message..." onkeypress="handleKeyPress(event)">
                <button id="send-btn" onclick="sendMessage()">Send</button>
            </div>
        </div>
        <script>
            const sessionId = Math.random().toString(36).substring(2, 15);

            function addMessage(text, sender) {
                const chatBox = document.getElementById('chat-box');
                const msgDiv = document.createElement('div');
                msgDiv.className = `msg ${sender}`;
                
                let formattedText = text.replace(/\\*\\*(.*?)\\*\\*/g, '<b>$1</b>');
                formattedText = formattedText.replace(/\\*(.*?)\\*/g, '<i>$1</i>');
                formattedText = formattedText.replace(/\\n/g, '<br>');
                formattedText = formattedText.replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank" style="color: #0066cc; font-weight: bold;">$1</a>');
                
                msgDiv.innerHTML = formattedText;
                chatBox.appendChild(msgDiv);
                chatBox.scrollTop = chatBox.scrollHeight;
            }

            async function sendMessage() {
                const input = document.getElementById('user-input');
                const text = input.value.trim();
                if (!text) return;

                addMessage(text, 'user');
                input.value = '';
                
                document.getElementById('typing').style.display = 'block';
                document.getElementById('chat-box').scrollTop = document.getElementById('chat-box').scrollHeight;

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId, message: text })
                    });
                    const data = await response.json();
                    document.getElementById('typing').style.display = 'none';
                    addMessage(data.reply, 'bot');
                } catch (e) {
                    document.getElementById('typing').style.display = 'none';
                    addMessage("Sorry, I'm having trouble connecting right now.", 'bot');
                }
            }

            function handleKeyPress(e) {
                if (e.key === 'Enter') sendMessage();
            }
        </script>
    </body>
    </html>
    """
    return html_content

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    session_id = req.session_id
    incoming_msg = req.message

    if session_id not in sessions:
        sessions[session_id] = ChatSession()
        opening = sessions[session_id].merchant.generate_opening()
        sessions[session_id].conversation.append(opening)

    session = sessions[session_id]

    if incoming_msg.strip().lower() == "reset":
        sessions[session_id] = ChatSession()
        return {"reply": "Session reset! Let's start over. What can I get for you?"}

    if session.deal_closed:
        return {"reply": "We already closed a deal! Type 'reset' to start a new negotiation."}
    if session.deal_failed:
        return {"reply": "Our last negotiation didn't work out. Type 'reset' to start fresh!"}

    buyer_price_paise = extract_price_from_message(incoming_msg)
    if buyer_price_paise is not None:
        session.last_buyer_price_paise = buyer_price_paise

    buyer_msg = NegotiationMessage(
        role="buyer",
        message=incoming_msg.strip(),
        proposed_price=buyer_price_paise,
    )
    session.conversation.append(buyer_msg)
    session.round_number += 1

    # --- Audit: log every inbound buyer message ---
    negotiation_id = f"web-{session_id}"
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

    is_final_round = session.round_number >= 4
    try:
        merchant_response = session.merchant.generate_message(
            conversation_history=session.conversation,
            is_final_round=is_final_round,
        )
    except Exception as e:
        return {"reply": "Sorry, give me a moment to check my stock. Please try again!"}

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

    reply_text = merchant_response.message

    if merchant_response.proposed_price and not merchant_response.accepted:
        price_rupees = merchant_response.proposed_price / 100
        reply_text += f"\n\n*My offer: ₹{price_rupees:.0f}*"

    if merchant_response.final_offer and not merchant_response.accepted:
        reply_text += "\n_This is my final offer._"

    if merchant_response.accepted:
        agreed_price = (
            merchant_response.proposed_price
            or session.last_buyer_price_paise
            or session.merchant.floor_price
        )
        session.final_price_paise = agreed_price
        session.deal_closed = True
        reply_text += f"\n\n*DEAL! Final Price: ₹{agreed_price / 100:.0f}*"

        payment_url = create_payment_link(session, session_id)
        if payment_url:
            reply_text += f"\n\nComplete your payment here: {payment_url}"
        
        reply_text += "\n\n_Type 'reset' to start a new negotiation._"

    elif merchant_response.walk_away:
        session.deal_failed = True
        reply_text += "\n\n_I'm sorry we couldn't reach a deal today. Type 'reset' to try again!_"

    return {"reply": reply_text}


# ------------------------------------------------------------------
# P2: Agent-to-Agent Protocol Adapter (ACP - Agent Commerce Protocol)
# ------------------------------------------------------------------

class ACPRequest(BaseModel):
    buyer_agent_id: str
    sku: str
    proposed_price: float  # In Rupees
    message: str = ""

class ACPResponse(BaseModel):
    status: str  # "accepted", "rejected", "counter_offer"
    sku: str
    price: float
    message: str
    payment_link: str | None = None

@app.post("/api/agent-protocol", response_model=ACPResponse)
async def agent_protocol_adapter(request: ACPRequest):
    """
    Standardized endpoint for Agent-to-Agent Commerce.
    Other autonomous agents hit this to negotiate programmatically without natural language.
    """
    stack = get_guardrail_stack()
    session_id = f"acp-{request.buyer_agent_id}-{uuid.uuid4().hex[:6]}"
    
    # 1. Look up inventory via Guardrail Stack
    product = catalog.get_product(request.sku)
    if not product:
        return ACPResponse(status="rejected", sku=request.sku, price=0, message="SKU not found.")

    # 2. Run deterministic PriceGuard evaluation (Bypass LLM completely for speed/safety)
    check_result = stack.price_guard.authoritative_check(request.sku, request.proposed_price)
    
    stack.audit.log_guardrail(
        negotiation_id=session_id,
        check_type="agent_protocol_auth",
        sku=request.sku,
        checked_price=request.proposed_price,
        allowed=check_result.allowed,
        reason=check_result.reason
    )

    if check_result.allowed:
        # Deal accepted programmatically
        idempotency_key = make_idempotency_key(session_id, request.sku)
        try:
            result = stack.payment_gate.finalize_deal(
                negotiation_id=session_id,
                sku=request.sku,
                agreed_price=request.proposed_price,
                idempotency_key=idempotency_key
            )
            
            if result.success:
                return ACPResponse(
                    status="accepted",
                    sku=request.sku,
                    price=request.proposed_price,
                    message="Your proposed price is acceptable. Proceed to payment.",
                    payment_link=result.payment_link
                )
            else:
                return ACPResponse(
                    status="rejected",
                    sku=request.sku,
                    price=request.proposed_price,
                    message=f"Deal conditionally accepted but payment generation failed: {result.reason}"
                )
        except Exception as e:
            return ACPResponse(
                status="rejected",
                sku=request.sku,
                price=request.proposed_price,
                message=f"Deal accepted but payment generation failed: {str(e)}"
            )
    else:
        # Generate a structured counter-offer based on the rejected price
        counter_price = (product.price / 100) * 0.95  # Standard 5% off for agents
        return ACPResponse(
            status="counter_offer",
            sku=request.sku,
            price=counter_price,
            message=f"Proposed price rejected. Protocol counter-offer stands at ₹{counter_price}."
        )


@app.get("/api/dashboard")
async def dashboard_data():
    """API for global merchant metrics."""
    try:
        stack = get_guardrail_stack()
        return stack.audit.get_dashboard_metrics()
    except Exception as e:
        return {"error": str(e)}

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_ui():
    """Visual HTML wrapper for the Merchant Dashboard."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Merchant Dashboard - Agentic Storefront</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; padding: 20px; color: #333; max-width: 1000px; margin: 0 auto; }
            h1 { color: #1c1e21; border-bottom: 2px solid #ddd; padding-bottom: 10px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 20px; }
            .card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); text-align: center; border-top: 4px solid #075e54; }
            .card.alert { border-top-color: #d9534f; }
            .card h3 { margin: 0 0 10px 0; color: #666; font-size: 1em; text-transform: uppercase; letter-spacing: 1px; }
            .card .value { font-size: 2.5em; font-weight: bold; color: #333; }
            .card .sub { font-size: 0.9em; color: #888; margin-top: 5px; }
        </style>
    </head>
    <body>
        <h1>🏪 Storefront Explainability Dashboard</h1>
        
        <div id="content">Loading metrics...</div>

        <script>
            async function loadDashboard() {
                try {
                    const response = await fetch('/api/dashboard');
                    const data = await response.json();
                    
                    if (data.error) {
                        document.getElementById('content').innerHTML = '<p>Error loading dashboard.</p>';
                        return;
                    }

                    document.getElementById('content').innerHTML = `
                        <div class="grid">
                            <div class="card">
                                <h3>Total GMV</h3>
                                <div class="value">₹${data.gmv.toLocaleString('en-IN')}</div>
                                <div class="sub">Revenue secured autonomously</div>
                            </div>
                            <div class="card">
                                <h3>Win Rate</h3>
                                <div class="value">${data.win_rate_pct}%</div>
                                <div class="sub">${data.total_deals} deals won / ${data.total_negotiations} started</div>
                            </div>
                            <div class="card alert">
                                <h3>Injections Blocked</h3>
                                <div class="value">${data.blocked_injections}</div>
                                <div class="sub">Below-floor attempts stopped by Guardrails</div>
                            </div>
                            <div class="card">
                                <h3>Negotiation Speed</h3>
                                <div class="value">${data.avg_rounds}</div>
                                <div class="sub">Avg. rounds to reach a decision</div>
                            </div>
                        </div>
                    `;
                } catch (e) {
                    document.getElementById('content').innerHTML = '<p>Failed to load data.</p>';
                }
            }
            loadDashboard();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/api/audit/{negotiation_id}")
async def audit_trail(negotiation_id: str):
    """Read-only API endpoint returning raw JSON audit trail."""
    try:
        stack = get_guardrail_stack()
        trace = stack.audit.full_trace(negotiation_id)
        return trace
    except Exception as e:
        return {"error": str(e)}

@app.get("/audit/{negotiation_id}", response_class=HTMLResponse)
async def audit_trail_ui(negotiation_id: str):
    """Visual HTML wrapper for the audit trail."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Audit Trail: {neg_id}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f9f9f9; padding: 20px; color: #333; max-width: 800px; margin: 0 auto; }
            h1 { color: #075e54; }
            .section { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .event { border-left: 4px solid #075e54; margin-bottom: 15px; padding-left: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }
            .event:last-child { border-bottom: none; }
            .ts { font-size: 0.8em; color: #888; }
            .actor-buyer { color: #0275d8; font-weight: bold; }
            .actor-merchant { color: #5cb85c; font-weight: bold; }
            .actor-guardrail { color: #d9534f; font-weight: bold; }
            .actor-payment { color: #f0ad4e; font-weight: bold; }
            pre { background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <h1>Audit Trail Explorer</h1>
        <p><strong>Negotiation ID:</strong> {neg_id}</p>
        
        <div id="content">Loading audit data...</div>

        <script>
            async function loadAudit() {
                try {
                    const response = await fetch('/api/audit/{neg_id}');
                    const data = await response.json();
                    
                    if (data.error || Object.keys(data).length === 0) {
                        document.getElementById('content').innerHTML = '<p>Error loading or no data found.</p>';
                        return;
                    }

                    let html = '<div class="section"><h2>Negotiation Turns</h2>';
                    if (data.turns && data.turns.length > 0) {
                        data.turns.forEach(t => {
                            let actorClass = t.actor === 'buyer' ? 'actor-buyer' : 'actor-merchant';
                            html += `<div class="event">
                                <span class="ts">Round ${t.round_number}</span><br>
                                <span class="${actorClass}">${t.actor.toUpperCase()}</span> 
                                <em>${t.action}</em> 
                                ${t.proposed_price ? `(₹${t.proposed_price})` : ''}
                                <p>"${t.rationale}"</p>
                            </div>`;
                        });
                    } else { html += '<p>No turns recorded.</p>'; }
                    html += '</div>';

                    html += '<div class="section"><h2>Guardrail Events</h2>';
                    if (data.guardrail_events && data.guardrail_events.length > 0) {
                        data.guardrail_events.forEach(g => {
                            html += `<div class="event">
                                <span class="actor-guardrail">PRICE GUARD</span> <span class="ts">[${g.check_type}]</span><br>
                                SKU: ${g.sku} | Price Checked: ₹${g.checked_price} | Allowed: ${g.allowed ? '✅' : '❌'}<br>
                                <em>Reason: ${g.reason}</em>
                            </div>`;
                        });
                    } else { html += '<p>No guardrail events recorded.</p>'; }
                    html += '</div>';

                    html += '<div class="section"><h2>Payment Events</h2>';
                    if (data.payment_events && data.payment_events.length > 0) {
                        data.payment_events.forEach(p => {
                            html += `<div class="event">
                                <span class="actor-payment">PAYMENT GATE</span> <span class="ts">[${p.status.toUpperCase()}]</span><br>
                                SKU: ${p.sku} | Amount: ₹${p.amount} | Idempotency: ${p.idempotency_key}<br>
                                <em>Detail: ${p.detail}</em>
                            </div>`;
                        });
                    } else { html += '<p>No payment events recorded.</p>'; }
                    html += '</div>';

                    document.getElementById('content').innerHTML = html;
                } catch (e) {
                    document.getElementById('content').innerHTML = '<p>Failed to load data.</p>';
                }
            }
            loadAudit();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html.replace("{neg_id}", negotiation_id))

