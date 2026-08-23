"""
prompt_versioning.py
---------------------
Fixes: "Evaluator AI automatically rewrites the Merchant's core system
prompt and iterates until a perfect score" running directly against
production, unreviewed, with no rollback.

The fix is NOT to remove the self-improvement loop — it's genuinely your
most interesting feature. The fix is to put a staging gate in front of
it:

  candidate prompt -> shadow-tested against a HELD-OUT persona set
  (never used to generate/train the candidate) -> must beat the current
  production prompt by a margin, not just clear an absolute score ->
  only then promoted -> every version kept -> instant rollback.

This turns "an autonomous agent that rewrites its own instructions" from
a liability into a controlled, demonstrable pipeline — which is a much
stronger story for judges than "it just works, trust us."
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class PromptVersion:
    version_id: str
    prompt_text: str
    created_at: float
    status: str  # 'staging' | 'production' | 'rejected' | 'retired'
    eval_score: Optional[float] = None
    eval_detail: str = ""
    parent_version_id: Optional[str] = None


class PromptRegistry:
    """
    In-memory for the demo — back with a real DB/file store for the
    actual submission so history survives restarts.
    """

    def __init__(self, initial_prompt: str):
        self._versions: List[PromptVersion] = []
        v0 = PromptVersion(
            version_id=str(uuid.uuid4()),
            prompt_text=initial_prompt,
            created_at=time.time(),
            status="production",
        )
        self._versions.append(v0)

    @property
    def production(self) -> PromptVersion:
        prod = [v for v in self._versions if v.status == "production"]
        return prod[-1]

    def propose_candidate(self, prompt_text: str) -> PromptVersion:
        """Called by your Evaluator/self-improvement loop when it wants
        to try a rewritten prompt. This does NOT go live."""
        candidate = PromptVersion(
            version_id=str(uuid.uuid4()),
            prompt_text=prompt_text,
            created_at=time.time(),
            status="staging",
            parent_version_id=self.production.version_id,
        )
        self._versions.append(candidate)
        return candidate

    def evaluate_and_promote(
        self,
        candidate: PromptVersion,
        held_out_eval_fn: Callable[[str], float],
        min_improvement: float = 0.03,
    ) -> bool:
        """
        held_out_eval_fn(prompt_text) -> score in [0, 1], computed against
        a persona/eval set the candidate was NOT optimized against.
        Reusing the same personas that generated the candidate here would
        just reward-hack your own gate — keep the held-out set separate
        and periodically refresh it.

        Promotion requires beating production by `min_improvement`, not
        just posting a high absolute number, so noisy single-run scores
        don't flip your live merchant on a fluke.
        """
        candidate_score = held_out_eval_fn(candidate.prompt_text)
        production_score = held_out_eval_fn(self.production.prompt_text)

        candidate.eval_score = candidate_score
        candidate.eval_detail = (
            f"candidate={candidate_score:.4f} vs "
            f"production={production_score:.4f}"
        )

        if candidate_score >= production_score + min_improvement:
            self.production.status = "retired"
            candidate.status = "production"
            return True

        candidate.status = "rejected"
        return False

    def rollback_to(self, version_id: str) -> None:
        """Instant rollback — e.g. if a promoted prompt misbehaves in
        production despite passing the held-out eval."""
        target = next(v for v in self._versions if v.version_id == version_id)
        self.production.status = "retired"
        target.status = "production"

    def history(self) -> List[PromptVersion]:
        return list(self._versions)


# ---------------------------------------------------------------------
# Example held-out eval stub — replace the body with your real
# Evaluator AI call against negotiation simulations. The important
# part is that `held_out_personas` is disjoint from whatever personas
# generated/trained the candidate prompt.
# ---------------------------------------------------------------------
def example_held_out_eval(prompt_text: str) -> float:
    held_out_personas = ["the_silent_haggler", "the_bulk_buyer", "the_impatient_buyer"]
    # ... run simulated negotiations here using `prompt_text` as the
    # merchant's system prompt against each persona, score margin
    # protection + upsell success, return an aggregate 0..1 score.
    raise NotImplementedError("Wire this to your real Evaluator AI + simulator")
