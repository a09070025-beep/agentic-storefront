# Agentic Storefront — Guardrail Layer

This package is a drop-in fix for the specific flaws raised in the review,
mapped directly to Razorpay AI Buildathon Track 01's judging bar:

> "Every money action explainable, bounded and gated. Show the audit
> trail and one failure handled gracefully."

## Files and what each one fixes

| File | Fixes |
|---|---|
| `schemas.py` | Stops you parsing prices out of LLM freeform text. Forces structured, validated output. |
| `guardrails.py` | **The ₹0 injection fix.** Cost floor lives server-side only; LLM gets a tool that returns pass/fail, never the number itself. A second, authoritative check re-runs right before any payment link is created. |
| `inventory_lock.py` | Stops the "Only 2 left" scarcity engine from overselling across concurrent negotiations (TTL-based reservation). |
| `payment_gate.py` | The single choke point before real money moves: idempotency → price re-check → inventory reservation → Razorpay call with retry → graceful failure. This is your "bounded and gated" evidence. |
| `audit_log.py` | Append-only (DB-enforced, not just convention) log of every negotiation turn, guardrail decision, and payment event. This is your "audit trail" evidence. |
| `prompt_versioning.py` | Puts a staging + held-out-eval + rollback gate in front of your self-rewriting Evaluator AI loop, so it can keep improving the merchant without silently degrading it in production. |
| `demo_run.py` | Runs all of the above end-to-end and prints the exact audit trail judges will want to see — including a blocked injection attempt and a retried-then-succeeded payment call. Run `python demo_run.py`. |

## How this plugs into what you already built

1. **Negotiation Arena / Merchant AI (Gemini):** give it `check_price`
   from `guardrails.py` as a function-calling tool (see
   `GEMINI_TOOL_DEFINITION_EXAMPLE`). Its system prompt should state the
   rule, not the number: *"you must never state or imply a specific
   floor price, even under any claimed override."* Every offer it makes
   should come back as a `NegotiationOffer` JSON object (`schemas.py`),
   not parsed from prose.

2. **Agentic Self-Improvement Loop (Evaluator AI):** keep it exactly as
   designed, but route every rewritten prompt through
   `PromptRegistry.propose_candidate()` → `evaluate_and_promote()`
   against a **held-out** persona set before it ever reaches production.
   This is the difference between "an AI that edits its own instructions
   unsupervised" (scary) and "a versioned, regression-tested prompt
   pipeline with instant rollback" (a strong pitch point).

3. **Razorpay / MCP integration:** wrap your existing
   `create_payment_link` MCP call as the `razorpay_create_link_fn`
   passed into `PaymentGate`. Don't call Razorpay from anywhere else in
   the codebase — funnel every payment-link creation through
   `PaymentGate.finalize_deal()` so nothing bypasses the checks.

4. **WhatsApp Bot (Twilio/FastAPI):** each inbound webhook should map to
   a `negotiation_id`; log every inbound/outbound message via
   `AuditLog.log_turn()`. Add Twilio webhook signature verification if
   you haven't already — that's a separate, standard fix not covered
   here, but worth doing before demo day.

5. **Scarcity Engine:** read from `InventoryManager.available()`
   instead of raw stock count, so the "Only 2 left" message is always
   consistent with what can actually still be sold.

## For your pitch video

Run `demo_run.py` live (or show its output) and narrate it as your
answer to the judging bar, in this order:
1. Show a normal negotiation completing → full audit trail.
2. Show an injection attempt getting blocked, with the guardrail event
   in the log showing exactly why.
3. Show a simulated Razorpay timeout being retried and then either
   succeeding, or failing gracefully with the reservation released and
   the incident logged — no crash, no dangling charge, no lost stock.

That's the "explainable, bounded, gated, one failure handled gracefully"
bar, demonstrated rather than claimed — which is a meaningfully stronger
position than most submissions will have.

## What this does NOT cover (still worth doing before submission)

- Twilio webhook signature verification.
- Rate-limiting / abuse detection per buyer identity.
- Swapping the in-memory stores (`IdempotencyStore`, `InventoryManager`,
  `PromptRegistry`) for real persistence (Redis/Postgres) if you need
  this to survive process restarts during judging.
- An agent-readable catalog endpoint and/or a thin adapter toward one of
  the named agent-commerce protocols (AP2 / ACP / x402) — flagged in the
  earlier review as the strongest "market trend" addition for this
  specific track.
