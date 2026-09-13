---
source_sha: 35c351a5e658
---

# Eine Capability hinzufügen { #add-a-capability }

Eine **Capability** ist die Einheit, aus der ein Agent zusammengesetzt wird. Sie
ist das, was der Builder als Schalter zeigt, und das, was ein Spec über eine id
benennt.

Sie ist absichtlich nicht "ein Tool". Ein Tool ist ein Implementierungsdetail —
"knowledge search" ist eine Entscheidung für die Person, die einen Agent
konfiguriert, und ob dahinter heute eine Funktion und morgen drei stehen, ist
nicht deren Problem. Eine Capability deckt außerdem Dinge ab, die gar keine Tools
sind: ein Budget-Guard, ein Approval-Gate, eine Kompaktierungsstrategie. Ein
Begriff deckt den ganzen Zusammenbau ab statt zwei, die sich unschön überlappen.

!!! abstract "Code definiert, was existiert; Konfiguration setzt es nur zusammen"

    Nichts, was eine Betreiberin eintippt, kann eine neue Capability ins Dasein
    rufen, und genau das macht die Menge dessen, was ein Agent tun kann,
    prüfbar.

## Die Form { #the-shape }

Ein Ordner pro Capability unter `backend/app/agents/capabilities/`:

```
weather/
  __init__.py       registration — the id, the name the picker shows, the builder
  _capability.py    the AbstractCapability subclass
  _toolset.py       the tools, and the text the model reads before calling them
  README.md         why this exists and what it deliberately does not do
```

!!! warning "Der Aufbau wird erzwungen, und eine seiner Regeln scheitert lautlos"

    `@register` steht in `__init__.py` und nirgendwo sonst. Eine Registrierung in
    einem Untermodul feuert nur, wenn irgendetwas dieses Modul importiert — so
    verschwindet eine Capability aus dem Builder, während alle Tests grün
    bleiben. `tests/test_capability_layout.py` ist das, was stattdessen
    fehlschlägt.

Dieser Aufbau ist kein Vorschlag — `tests/test_capability_layout.py` erzwingt
ihn. Jedes Paket hat eine `_capability.py`, und jedes Paket mit eigenen Tools hat
eine `_toolset.py`. Eine Capability ohne Tools — `clock`, `thinking` — steht mit
der Begründung in diesem Test, statt ein leeres Modul mitzuschleppen.

Die Tools liegen getrennt von der Capability-Klasse, weil Name und Beschreibung
eines Tools **Prompt sind**: Das Modell liest sie, bevor es sich für einen Aufruf
entscheidet, und eine Agent-Autorin darf beide pro Agent umschreiben. In einer
`get_toolset`-Closure vergraben findet sie nur, wer die Klasse geschrieben hat.

Lesen Sie `clock/` als kleinstes vollständiges Beispiel und `knowledge/` als
eines mit Config-Schema, Ressourcen und einem Scope.

## 1. Die Capability { #1-the-capability }

`_capability.py` — eine Dataclass, die `AbstractCapability` erweitert und ihr
Toolset verzögert aufbaut:

```python
"""Current weather for a place."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset


def _build_toolset(units: str) -> FunctionToolset[Any]:
    async def current_weather(city: str) -> dict[str, str]:
        """Get the current weather for a city.

        Use this when an answer depends on today's conditions rather than a
        seasonal average.
        """
        ...

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(current_weather, takes_ctx=False)
    return toolset


@dataclass
class Weather(AbstractCapability[AgentDepsT]):
    """Gives an agent current conditions instead of a guess."""

    units: str = "metric"
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = _build_toolset(self.units)
        return self._toolset
```

Der Docstring des Tools ist der Prompt. Er ist das, was das Modell liest, wenn es
über einen Aufruf entscheidet, also sagt er, *wann man das nutzt*, nicht, was die
Funktion tut — siehe `~/.claude/standards/prompting.md`.

## 2. Registrieren { #2-register-it }

`__init__.py`:

```python
"""Weather capability — current conditions."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.weather._capability import Weather

__all__ = ["Weather"]


class WeatherConfig(BaseModel):
    units: str = Field(default="metric", pattern="^(metric|imperial)$")


@register(
    id="weather",
    name="Weather",
    category="data",
    description="Read current conditions for a place instead of assuming them.",
    tools=(
        CapabilityToolInfo(
            id="current_weather",
            description="Get the current weather for a city.",
        ),
    ),
    config_schema=WeatherConfig,
    scopes=("weather:read",),
)
def _build(ctx: CapabilityBuildContext) -> Weather | None:
    """Build the capability from its validated config."""
    config = ctx.config if isinstance(ctx.config, WeatherConfig) else WeatherConfig()
    return Weather(units=config.units)
```

- **`id`** geht in jeden veröffentlichten Spec ein und ist das Eine, das sich nie
  ändern darf. Umbenennen jederzeit; eine neue id nie.
- **`tools`** hat absichtlich keinen Default. Das Argument wegzulassen ist ein
  `TypeError`; eine Capability wirklich ohne Tools schreibt `tools=()`. Die `id`
  jedes Eintrags ist das, worauf `tool_approval` und `tool_overrides` eines Specs
  zeigen, und seine `description` sollte die Zusammenfassung aus dem Docstring
  des Tools sein — wer entscheidet, was eine Approval braucht, und das Modell,
  das entscheidet, wann es handelt, sollten denselben Text lesen, nicht zwei
  Umschreibungen, die auseinanderlaufen.
- **`config_schema`** erzeugt das Formular im Builder und wird beim
  Veröffentlichen validiert, sodass ein schlechter Wert scheitert, während jemand
  auf ein Formular schaut, statt mitten in einem Run.
- **`scopes`** werden beim Bauen abgelehnt, wenn die Organisation sie nicht
  gewährt hat.
- **`side_effecting=True`** leitet die Tools der Capability durch das
  Approval-Gate.
- **Ein `None` als Rückgabe** heißt "steuert zu *diesem* Agent nichts bei", und
  die Capability wird gar nicht erst angehängt. `knowledge` tut das, wenn keine
  Collections gebunden sind: Ein Suchwerkzeug, das immer leer zurückkommt, ist
  schlechter als keines, weil das Modell es weiter versucht.
- **`ctx.resources`** trägt das, was für diesen Run aus der Datenbank aufgelöst
  wurde — Collection-Namen, Skills. Eine Capability fragt nie selbst danach; das
  Modell fragt, *was* zu suchen ist, nie, *wo*.

!!! danger "Ein nicht deklariertes Tool läuft ungebremst, und nichts sagt es"

    `tools=` ist das, wofür der Builder Approval pro Tool anbietet, und das,
    worauf das Approval-Gate abgleicht. Die gefährliche Hälfte dieses Fehlers ist
    lautlos: Eine Autorin fügt ein zweites Tool mit Nebenwirkung hinzu, vergisst
    es zu deklarieren, und es läuft für immer unbeaufsichtigt.
    `tests/test_capability_registry.py` vergleicht die deklarierte Liste mit den
    Tools, die dem Modell tatsächlich angeboten werden — und das ist das Einzige,
    was das auffängt.

**Der Builder darf eine Capability zurückgeben, die wir nicht geschrieben
haben.** Seine Signatur ist `CapabilityBuildContext -> AbstractCapability[Any] |
None`, also ist alles, was Pydantic AI mitliefert, ein gültiger Rückgabewert —
`thinking/` registriert `pydantic_ai.capabilities.Thinking` und hat gar keine
`_capability.py`. Eine ihrer Capabilities einzuwickeln, um sie zu "unserer" zu
machen, schafft nur einen zweiten Ort, an dem derselbe Wert gesetzt wird. Die
Registry stempelt der zurückgegebenen Instanz die Registry-id auf, auf die das
Approval-Gate abgleicht, also kommt eine fremde Capability mit derselben
Identität an wie eine eigene.

Die Einengung per `isinstance` statt eines Casts ist das, was jedes Builtin tut:
`ctx.config` ist als Basismodell typisiert, weil die Registry nicht weiß, welches
Schema diese Capability deklariert hat, und eine Capability, die ganz ohne Config
gebunden wird, bekommt ihre Defaults statt eines Absturzes.

!!! important "Dann das Modul in `load_builtins()` in `_registry.py` eintragen"

    Ein Modul, das niemand importiert, existiert für den Builder nicht. Diese
    Kopplung ist gewollt — Registrierung ist ein Import, kein Scan.

## 3. Die README schreiben { #3-write-the-readme }

Jeder Capability-Ordner hat eine. Sagen Sie, warum es sie gibt, was sie
absichtlich nicht tut, und jede Entscheidung, die eine spätere Leserin sonst
rückgängig machen würde. Hier wohnt die Begründung, nicht in der
Commit-Nachricht.

## 4. Testen { #4-test-it }

!!! danger "`app/agents/**` liegt bei 100 % Coverage, in CI erzwungen"

    Eine neue Capability mit einem ungetesteten Zweig bricht den Build. Sie
    müssen das Gate dafür **nicht** aufweiten: Beide Listen in
    `backend/pyproject.toml` tragen den Glob `app/agents/**` bereits, und
    `test_every_file_in_a_platform_package_is_gated` gibt es, damit das so
    bleibt. Diese Listen zu bearbeiten ist für ein neues Plattform-*Paket*
    außerhalb der bereits erfassten Globs. Siehe `## Testing` in
    `CLAUDE.md` und `tests/test_capability_registry.py` für den Stil.

Was sich besonders zu prüfen lohnt:

- das Config-Schema, das einen schlechten Wert ablehnt, denn das ist das Gate
  beim Veröffentlichen
- der Builder, der `None` zurückgibt, wenn er nichts beitragen soll
- die Scope-Ablehnung, falls die Capability einen deklariert
- das Tool selbst, einschließlich dessen, was es tut, wenn das Aufgerufene nicht
  erreichbar ist

## Wo es auftaucht { #where-it-shows-up }

Sonst muss nichts geändert werden. `GET /api/v1/agents/capabilities` liefert die
Registry aus, der Picker des Builders rendert daraus, und `schema-form.tsx`
erzeugt das Konfigurationsformular aus `config_json_schema()`. Eine hier
hinzugefügte Capability ist beim nächsten Neustart im Produkt.

Zwei Dinge, die das erzeugte Formular liest und die beim Schreiben des Schemas zu
wissen lohnen:

- **Der Default eines Feldes wird als sein Wert gezeichnet**, nicht als graue
  Platzhalterschrift. Gespeichert wird nichts, bis jemand ihn bearbeitet, also
  folgt das Feld weiterhin einem Default, der sich später im Code ändert — aber
  was eine Person sieht, ist das, was passiert, wenn sie es in Ruhe lässt. Geben
  Sie jedem optionalen Feld einen sinnvollen Default, und das Formular ist bei
  Ankunft ausgefüllt.
- **Ein `Literal` rendert seine rohen Werte**, sofern das Schema nichts anderes
  sagt, und rohe Werte sind Spec-Format: `clear_tool_results` in einem Dropdown
  ist eine Entscheidung, die jemand raten muss. Sagen Sie mit
  `json_schema_extra={"x-enum-labels": {value: "what it does"}}` am Feld, was
  jeder Wert tut — ein Erweiterungsschlüsselwort, weil JSON Schema keines hat,
  aufbewahrt neben der Definition aus demselben Grund wie `description`.
- **Ein String ist ein einzeiliges Feld**, sofern das Schema nichts anderes sagt,
  und ein Prompt darin ist ein Feld, in dem niemand lesen kann, was er gerade
  bearbeitet. `json_schema_extra={"x-multiline": True}` verschafft ihm den
  Markdown-Editor, den auch die Instruktionen des Agents bekommen — Quelltext
  oder Vorschau, mit einer an das Feld verdrahteten Ablehnung. Dieselbe Form der
  Erweiterung, derselbe Grund.

## Ein Tool zu einer bestehenden Capability hinzufügen { #adding-a-tool-to-an-existing-capability }

Meist der richtige Zug, wenn das neue Verhalten zu einer Entscheidung gehört, die
jemand bereits getroffen hat — ein zweiter Weg, die Wissensbasis zu lesen, ist
immer noch "knowledge search". Drei Schritte, und der zweite ist der, der
vergessen wird:

1. **Die Funktion schreiben**, in `_toolset.py`, und sie dem Toolset hinzufügen.
   Ihr Docstring ist der Prompt; sagen Sie, *wann man danach greift*, nicht, was
   die Funktion tut.
2. **Sie deklarieren**, im Tupel `tools=` in `__init__.py`. Ein Tool, von dem die
   Registry nichts weiß, kann nicht freigegeben werden, kann pro Agent nicht
   umbenannt werden und erscheint nicht im Builder — es läuft einfach.
3. **Den Drift-Test prüfen.** `tests/test_capability_registry.py` baut jede
   registrierte Capability und vergleicht die deklarierte Liste mit den Tools,
   die dem Modell tatsächlich angeboten werden. Er fängt einen übersprungenen
   Schritt 2 ab und meldet den Tag, an dem ein Upstream-Paket eines der Tools
   umbenennt, die wir re-exportieren — die drei der `skills`-Capability kommen
   aus `pydantic-ai-skills`, ihre Namen gehören also anderen.

!!! tip "Ein Tool mit Nebenwirkung neben rein lesenden ist ein Signal"

    `side_effecting` gilt pro Capability, also sind es jetzt zwei Entscheidungen
    unter einem Namen. Nehmen Sie lieber eine zweite Capability; `approval` pro
    Tool in einem Spec lässt eine *Agent-Autorin* strenger sein als der Default
    und ersetzt nicht, die Wahrheit zu deklarieren.

## Ein Tool hinzufügen, das hier niemand schreiben muss { #adding-a-tool-nobody-here-has-to-write }

Wenn das Tool ein Aufruf einer Drittanbieter-API ist, für die es bereits einen
veröffentlichten MCP-Server gibt, überlegen Sie, ob es überhaupt in Code gehört.
Eine Capability ist richtig für etwas, das die Plattform garantieren muss; ein
Server, den der Anbieter pflegt, ist richtig für den Rest. Siehe
[MCP](../mcp.md) und
[Einen Server zum MCP-Katalog hinzufügen](add-mcp-server.md).
