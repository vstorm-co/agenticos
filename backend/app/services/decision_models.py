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

    `x-suggestions` is the *open* counterpart of `enum`, and the distinction is
    the whole point: `enum` makes the console render a closed select, which would
    have forbidden the pinned build this field exists to allow - the promise two
    paragraphs up, broken by the mechanism meant to deliver it. Suggestions are
    offered in a datalist and anything else is still typed. `x-enum-labels`
    names them, the same convention a select uses, so the catalog reaches the
    form without a second endpoint, a second hook or a second copy of the list.
    """
    return {
        "x-suggestions": [model.id for model in DECISION_MODELS],
        "x-enum-labels": {model.id: model.name for model in DECISION_MODELS},
    }
