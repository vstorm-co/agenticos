"""Role packs: the routines worth starting with for a kind of work (#2301).

A person who says they work in sales is offered a morning briefing, a brief
before each meeting and news about their accounts - routines on the starter
agent, from the trigger templates the routine dialog already offers. A pack is
setup data like those templates: installing one creates ordinary routines the
person can change or delete, and the pack plays no part after that.

Hand-maintained in `role_packs.json`. Every routine a pack names has to be a
schedule template in `trigger_templates.json`; the import below refuses one
that is not, so a pack never installs half of itself.
"""

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core import catalog
from app.services.trigger_templates import CATALOG as TRIGGER_TEMPLATES
from app.services.trigger_templates import TriggerTemplate


class RolePack(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str
    routines: tuple[str, ...] = Field(min_length=1)


PACKS: tuple[RolePack, ...] = catalog.load("role_packs.json", TypeAdapter(tuple[RolePack, ...]))

_SCHEDULES = {
    template.key: template for template in TRIGGER_TEMPLATES if template.trigger_type == "schedule"
}
_MISSING = sorted({key for pack in PACKS for key in pack.routines} - set(_SCHEDULES))
if _MISSING:  # pragma: no cover - a catalog edit that would install half a pack
    raise ValueError(f"role_packs.json names routines with no schedule template: {_MISSING}")


def pack(pack_id: str) -> RolePack | None:
    return next((candidate for candidate in PACKS if candidate.id == pack_id), None)


def routines_of(role_pack: RolePack) -> list[TriggerTemplate]:
    """The schedule templates a pack installs, in its order."""
    return [_SCHEDULES[key] for key in role_pack.routines]
