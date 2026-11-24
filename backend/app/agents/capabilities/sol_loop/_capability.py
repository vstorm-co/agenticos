"""One reviewer judges the work, in rounds, until it passes or the budget ends.

The builder resolves the configured reviewer against the models the runner
resolved for this run - primary only, never a profile's fallback chain, which
would silently substitute another model and break the one-reviewer shape the
ledger is written under. A reviewer whose model did not resolve is kept with
no model rather than dropped: the tool reports it unavailable, with the
reason, instead of the round quietly becoming a review by nobody.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.sol_loop._toolset import build_sol_loop_toolset
from app.agents.manifest import RunRecorder
from app.agents.model_resolver import ModelRequestSpec, build_model
from app.agents.sol_loop import ResolvedSolLoopReviewer

logger = logging.getLogger(__name__)

#: The runner-resolved sol-loop model, by model profile id. Read here rather
#: than resolved here: the runner holds the vault, and a capability must never
#: fetch credentials itself.
SOL_LOOP_MODELS_RESOURCE = "sol_loop_models"
#: The run's recorder, so rounds land on the manifest beside the requests.
SOL_LOOP_RECORDER_RESOURCE = "sol_loop_recorder"

_INSTRUCTIONS = (
    "Sol-loop reviews work in rounds. Call run_sol_loop_review with the work "
    "and the context it needs, one round per call: the call asks the one "
    "configured reviewer for a verdict and findings. Round 1 reviews the whole "
    "change; later rounds check only the changed code and the open findings, so "
    "pass the changed files and your dispositions for the last round's findings "
    "with each later call. After a round, fix what the reviewer found and call "
    "it again for a fresh round, until the verdict is APPROVE on the current "
    "diff. Do not ask for more rounds than the capability allows, do not let "
    "repeated reviews widen the scope - fix what was asked, nothing more - and "
    "do not treat a round that ran out of budget, or one the reviewer never "
    "answered, as approval."
)


@dataclass
class SolLoop(AbstractCapability[AgentDepsT]):
    """Runs sol-loop review rounds over the work the agent hands it.

    The reviewer arrives resolved: a reviewer with no model is reported
    unavailable by the tool rather than substituted, and a run with no reviewer
    at all still builds, so the drift check can build it - its tool then says
    so instead of offering a review nobody will give.
    """

    reviewer: ResolvedSolLoopReviewer | None = None
    max_rounds: int = 3
    recorder: RunRecorder = field(default_factory=RunRecorder)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The sol-loop's one tool, built once."""
        if self._toolset is None:
            self._toolset = build_sol_loop_toolset(self.reviewer, self.recorder, self.max_rounds)
        return self._toolset

    def get_instructions(self) -> str:
        """How sol-loop works, in the agent's instructions."""
        return _INSTRUCTIONS


def resolve_reviewer(
    reviewer: dict[str, Any] | None,
    models: Mapping[UUID, ModelRequestSpec] | None,
) -> ResolvedSolLoopReviewer | None:
    """The configured reviewer with its primary model, or why it has none.

    `models` is what the runner resolved for this run; a profile id missing
    from it - deleted since publish, or a key that no longer unseals - leaves
    the reviewer in place with no model, so the round reports it unavailable
    rather than reviewing with a reviewer the operator did not choose. No
    reviewer configured at all is `None`, which the tool refuses outright.
    """
    if reviewer is None:
        return None
    name = str(reviewer.get("name", ""))
    provider = str(reviewer.get("provider", ""))
    profile_id = reviewer.get("model_profile_id")
    spec = models.get(profile_id) if isinstance(models, Mapping) and profile_id else None
    if spec is None:
        return ResolvedSolLoopReviewer(
            name=name,
            provider=provider,
            model_label="",
            model=None,
            unavailable_reason=("No model resolved for this reviewer's model profile"),
        )
    try:
        model = build_model(spec.credential, spec.model)
    except Exception:
        # A model that cannot be constructed is unavailable, never the run's
        # failure: sol-loop is advisory to the run it reviews.
        logger.warning(
            "Sol-loop reviewer %s cannot build its model; reviewing without it",
            name,
            exc_info=True,
        )
        return ResolvedSolLoopReviewer(
            name=name,
            provider=provider,
            model_label=spec.label,
            model=None,
            unavailable_reason="Its model could not be built",
        )
    return ResolvedSolLoopReviewer(
        name=name, provider=provider, model_label=spec.label, model=model
    )
