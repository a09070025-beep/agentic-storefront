import os
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import get_settings
from src.catalog import CatalogStore
from src.merchant_ai import MerchantAI, NegotiationMessage
from src.razorpay_service import RazorpayService

app = FastAPI(title="Agentic Storefront - Web UI")

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
        self.merchant = MerchantAI(products=products, catalog=catalog)
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

def create_payment_link(session: ChatSession) -> str | None:
    try:
        url = razorpay_service.create_payment_link(
            amount_paise=session.final_price_paise,
            reference_id=f"order_{uuid.uuid4().hex[:8]}",
            description="Agentic Storefront Purchase",
            customer_name="Valued Customer",
            customer_contact="+919999999999",
            customer_email="customer@example.com"
        )
        return url
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

    is_final_round = session.round_number >= 4
    try:
        merchant_response = session.merchant.generate_message(
            conversation_history=session.conversation,
            is_final_round=is_final_round,
        )
    except Exception as e:
        return {"reply": "Sorry, give me a moment to check my stock. Please try again!"}

    session.conversation.append(merchant_response)
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

        payment_url = create_payment_link(session)
        if payment_url:
            reply_text += f"\n\nComplete your payment here: {payment_url}"
        
        reply_text += "\n\n_Type 'reset' to start a new negotiation._"

    elif merchant_response.walk_away:
        session.deal_failed = True
        reply_text += "\n\n_I'm sorry we couldn't reach a deal today. Type 'reset' to try again!_"

    return {"reply": reply_text}
