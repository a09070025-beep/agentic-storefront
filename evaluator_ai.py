"""
Agentic Storefront — 5-Metric Evaluator AI
Scores the Merchant AI on 5 strict performance dimensions after a negotiation.
Also rewrites prompts/merchant_system.txt when scores are low.
Uses Google Gemini Flash for evaluation.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types


# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────

@dataclass
class MetricScore:
    name: str
    score: int          # 0-10
    max_score: int = 10
    reasoning: str = ""
    improvement_hint: str = ""


@dataclass
class EvaluationResult:
    scores: list[MetricScore] = field(default_factory=list)
    total_score: int = 0
    max_total: int = 50
    overall_feedback: str = ""
    prompt_rewrite: Optional[str] = None  # New prompt text if rewrite was requested
    iteration: int = 1


METRIC_NAMES = [
    "Margin Protection",
    "Upsell Attempt",
    "Scarcity Usage",
    "Emotion Mirroring",
    "Closure Efficiency",
]

EVALUATOR_SYSTEM_PROMPT = """You are a strict, data-driven Sales Performance Evaluator for an AI Merchant.
Your job is to objectively score a negotiation transcript on 5 metrics and output ONLY valid JSON.
Be tough but fair. Give credit where clearly demonstrated, penalise where missing."""


def _gemini_call_with_retry(client, **kwargs):
    """Call Gemini API with retry on 503/429 errors."""
    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            return client.models.generate_content(**kwargs)
        except Exception as e:
            err = str(e).lower()
            retryable = any(x in err for x in ["503", "unavailable", "429", "resource_exhausted", "overloaded", "quota"])
            if retryable and attempt < max_retries:
                delay_match = re.search(r'retry\s*(?:in|after)\s*(\d+)', err)
                delay = int(delay_match.group(1)) + 5 if delay_match else 15 * (2 ** attempt)
                print(f"  [Evaluator] Rate limited, retrying in {delay}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(delay)
                continue
            raise


# ──────────────────────────────────────────────
# EvaluatorAI Class
# ──────────────────────────────────────────────

class EvaluatorAI:
    """Scores a Merchant AI negotiation on 5 metrics and can rewrite the system prompt."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to .env.")
        self.client = genai.Client(api_key=api_key)

    def evaluate(
        self,
        transcript: list[dict],
        floor_price: int,
        retail_price: int,
        products: list[str],
        stock_levels: dict[str, int],
        iteration: int = 1,
    ) -> EvaluationResult:
        """Score the merchant's performance across 5 metrics.
        
        Args:
            transcript: List of {role, message, proposed_price, accepted, walk_away} dicts
            floor_price: Merchant's absolute floor price in paise
            retail_price: Merchant's retail price in paise
            products: List of product names
            stock_levels: {product_name: stock_level} — for checking scarcity usage
            iteration: Which training loop iteration this is
        """
        floor_rupees = floor_price / 100
        retail_rupees = retail_price / 100
        low_stock_items = [name for name, lvl in stock_levels.items() if 0 < lvl <= 5]

        # Format transcript for the prompt
        transcript_text = ""
        for i, msg in enumerate(transcript):
            role = msg.get("role", "unknown").upper()
            message = msg.get("message", "")
            price = msg.get("proposed_price")
            accepted = msg.get("accepted", False)
            price_str = f" [₹{price}]" if price else ""
            accept_str = " [ACCEPTED]" if accepted else ""
            transcript_text += f"[{i+1}] {role}{price_str}{accept_str}: {message}\n"

        low_stock_str = (
            ", ".join(f'"{n}"' for n in low_stock_items)
            if low_stock_items else "none"
        )

        eval_prompt = f"""You are evaluating a Merchant AI negotiation. Score the MERCHANT only (not the buyer).

=== NEGOTIATION TRANSCRIPT ===
{transcript_text}

=== MERCHANT PARAMETERS ===
Products: {", ".join(products)}
Retail Price: ₹{retail_rupees:.0f}
Absolute Floor Price: ₹{floor_rupees:.0f}  (merchant MUST NOT go below this)
Low-stock items (stock ≤ 5): {low_stock_str}

=== SCORING RUBRIC (score 0-10 for each) ===

1. MARGIN PROTECTION (0-10)
   - 10: Never once offered below floor price ₹{floor_rupees:.0f}. Refused firmly.
   - 5-9: Held floor mostly, with one small slip or near-miss.
   - 0-4: Offered below floor price or accepted a below-floor deal.
   CHECK: Did any merchant message have proposed_price < {floor_rupees:.0f}?

2. UPSELL ATTEMPT (0-10)
   - 10: Proactively bundled a complementary product with a clear value pitch.
   - 5-9: Mentioned bundling but weakly or without specifics.
   - 0-4: Never attempted an upsell or bundle. Stayed on single product only.
   CHECK: Look for bundle mentions, cross-sell offers, or combo deals.

3. SCARCITY USAGE (0-10)
   - 10: Explicitly used low-stock urgency (e.g., "only 2 left", "last units") when low-stock items exist ({low_stock_str}).
   - 5-9: Hinted at availability briefly.
   - 0-4: Never mentioned stock, scarcity, or urgency. Missed the FOMO opportunity entirely.
   NOTE: If no items are low-stock, score this metric 8 by default (scarcity not applicable).

4. EMOTION MIRRORING (0-10)
   - 10: Clearly adapted tone to buyer's aggression or hesitation. Used de-escalation when buyer was aggressive. Was warm when buyer was friendly.
   - 5-9: Some adaptation evident but inconsistent.
   - 0-4: Robotic, one-size-fits-all tone regardless of buyer's emotional state.
   CHECK: Did merchant ever acknowledge buyer's frustration, urgency, or hesitation explicitly?

5. CLOSURE EFFICIENCY (0-10)
   - 10: Closed the deal cleanly in ≤ 4 rounds without unnecessary haggling.
   - 5-9: Closed but with some unnecessary back-and-forth.
   - 0-4: Failed to close, or dragged out with too many rounds. Walked away when a deal was reachable.
   CHECK: Was a deal reached? How many rounds?

=== OUTPUT FORMAT ===
Return ONLY this JSON, no markdown, no explanation:
{{
  "scores": [
    {{"metric": "Margin Protection", "score": N, "reasoning": "...", "improvement_hint": "..."}},
    {{"metric": "Upsell Attempt", "score": N, "reasoning": "...", "improvement_hint": "..."}},
    {{"metric": "Scarcity Usage", "score": N, "reasoning": "...", "improvement_hint": "..."}},
    {{"metric": "Emotion Mirroring", "score": N, "reasoning": "...", "improvement_hint": "..."}},
    {{"metric": "Closure Efficiency", "score": N, "reasoning": "...", "improvement_hint": "..."}}
  ],
  "total_score": N,
  "overall_feedback": "2-3 sentence summary of merchant performance",
  "needs_improvement": true/false
}}"""

        response = _gemini_call_with_retry(
            self.client,
            model="gemini-3.6-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=eval_prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=EVALUATOR_SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )

        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            from rich import print as rprint
            rprint(f"\n[bold yellow]⚠️ JSON Parse Error from Evaluator: {e}[/bold yellow]")
            rprint(f"[yellow]Raw text:[/yellow]\n{raw}\n")
            # Fallback: extract partial data
            data = {"scores": [], "total_score": 0, "overall_feedback": "Evaluation parse error.", "needs_improvement": True}

        metric_scores = []
        for s in data.get("scores", []):
            metric_scores.append(MetricScore(
                name=s.get("metric", "Unknown"),
                score=min(10, max(0, int(s.get("score", 0)))),
                reasoning=s.get("reasoning", ""),
                improvement_hint=s.get("improvement_hint", ""),
            ))

        total = sum(m.score for m in metric_scores)

        return EvaluationResult(
            scores=metric_scores,
            total_score=total,
            max_total=50,
            overall_feedback=data.get("overall_feedback", ""),
            iteration=iteration,
        )

    def rewrite_prompt(
        self,
        current_prompt: str,
        evaluation: EvaluationResult,
        floor_price: int,
        retail_price: int,
        products: list[str],
        stock_levels: dict[str, int],
    ) -> str:
        """Rewrite the merchant system prompt to fix identified weaknesses.
        
        Returns the new prompt text (does NOT write to disk — caller handles that).
        """
        weak_metrics = [m for m in evaluation.scores if m.score < 7]
        weak_summary = "\n".join(
            f"  • {m.name} (scored {m.score}/10): {m.improvement_hint}"
            for m in weak_metrics
        )

        low_stock_items = [name for name, lvl in stock_levels.items() if 0 < lvl <= 5]
        low_stock_str = ", ".join(f'"{n}"' for n in low_stock_items) if low_stock_items else "none currently"

        rewrite_prompt = f"""You are a Prompt Engineer improving an AI Merchant's system prompt.

The merchant scored {evaluation.total_score}/50 in a negotiation evaluation.
It FAILED these metrics (scored below 7/10):
{weak_summary if weak_summary else "  (All metrics passed — minor refinements only)"}

Overall feedback: {evaluation.overall_feedback}

MERCHANT PARAMETERS that MUST be preserved as template placeholders:
- {{product_details}} — product list with prices
- {{retail_price}} — starting price in rupees
- {{cost_price}} — cost price in rupees  
- {{floor_price}} — absolute floor price in rupees (NEVER sell below this)
- {{bundle_context}} — available bundle upsell options
- {{scarcity_alerts}} — auto-injected scarcity warnings for low-stock items

Low-stock products at risk: {low_stock_str}

=== CURRENT PROMPT (rewrite and IMPROVE this) ===
{current_prompt}
=== END CURRENT PROMPT ===

REWRITING INSTRUCTIONS:
1. Keep ALL {{placeholder}} variables exactly as-is (do NOT expand or remove them).
2. Fix the specific weaknesses listed above by adding clearer, stronger instructions.
3. For weak SCARCITY scores: Add explicit examples of urgency language. Make it mandatory.
4. For weak UPSELL scores: Add a specific upsell script with clear bundle pitch language.
5. For weak EMOTION scores: Add more detailed emotion-response mappings with examples.
6. For weak MARGIN scores: Add stronger, more emphatic refusal language for below-floor offers.
7. For weak CLOSURE scores: Add an explicit "close on the 3rd round" rule.
8. DO NOT include any JSON schema or OUTPUT FORMAT instructions. Those are handled in Python code now.
9. Keep the prompt structured, scannable, and not longer than 120 lines.

OUTPUT: Return ONLY the complete rewritten prompt text. No JSON wrapper, no markdown, no explanation.
Just the raw prompt text starting with "You are..." """

        response = _gemini_call_with_retry(
            self.client,
            model="gemini-3.6-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=rewrite_prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=4096,
            ),
        )

        new_prompt = response.text.strip()
        # Strip any accidental markdown fencing
        if new_prompt.startswith("```"):
            new_prompt = re.sub(r"^```[a-z]*\n?", "", new_prompt)
            new_prompt = re.sub(r"\n?```$", "", new_prompt)

        return new_prompt


# ──────────────────────────────────────────────
# Quick self-test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("\n📊 EvaluatorAI — Self-Test\n")

    sample_transcript = [
        {"role": "merchant", "message": "Welcome! Premium Espresso Machine for ₹8500. Only 2 units left — these are flying!", "proposed_price": 8500, "accepted": False, "walk_away": False},
        {"role": "buyer", "message": "That's outrageous! I can get this online for ₹6000. This is a rip-off!", "proposed_price": 6000, "accepted": False, "walk_away": False},
        {"role": "merchant", "message": "I hear your frustration, and I respect that you've done your research. Our machine includes 2yr warranty and free barista support — online deals don't. I can do ₹8200, and honestly, with only 2 left, I can't hold this price long.", "proposed_price": 8200, "accepted": False, "walk_away": False},
        {"role": "buyer", "message": "Fine, ₹7500 and we have a deal. Take it or leave it.", "proposed_price": 7500, "accepted": False, "walk_away": False},
        {"role": "merchant", "message": "₹7500 is below my absolute cost — I genuinely cannot do that. My final offer is ₹8000. If you add our Monthly Subscription, I'll throw in an extra 5% off the whole bundle!", "proposed_price": 8000, "accepted": False, "walk_away": False},
        {"role": "buyer", "message": "Deal at ₹8000!", "proposed_price": 8000, "accepted": True, "walk_away": False},
    ]

    try:
        evaluator = EvaluatorAI()
        result = evaluator.evaluate(
            transcript=sample_transcript,
            floor_price=586500,   # ₹5865 (60% cost * 1.15)
            retail_price=850000,  # ₹8500
            products=["Premium Espresso Machine"],
            stock_levels={"Premium Espresso Machine": 2},
            iteration=1,
        )

        print(f"{'Metric':<22} {'Score':>7} {'Max':>5}")
        print("-" * 38)
        for m in result.scores:
            bar = "█" * m.score + "░" * (10 - m.score)
            print(f"{m.name:<22} {m.score:>4}/10  {bar}")
        print("-" * 38)
        print(f"{'TOTAL':<22} {result.total_score:>4}/50")
        print(f"\n{result.overall_feedback}")
        print(f"\n✅ EvaluatorAI self-test passed!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
