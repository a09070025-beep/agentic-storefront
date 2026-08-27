import os
import uuid
from fastapi import APIRouter, HTTPException, Header, Response, status
from pydantic import BaseModel

# Assume catalog and stack are accessible from web_app.py context
# This file can be imported in web_app.py or we can just append it to web_app.py

x402_router = APIRouter()

@x402_router.get("/api/x402/purchase/{sku}")
async def x402_purchase(sku: str, authorization: str | None = Header(default=None)):
    """
    x402 (HTTP Payment Protocol) endpoint.
    Returns 402 Payment Required if no valid payment is provided.
    Returns 200 OK + Resource if payment is valid.
    """
    from web_app import catalog, get_guardrail_stack
    
    product = catalog.get_product(sku)
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    # If the agent has paid, they provide the payment ID or receipt in the Authorization header
    # e.g., Authorization: Payment pay_xyz123
    if authorization and authorization.startswith("Payment "):
        payment_id = authorization.split(" ")[1]
        
        # In a real scenario, we would verify the payment_id with Razorpay via payment_gate
        # For this stub, we'll assume any non-empty payment ID after 'Payment ' is a proof of payment
        if len(payment_id) > 5:
            return {
                "status": "delivered",
                "resource": f"Secure digital resource for {product.name}",
                "receipt": payment_id
            }

    # If not paid, initiate payment gate and return 402
    stack = get_guardrail_stack()
    session_id = f"x402-{uuid.uuid4().hex[:8]}"
    
    # We use the standard retail price (in rupees) for instant purchase via x402
    price = product.price / 100
    
    try:
        result = stack.payment_gate.finalize_deal(
            negotiation_id=session_id,
            sku=sku,
            agreed_price=price,
            idempotency_key=session_id
        )
        
        if result.success:
            # The protocol dictates returning HTTP 402 with the payment link
            return Response(
                content=f'{{"error": "Payment Required", "payment_link": "{result.payment_link}", "price": {price}}}',
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                media_type="application/json",
                headers={"X-Payment-Required": result.payment_link}
            )
        else:
            raise HTTPException(status_code=500, detail=f"Failed to generate payment link: {result.reason}")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
