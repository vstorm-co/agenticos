"""Which models can answer a browsing agent's typed questions.

Data, in `app/core/catalog/decision_models.json`, for the reason
`app/services/image_models.py` gives about image models: an id, a name and a
sentence saying when to reach for it is not something any provider listing
answers. TypeSafe's `/models` is not a catalog of what this platform supports.

**The catalog is what the picker offers, not what the field accepts.** A moving
alias is the right answer for almost every agent, and a pinned version
(`jev-1.13.0`) is the right answer for an agent whose confidence floor was tuned
against one - TypeSafe accepts both. So the schema carries the catalog as an
`enum` the Builder renders a select from, while the field stays a string and
validation stays permissive. An author who needs a pinned build types it; nobody
has to wait for a release of this platform to use a release of that one.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from app.core import catalog


@dataclass(frozen=True)
class DecisionModel:
    """One model that picks, as a picker renders it."""

    id: str
    name: str
    description: str = ""


DECISION_MODELS: tuple[DecisionModel, ...] = catalog.load(
    "decision_models.json", TypeAdapter(tuple[DecisionModel, ...])
)

DEFAULT_DECISION_MODEL = DECISION_MODELS[0].id
"""What an agent gets when its author picks nothing - the moving alias, first in the file."""


def decision_model_schema() -> dict[str, Any]:
    """The `json_schema_extra` that turns the model field into a picker.

    `enum` is what the Builder's schema form renders a select from and
    `x-enum-labels` is what it writes in the options, both conventions this
    console already has - so the catalog reaches the form without a second
    endpoint, a second hook or a second copy of the list.
    """
    return {
        "enum": [model.id for model in DECISION_MODELS],
        "x-enum-labels": {model.id: model.name for model in DECISION_MODELS},
    }
