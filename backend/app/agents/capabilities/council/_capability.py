"""Three delegates review the work, one per provider, in parallel.

The builder resolves each configured member against the models the runner
resolved for this run - primary only, never a profile's fallback chain, which
would silently substitute another provider and break the one-model-per-provider
shape the scores are comparable under. A member whose model did not resolve is
kept with no model rather than dropped: the tool reports it unavailable, with
the reason, instead of the round quietly becoming a two-delegate review.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.council._toolset import build_council_toolset
from app.agents.council import ResolvedCouncilMember
from app.agents.manifest import RunRecorder
from app.agents.model_resolver import ModelRequestSpec, build_model

logger = logging.getLogger(__name__)

#: The runner-resolved council models, by model profile id. Read here rather
#: than resolved here: the runner holds the vault, and a capability must never
#: fetch credentials itself.
COUNCIL_MODELS_RESOURCE = "council_models"
#: The run's recorder, so rounds land on the manifest beside the requests.
COUNCIL_RECORDER_RESOURCE = "council_recorder"

_INSTRUCTIONS = (
    "The council reviews work in rounds. Call run_council_review with the work "
    "and the context it needs, one round per call: the call fans the work out to "
    "the delegates in parallel and returns each delegate's score out of 10 with "
    "its findings. After a round, fix what the delegates found and call it again "
    "for a fresh round, until every delegate scores at or above the agreement "
    "threshold. Do not ask for more rounds than the capability allows, and do "
    "not let repeated reviews widen the scope - fix what was asked, nothing more."
)


@dataclass
class Council(AbstractCapability[AgentDepsT]):
    """Runs council review rounds over the work the agent hands it.

    The members arrive resolved: a member with no model is reported
    unavailable by the tool rather than substituted, and a run with no members
    at all still builds, so the drift check can build it - its tool then says
    so instead of offering a review nobody will give.
    """

    members: list[ResolvedCouncilMember] = field(default_factory=list)
    threshold: int = 8
    max_rounds: int = 3
    recorder: RunRecorder = field(default_factory=RunRecorder)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The council's one tool, built once."""
        if self._toolset is None:
            self._toolset = build_council_toolset(
                self.members, self.recorder, self.threshold, self.max_rounds
            )
        return self._toolset

    def get_instructions(self) -> str:
        """How the council works, in the agent's instructions."""
        return _INSTRUCTIONS


def resolve_members(
    members: list[dict[str, Any]],
    models: Mapping[UUID, ModelRequestSpec] | None,
) -> list[ResolvedCouncilMember]:
    """Each configured member with its primary model, or why it has none.

    `models` is what the runner resolved for this run; a profile id missing
    from it - deleted since publish, or a key that no longer unseals - leaves
    the member in place with no model, so the round reports it unavailable
    rather than reviewing with a council that quietly lost a provider.
    """
    resolved: list[ResolvedCouncilMember] = []
    for member in members:
        name = str(member.get("name", ""))
        provider = str(member.get("provider", ""))
        profile_id = member.get("model_profile_id")
        spec = models.get(profile_id) if isinstance(models, Mapping) and profile_id else None
        if spec is None:
            resolved.append(
                ResolvedCouncilMember(
                    name=name,
                    provider=provider,
                    model_label="",
                    model=None,
                    unavailable_reason=("No model resolved for this member's model profile"),
                )
            )
            continue
        if spec.provider != provider or spec.credential.provider != provider:
            resolved.append(
                ResolvedCouncilMember(
                    name=name,
                    provider=provider,
                    model_label=spec.label,
                    model=None,
                    unavailable_reason=(
                        "Configured provider does not match the resolved model profile"
                    ),
                )
            )
            continue
        try:
            model = build_model(spec.credential, spec.model)
        except Exception:
            # A model that cannot be constructed is unavailable, never the
            # run's failure: the council is advisory to the run it reviews.
            logger.warning(
                "Council member %s cannot build its model; reviewing without it",
                name,
                exc_info=True,
            )
            resolved.append(
                ResolvedCouncilMember(
                    name=name,
                    provider=provider,
                    model_label=spec.label,
                    model=None,
                    unavailable_reason="Its model could not be built",
                )
            )
            continue
        resolved.append(
            ResolvedCouncilMember(name=name, provider=provider, model_label=spec.label, model=model)
        )
    return resolved
