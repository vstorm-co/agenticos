"""Giving an agent a way to draw in the conversation, and to find what it drew before."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.visuals._reach import WebReach
from app.agents.capabilities.visuals._toolset import VisualsToolset
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.services import visual as visuals

LISTED = 20
"""How many earlier visuals the instructions name - the newest ones."""


def maps_line() -> str:
    """Whether a map drawn here has a background, so the model promises nothing it lacks."""
    tiles = settings.map_tiles()
    if tiles is None:
        return (
            "Maps in visuals: use `AOWorldMap.draw` by default, including for city-to-city "
            "routes and itineraries. Load the bundled d3, topojson, world-atlas and "
            "agenticos-worldmap libraries, then draw country outlines, pins and routes "
            "in SVG; pass a DOM element, not a CSS selector, and use `focus` to zoom to "
            "the relevant countries. This works without "
            "map tiles or network access. Do not use Leaflet, `AOMap.itinerary`, remote "
            "tiles or a plain pin-only outline when no map tiles are configured. "
            "Country outlines are geographic context, not street directions: never "
            "invent road geometry, distances or travel times. Only if street detail "
            "is requested, explain in your answer that the deployment administrator "
            "can enable it with `VISUAL_MAP_TILES` (for example `openstreetmap`)."
        )
    return (
        f"Maps in visuals: the administrator enabled {tiles.name} tiles. Use "
        "`AOWorldMap.draw` for country and regional maps; street-level maps and "
        "itineraries may use `AOMap.itinerary`. If tiles fail to load, render a "
        "lightweight SVG map with `AOWorldMap.draw`, country outlines, pins and routes "
        "instead of leaving an empty map. Coordinates you know from memory are "
        "approximate - say so, and never present the line between stops as directions, "
        "a distance or a travel time you have not looked up. An administrator can "
        "check the configured tile server under Admin → System."
    )


@dataclass
class Visuals(AbstractCapability[AgentDeps]):
    """Lets an agent draw diagrams, explainers and scenes live under its message.

    See the package `README.md` for why a visual lives in its tool call, why the
    frame is the app sandbox, and why earlier visuals are named rather than replayed.
    """

    web_reach: tuple[WebReach, ...] = ()
    """Where the agent's web readers may go, and so where a picture may come from."""

    _tools: VisualsToolset = field(init=False, repr=False)
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _listed: dict[UUID, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._tools = VisualsToolset(web_reach=self.web_reach)

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = self._tools.build()
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[AgentDeps]], Awaitable[str]]:
        """A callable, so a run is told about the visuals its conversation already holds."""
        return self._instructions

    async def _instructions(self, ctx: RunContext[AgentDeps]) -> str:
        earlier = await self._earlier(ctx)
        return f"{maps_line()}\n\n{earlier}" if earlier else maps_line()

    async def _earlier(self, ctx: RunContext[AgentDeps]) -> str:
        """The conversation's earlier visuals by id, read once per run.

        An earlier turn reaches the model as its text alone, so without this the
        model would not know a drawing it made yesterday exists, let alone its id.
        Once per run: a turn's own drawings are in its messages already.
        """
        deps = ctx.deps
        if deps.run_id is None or deps.organization_id is None:
            return ""
        if deps.run_id not in self._listed:
            conversation_id = await visuals.conversation_of_run(
                run_id=deps.run_id, organization_id=deps.organization_id
            )
            earlier = (
                await visuals.earlier_visuals(conversation_id=conversation_id, limit=LISTED)
                if conversation_id is not None
                else []
            )
            lines = [
                f"- `{item.id}` - {item.title} ({item.kind}"
                + (f", a revision of `{item.revision_of}`" if item.revision_of else "")
                + ")"
                for item in earlier
            ]
            self._listed[deps.run_id] = (
                "Visuals already drawn in this conversation, oldest first. Pass an id to "
                "`read_visual` or `revise_visual`:\n" + "\n".join(lines)
                if lines
                else ""
            )
        return self._listed[deps.run_id]
