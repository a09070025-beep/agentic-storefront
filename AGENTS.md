# AGENTS.md — Agentic Storefront (Razorpay AI Buildathon, Track 01)

## What this project is

"Agentic Storefront" — a self-optimizing agentic commerce demo built for
Razorpay's AI Buildathon, Track 01 (AI Growth & Agentic Commerce).

Core pieces already built (see /legacy or wherever the existing app code
lives once merged into this repo):
- Negotiation Arena: buyer (human or AI persona) negotiates with a
  Merchant AI over chat/WhatsApp.
- Merchant AI (Gemini): sales agent that knows product info, negotiates,
  upsells, and closes deals.
- Buyer AI Personas: adversarial simulated buyers used for testing.
- Agentic Self-Improvement Loop: an Evaluator AI scores the Merchant AI's
  performance against simulated negotiations and rewrites its system
  prompt to improve.
- Smart Upsell & Bundle Engine, Scarcity & Emotion Engines.
- Razorpay integration via an MCP server (catalog search, cart building,
  payment link generation).
- WhatsApp bot via Twilio + FastAPI.

## New guardrail layer (in /agentic_storefront_guardrails)

This folder was added after an architecture review flagged real security
and reliability gaps (see HANDOFF_TASKS.md for the full list). It is a
tested, runnable set of modules — `python demo_run.py` inside that folder
to see it work end to end before touching the integration.

## Non-negotiable rules for any agent working in this repo

1. **The LLM never sees or holds the cost floor.** The floor lives only
   in `guardrails.py`'s `ProductCatalog`. The Merchant AI may only learn
   whether a price is allowed via the `check_price` tool, which returns
   `{allowed, reason}` and nothing else. Do not refactor this so the
   floor ends up in a prompt, a log visible to the buyer, or a tool
   response the buyer-facing side can read.

2. **No payment link is ever created without going through
   `PaymentGate.finalize_deal()`.** Do not add a second code path that
   calls the Razorpay/MCP `create_payment_link` tool directly. If a new
   integration point needs to create a link, it wires into `PaymentGate`,
   it does not bypass it.

3. **Every money-relevant event gets logged via `AuditLog`.** Negotiation
   turns, guardrail decisions, and payment events all go through
   `audit_log.py`. This is not optional logging — it's evidence for the
   buildathon judging bar ("every money action explainable, bounded and
   gated... show the audit trail").

4. **Self-improvement prompt changes go through `PromptRegistry`.** The
   Evaluator AI's rewritten prompts are staged candidates, evaluated
   against a held-out persona set, and only promoted if they beat
   production by the configured margin. No code path should let a
   rewritten prompt go directly into the live Merchant AI's system
   prompt without passing through `evaluate_and_promote()`.

5. **Prefer deterministic checks over prompting for anything involving
   money, inventory, or identity.** If you're tempted to fix a bug by
   adding a sentence to a system prompt ("never do X"), stop and ask
   whether X should instead be impossible at the code level.

## Working style

- Read `HANDOFF_TASKS.md` before starting; it's the prioritized list of
  what to fix and why, drawn from an external architecture review.
- Read `agentic_storefront_guardrails/README.md` before integrating the
  guardrail modules into the existing negotiation/payment code.
- Run `python demo_run.py` in the guardrails folder to confirm the
  baseline works before you start modifying it.
- After integrating, re-run (or extend) the three demo scenarios
  (normal deal / blocked injection / retried gateway failure) against
  the real Merchant AI and Razorpay MCP call, not just the stubs.
