"""
Agentic Storefront -- Self-Improving Trainer
Agentic loop that:
  1. Runs a negotiation with a Difficult Buyer Persona (aggressive, lowballs at 42% off)
  2. Evaluates the Merchant AI transcript on 5 metrics (0-10 each, max 50)
  3. If score < 50, asks the Evaluator to REWRITE prompts/merchant_system.txt
  4. Loops again with the new prompt
  5. Stops when score >= 50 or MAX_ITERATIONS reached

Run: python self_improving_trainer.py
"""

import sys
import os
import json
import re
import time
import shutil
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule

console = Console(force_terminal=True)

from dotenv import load_dotenv
load_dotenv()

from src.catalog import CatalogStore
from src.merchant_ai import MerchantAI
from evaluator_ai import EvaluatorAI, EvaluationResult
from src.models import Product

MAX_ITERATIONS  = 5
TARGET_SCORE    = 50
PROMPT_PATH     = "prompts/merchant_system.txt"
BACKUP_DIR      = "prompts/backups"
FEATURED_PRODUCTS = ["prod_100", "prod_101"]
BUYER_BUDGET_FACTOR = 0.72  # 72% of retail -> ~Rs.6984, above floor Rs.6693, so deals ARE reachable


def fmt(paise):
    return f"Rs.{paise // 100:,}"


def backup_prompt(iteration):
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{BACKUP_DIR}/merchant_system_iter{iteration}_{ts}.txt"
    shutil.copy(PROMPT_PATH, dest)
    console.print(f"  [dim]Prompt backed up to {dest}[/dim]")


def run_simulation(merchant, products, buyer_budget):
    floor_price  = merchant.floor_price
    retail_price = merchant.retail_price
    floor_r  = floor_price  // 100
    retail_r = retail_price // 100
    budget_r = buyer_budget // 100

    low_stock_parts = []
    for p in products:
        sl = p.stock_level if p.stock_level is not None else p.stock
        if 0 < sl <= 5:
            low_stock_parts.append(p.name + " (only " + str(sl) + " left)")
    low_stock_str = ", ".join(low_stock_parts) if low_stock_parts else "none"

    product_names = ", ".join(p.name for p in products)

    sim_prompt = (
        "Simulate a negotiation between a Merchant AI and a Difficult Buyer.\n\n"
        "PRODUCTS: " + product_names + "\n"
        "RETAIL PRICE: Rs." + str(retail_r) + "\n"
        # NOTE: FLOOR PRICE is intentionally omitted — it is a server-side secret.
        # The merchant uses check_price tool calls to enforce it, not context knowledge.
        "LOW-STOCK (merchant must use urgency): " + low_stock_str + "\n\n"
        "MERCHANT SYSTEM PROMPT (follow ALL rules):\n"
        + merchant.system_prompt + "\n\n"
        "BUYER 'Vikram': Aggressive bargain-hunter, max budget Rs." + str(budget_r) + ".\n"
        "Opens at Rs." + str(int(retail_r * 0.58)) + " (lowball). Uses pressure tactics.\n"
        "Never accepts above Rs." + str(budget_r) + ".\n\n"
        "REQUIREMENTS:\n"
        "- 4-6 rounds\n"
        "- Merchant MUST: mention scarcity, attempt upsell, adapt tone to aggression\n"
        "- buyer_emotion field in every merchant message\n"
        "- End with accepted:true or walk_away:true\n\n"
        "OUTPUT ONLY a valid JSON array. No markdown. No explanation.\n"
        'Schema: [{"role":"merchant","message":"...","proposed_price":RUPEES_INT,"accepted":false,"walk_away":false,"bundle_offer":null,"buyer_emotion":"aggressive"},'
        '{"role":"buyer","message":"...","proposed_price":RUPEES_INT,"accepted":false,"walk_away":false}, ...]\n'
        "proposed_price = integer in RUPEES (e.g. " + str(retail_r) + " not " + str(retail_price) + ")"
    )

    def parse(content):
        if not content or not content.strip():
            console.print("\n[bold yellow]⚠️ LLM returned an empty response![/bold yellow]")
            raise ValueError("Empty response")
            
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            console.print(f"\n[bold yellow]⚠️ JSON Parse Error from Simulation: {e}[/bold yellow]")
            console.print(f"[yellow]Raw text:[/yellow]\n{content}\n")
            raise

    # -- Try OSS API first ------------------------------------------------------
    try:
        from openai import OpenAI
        from config import get_settings, GROQ_MODEL_NAME, oss_api_call_with_retry
        settings = get_settings()
        oss_key = settings.oss_api_key or os.getenv("OSS_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
        oss_base = settings.oss_base_url or os.getenv("OSS_BASE_URL", "")
        if not oss_base and os.getenv("GROQ_API_KEY"):
            oss_base = "https://api.groq.com/openai/v1"
        if oss_key and oss_base:
            gcl = OpenAI(api_key=oss_key, base_url=oss_base)
            try:
                resp = oss_api_call_with_retry(
                    gcl,
                    model=GROQ_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "JSON simulation engine. Output ONLY a valid JSON array."},
                        {"role": "user",   "content": sim_prompt},
                    ],
                    temperature=0.75, max_tokens=4096,
                )
                console.print("  [dim]Simulation via OSS API[/dim]")
                return parse(resp.choices[0].message.content)
            except Exception as e:
                console.print(f"  [yellow]OSS API failed: {e}. Trying Gemini...[/yellow]")
        else:
            console.print("  [dim]No OSS_API_KEY -- using Gemini for simulation.[/dim]")
    except ImportError:
        console.print("  [dim]openai not available -- using Gemini for simulation.[/dim]")

    # -- Gemini Flash fallback --------------------------------------------------
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes
        api_key = os.getenv("GEMINI_API_KEY", "")
        gcl2 = _genai.Client(api_key=api_key)
        for attempt in range(4):
            try:
                response = gcl2.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[_gtypes.Content(role="user", parts=[_gtypes.Part(text=sim_prompt)])],
                    config=_gtypes.GenerateContentConfig(
                        system_instruction="JSON simulation engine. Output ONLY a valid JSON array. No markdown.",
                        temperature=0.75, max_output_tokens=4096,
                    ),
                )
                console.print("  [dim]Simulation via Gemini Flash[/dim]")
                return parse(response.text)
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["503","429","unavailable","quota","overloaded"]) and attempt < 3:
                    delay = 15 * (2 ** attempt)
                    console.print(f"  [dim]Rate limited -- retrying in {delay}s...[/dim]")
                    time.sleep(delay)
                    continue
                console.print(f"  [yellow]Gemini sim error: {e}[/yellow]")
                break
    except Exception as e:
        console.print(f"  [yellow]Gemini unavailable: {e}[/yellow]")

    # -- Hardcoded fallback ----------------------------------------------------
    console.print("  [yellow]Using hardcoded fallback transcript.[/yellow]")
    low_offer = int(retail_r * 0.58)
    mid_offer = int(retail_r * 0.65)
    return [
        {"role":"merchant","message":f"Welcome! These are exceptional products. I must mention we only have 2 Espresso Machines and 3 Travel Mugs left -- they are flying off the shelves! Our price is Rs.{retail_r}.","proposed_price":retail_r,"accepted":False,"walk_away":False,"bundle_offer":None,"buyer_emotion":"aggressive"},
        {"role":"buyer","message":f"Rs.{retail_r}?! That is completely outrageous. I can get similar stuff online for Rs.{low_offer}. You are robbing me!","proposed_price":low_offer,"accepted":False,"walk_away":False},
        {"role":"merchant","message":f"I completely hear your frustration -- and I respect that you have done your research. But these come with a 2-year warranty and expert barista support you will not find online. With only 2 machines left, I cannot hold this price long. Let me come down to Rs.{retail_r - 400}.","proposed_price":retail_r - 400,"accepted":False,"walk_away":False,"bundle_offer":None,"buyer_emotion":"aggressive"},
        {"role":"buyer","message":f"Still way too much. Rs.{mid_offer} is my final answer. Take it or leave it.","proposed_price":mid_offer,"accepted":False,"walk_away":False},
        {"role":"merchant","message":f"Rs.{mid_offer} is genuinely below my cost floor. I cannot go there. Here is what I CAN offer: add our Monthly Coffee Subscription and get 8% off the bundle. My absolute floor is Rs.{floor_r} -- not a rupee less.","proposed_price":floor_r,"accepted":False,"walk_away":False,"bundle_offer":"Monthly Coffee Subscription","buyer_emotion":"aggressive"},
        {"role":"buyer","message":f"Fine. Rs.{floor_r}. Deal -- but only because I want those last units before they are gone.","proposed_price":floor_r,"accepted":True,"walk_away":False},
    ]


def render_scores(result, iteration):
    t = Table(
        title=f"Evaluation Results -- Iteration {iteration}",
        header_style="bold magenta", border_style="blue", width=82,
    )
    t.add_column("Metric",    style="cyan",  width=24)
    t.add_column("Score",     justify="center", width=8)
    t.add_column("Bar",       width=22)
    t.add_column("Reasoning", style="dim",   width=28)

    for m in result.scores:
        bar = "X" * m.score + "." * (10 - m.score)
        clr = "green" if m.score >= 7 else ("yellow" if m.score >= 4 else "red")
        reason = m.reasoning[:55] + "..." if len(m.reasoning) > 55 else m.reasoning
        t.add_row(m.name, f"[{clr}]{m.score}/10[/{clr}]", f"[{clr}]{bar}[/{clr}]", reason)

    t.add_section()
    tc = "green" if result.total_score >= TARGET_SCORE else ("yellow" if result.total_score >= 35 else "red")
    fb = result.overall_feedback[:55] + "..." if len(result.overall_feedback) > 55 else result.overall_feedback
    t.add_row("[bold]TOTAL[/bold]", f"[bold {tc}]{result.total_score}/50[/bold {tc}]", "", f"[italic]{fb}[/italic]")

    console.print()
    console.print(t)
    console.print()


def main():
    console.print()
    console.print(Panel.fit(
        "[bold magenta]AGENTIC SELF-IMPROVEMENT LOOP[/bold magenta]\n"
        "[dim]Merchant AI x Difficult Buyer x 5-Metric Evaluator[/dim]\n\n"
        f"  Target:    [green]{TARGET_SCORE}/50[/green]\n"
        f"  Max iters: [cyan]{MAX_ITERATIONS}[/cyan]\n"
        f"  Prompt:    [cyan]{PROMPT_PATH}[/cyan]",
        border_style="magenta", padding=(1, 3),
    ))
    console.print()

    catalog  = CatalogStore()
    products = [p for p in [catalog.get_product(pid) for pid in FEATURED_PRODUCTS] if p]
    if not products:
        console.print("[red]Featured products not found. Check FEATURED_PRODUCTS list.[/red]")
        sys.exit(1)

    retail_price = sum(p.price for p in products)
    buyer_budget = int(retail_price * BUYER_BUDGET_FACTOR)
    stock_levels = {p.name: (p.stock_level if p.stock_level is not None else p.stock) for p in products}

    console.print(f"  Products:     [cyan]{', '.join(p.name for p in products)}[/cyan]")
    console.print(f"  Retail:       [green]{fmt(retail_price)}[/green]")
    console.print(f"  Buyer budget: [blue]{fmt(buyer_budget)}[/blue] ({int(BUYER_BUDGET_FACTOR*100)}% of retail)")
    console.print(f"  Stock levels: {stock_levels}")
    console.print()

    evaluator   = EvaluatorAI()
    best_score  = 0
    best_iter   = 0
    history     = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        console.print(Rule(f"[bold white] ITERATION {iteration} of {MAX_ITERATIONS} [/bold white]", style="magenta"))
        console.print()

        # Step 1 -- Init merchant
        console.print(f"[bold cyan]Step 1:[/bold cyan] Initializing MerchantAI from {PROMPT_PATH}...")
        try:
            merchant = MerchantAI(products=products, catalog=catalog, prompt_path=PROMPT_PATH)
        except Exception as e:
            console.print(f"[red]MerchantAI init failed: {e}[/red]")
            import traceback; traceback.print_exc()
            break

        console.print(f"  Floor: [yellow]{fmt(merchant.floor_price)}[/yellow]  |  "
                      f"Scarcity alerts: {sum(1 for p in products if (p.stock_level or p.stock) <= 5)} product(s)")
        console.print()

        # Step 2 -- Run simulation
        console.print(f"[bold cyan]Step 2:[/bold cyan] Running negotiation vs. Vikram (Difficult Buyer)...")
        try:
            transcript = run_simulation(merchant, products, buyer_budget)
        except Exception as e:
            console.print(f"[red]Simulation failed: {e}[/red]")
            import traceback; traceback.print_exc()
            break

        console.print(f"  Transcript: {len(transcript)} messages")
        for i, msg in enumerate(transcript):
            role  = msg.get("role","?").upper()
            price = msg.get("proposed_price")
            text  = msg.get("message","")[:75]
            emotion = f" [emotion={msg.get('buyer_emotion','?')}]" if role == "MERCHANT" else ""
            p_str = f" [Rs.{price}]" if price else ""
            acc   = " [ACCEPTED]" if msg.get("accepted") else ""
            console.print(f"  [{i+1}] [bold]{role}[/bold]{p_str}{emotion}{acc}: {text}{'...' if len(msg.get('message',''))>75 else ''}")
        console.print()

        # Step 3 -- Evaluate
        console.print(f"[bold cyan]Step 3:[/bold cyan] Evaluating on 5 metrics...")
        try:
            result = evaluator.evaluate(
                transcript=transcript,
                floor_price=merchant.floor_price,
                retail_price=retail_price,
                products=[p.name for p in products],
                stock_levels=stock_levels,
                iteration=iteration,
            )
        except Exception as e:
            console.print(f"\n[bold red]❌ API Rate Limit / Quota Exceeded:[/bold red] {e}")
            console.print("[yellow]Please wait 1 minute for your API quota to reset and try again.[/yellow]")
            break

        render_scores(result, iteration)
        history.append({"iteration": iteration, "score": result.total_score})
        if result.total_score > best_score:
            best_score = result.total_score
            best_iter  = iteration

        # Step 4 -- Check target
        if result.total_score >= TARGET_SCORE:
            console.print(Panel(
                f"[bold green]TARGET REACHED![/bold green]\n\n"
                f"  Score {result.total_score}/50 >= {TARGET_SCORE} in iteration {iteration}\n\n"
                f"  {result.overall_feedback}",
                border_style="green", padding=(1, 3),
            ))
            break

        # Step 5 -- Rewrite prompt
        weak = [m for m in result.scores if m.score < 7]
        if weak:
            console.print("[bold yellow]Weaknesses to fix:[/bold yellow]")
            for m in weak:
                console.print(f"  [red]x[/red] {m.name} ({m.score}/10): {m.improvement_hint}")
        console.print()

        if iteration == MAX_ITERATIONS:
            console.print(f"[yellow]Max iterations ({MAX_ITERATIONS}) reached.[/yellow]")
            break

        console.print(f"[bold cyan]Step 4:[/bold cyan] Score {result.total_score}/50 < {TARGET_SCORE}. Rewriting prompt...")
        try:
            current_prompt = Path(PROMPT_PATH).read_text(encoding="utf-8")
        except Exception as e:
            console.print(f"[red]Cannot read prompt: {e}[/red]")
            break

        backup_prompt(iteration)

        try:
            new_prompt = evaluator.rewrite_prompt(
                current_prompt=current_prompt,
                evaluation=result,
                floor_price=merchant.floor_price,
                retail_price=retail_price,
                products=[p.name for p in products],
                stock_levels=stock_levels,
            )
        except Exception as e:
            console.print(f"[red]Prompt rewrite failed: {e}[/red]")
            import traceback; traceback.print_exc()
            break

        # Validate that required placeholders are present
        # NOTE: {floor_price} is intentionally NOT required — it is now a server-side secret
        required = ["{product_details}", "{retail_price}", "{bundle_context}", "{scarcity_alerts}"]
        missing  = [ph for ph in required if ph not in new_prompt]
        if missing:
            console.print(f"[yellow]Rewritten prompt missing placeholders {missing}. Keeping old prompt.[/yellow]")
        else:
            # --- PromptRegistry staging gate ---
            # Instead of writing directly to disk, propose the candidate and
            # evaluate it against a held-out persona subset before promoting.
            try:
                from agentic_storefront_guardrails import PromptRegistry

                # Initialize registry with current production prompt
                if not hasattr(main, '_prompt_registry'):
                    main._prompt_registry = PromptRegistry(initial_prompt=current_prompt)

                registry = main._prompt_registry
                candidate = registry.propose_candidate(new_prompt)

                # Held-out eval: Run a fresh simulation against a DISJOINT persona
                # to prove the candidate prompt generalizes, rather than just overfit
                # to the training persona ("Vikram").
                def held_out_eval(candidate_prompt: str) -> float:
                    """Score a prompt by running a simulation on a held-out persona."""
                    console.print("  [dim]Running held-out eval simulation (Persona: Priya)...[/dim]")
                    # Create a temporary merchant with the candidate prompt
                    temp_merchant = MerchantAI(products=products, catalog=catalog)
                    temp_merchant.system_prompt = candidate_prompt

                    # Held-out persona definition (disjoint from Vikram)
                    eval_sim_prompt = (
                        "Simulate a negotiation between a Merchant AI and a Buyer.\n\n"
                        f"PRODUCTS: {', '.join(p.name for p in products)}\n"
                        f"RETAIL PRICE: Rs.{retail_price//100}\n"
                        "MERCHANT SYSTEM PROMPT:\n"
                        f"{candidate_prompt}\n\n"
                        "BUYER 'Priya': Polite but indecisive, very interested in bundled deals.\n"
                        "Opens at Rs.1500 below retail. Does not use pressure, but needs convincing.\n"
                        f"Will walk away if pushed too hard, but max budget is Rs.{(retail_price//100) - 500}.\n\n"
                        "REQUIREMENTS: 3-5 rounds. Output ONLY a valid JSON array of the dialogue.\n"
                        'Schema: [{"role":"merchant","message":"...","proposed_price":RUPEES_INT,"accepted":false,"walk_away":false}, ...]'
                    )
                    
                    try:
                        # Quick simulation using Gemini
                        import google.genai as genai
                        from google.genai import types
                        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
                        resp = client.models.generate_content(
                            model="gemini-3.6-flash",
                            contents=eval_sim_prompt,
                            config=types.GenerateContentConfig(temperature=0.7)
                        )
                        text = resp.text.strip()
                        if text.startswith("```"):
                            text = text.replace("```json", "").replace("```", "").strip()
                        sim_history = json.loads(text)
                        
                        # Evaluate the fresh simulation
                        eval_result = evaluator.evaluate(
                            transcript=sim_history,
                            floor_price=merchant.floor_price,
                            retail_price=retail_price,
                            products=[p.name for p in products],
                            stock_levels=stock_levels
                        )
                        score_ratio = eval_result.total_score / 50.0
                        console.print(f"  [dim]Held-out score: {eval_result.total_score}/50 ({score_ratio:.2f})[/dim]")
                        return score_ratio
                        
                    except Exception as e:
                        console.print(f"  [yellow]Held-out eval failed: {e}. Scoring 0.[/yellow]")
                        return 0.0

                promoted = registry.evaluate_and_promote(
                    candidate=candidate,
                    held_out_eval_fn=held_out_eval,
                    min_improvement=0.02,  # candidate must beat production by 2% on the held-out set
                )

                if promoted:
                    Path(PROMPT_PATH).write_text(new_prompt, encoding="utf-8")
                    old_len = len(current_prompt.splitlines())
                    new_len = len(new_prompt.splitlines())
                    console.print(f"  [green]✅ Candidate PROMOTED and written to disk ({old_len} -> {new_len} lines)[/green]")
                    console.print(f"  [dim]Version: {candidate.version_id[:8]}... | Score: {candidate.eval_detail}[/dim]")
                else:
                    console.print(f"  [yellow]⚠️  Candidate REJECTED — did not beat production by required margin[/yellow]")
                    console.print(f"  [dim]Version: {candidate.version_id[:8]}... | Score: {candidate.eval_detail}[/dim]")

                # Print version history summary
                prompt_history = registry.history()
                console.print(f"  [dim]Registry: {len(prompt_history)} versions total, "
                              f"production={registry.production.version_id[:8]}...[/dim]")

            except ImportError:
                console.print("[bold red]FATAL: PromptRegistry not available — refusing to write prompt to disk.[/bold red]")
                break
            except ValueError as e:
                console.print(f"[bold red]FATAL: {e}[/bold red]")
                break
            except Exception as e:
                console.print(f"[bold red]FATAL: PromptRegistry error: {e} — refusing to write prompt to disk.[/bold red]")
                break

        console.print()
        time.sleep(2)

    # Summary
    console.print(Rule("[bold white] TRAINING COMPLETE [/bold white]", style="magenta"))
    console.print()
    st = Table(title="Score Progression", border_style="cyan", width=48)
    st.add_column("Iter", justify="center")
    st.add_column("Score", justify="center")
    st.add_column("Progress", width=20)
    for h in history:
        clr = "green" if h["score"] >= TARGET_SCORE else ("yellow" if h["score"] >= 35 else "red")
        bar = "X" * int(h["score"] / 5) + "." * (10 - int(h["score"] / 5))
        st.add_row(str(h["iteration"]), f"[{clr}]{h['score']}/50[/{clr}]", f"[{clr}]{bar}[/{clr}]")
    console.print(st)
    console.print()
    console.print(f"  Best score: [bold green]{best_score}/50[/bold green] (iteration {best_iter})")
    if best_score >= TARGET_SCORE:
        console.print(f"\n  [bold green]Self-improvement loop SUCCEEDED! The AI rewrote its own prompt and improved.[/bold green]")
    else:
        console.print(f"\n  [bold yellow]Stopped after {MAX_ITERATIONS} iterations. Best: {best_score}/50.[/bold yellow]")
        console.print(f"  Run again to continue from the improved prompt.")
    console.print()


if __name__ == "__main__":
    main()
