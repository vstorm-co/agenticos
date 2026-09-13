---
source_sha: 35c351a5e658
---

# Dodaj capability { #add-a-capability }

**Capability** to jednostka, z której składa się agenta. To ona jest
przełącznikiem pokazywanym przez Builder i to ją spec nazywa po id.

Celowo nie jest to „narzędzie”. Narzędzie to szczegół implementacyjny —
„wyszukiwanie w wiedzy” to jedna decyzja osoby konfigurującej agenta, a to, czy
wystawia ono dziś jedną funkcję, a jutro trzy, nie jest jej problemem. Capability
obejmuje też rzeczy, które w ogóle nie są narzędziami: strażnika budżetu, bramkę
approvalu, strategię kompaktowania. Jedno pojęcie pokrywa cały montaż zamiast
dwóch, które niezgrabnie się nakładają.

!!! abstract "Kod definiuje to, co istnieje; konfiguracja jedynie to komponuje"

    Nic, co wpisze operator, nie powoła do życia nowej capability, i to właśnie
    sprawia, że zbiór rzeczy, które agent może robić, da się przejrzeć.

## Kształt { #the-shape }

Jeden folder na capability pod `backend/app/agents/capabilities/`:

```
weather/
  __init__.py       registration — the id, the name the picker shows, the builder
  _capability.py    the AbstractCapability subclass
  _toolset.py       the tools, and the text the model reads before calling them
  README.md         why this exists and what it deliberately does not do
```

!!! warning "Układ jest egzekwowany, a jedna jego reguła jest cichą awarią"

    `@register` pojawia się w `__init__.py` i nigdzie indziej. Rejestracja w
    podmodule odpala się tylko wtedy, gdy coś ten moduł importuje — i tak
    właśnie capability znika z Buildera, przy wszystkich testach nadal na
    zielono. To `tests/test_capability_layout.py` oblewa zamiast tego.

Ten układ nie jest sugestią — `tests/test_capability_layout.py` go egzekwuje.
Każda paczka ma `_capability.py`, a każda paczka oferująca własne narzędzia ma
`_toolset.py`. Capability bez narzędzi — `clock`, `thinking` — jest wymieniona w tym
teście wraz z powodem, zamiast nosić pusty moduł.

Narzędzia mieszkają osobno od klasy capability, bo **nazwa i opis narzędzia są
promptem**: model czyta je, zanim zdecyduje o wywołaniu, a autor agenta może
przepisać oba per agent. Zakopane w domknięciu `get_toolset` są znajdowalne tylko
przez tego, kto napisał klasę.

Przeczytaj `clock/` jako najmniejszy kompletny przykład, a `knowledge/` jako
przykład ze schematem konfiguracji, zasobami i scope'em.

## 1. Capability { #1-the-capability }

`_capability.py` — dataclass rozszerzająca `AbstractCapability`, budująca swój
toolset leniwie:

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

Docstring narzędzia jest promptem. To on jest tym, co model czyta, decydując, czy
je wywołać, więc mówi *kiedy tego użyć*, a nie co funkcja robi — zobacz
`~/.claude/standards/prompting.md`.

## 2. Zarejestruj ją { #2-register-it }

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

- **`id`** trafia do każdego opublikowanego speca i jest tą jedną rzeczą, która
  nigdy nie może się zmienić. Nazwę zmieniaj dowolnie; id — nigdy.
- **`tools`** celowo nie ma wartości domyślnej. Pominięcie tego argumentu to
  `TypeError`; capability naprawdę bez narzędzi mówi `tools=()`. `id` każdego
  wpisu jest tym, na czym kluczują się `tool_approval` i `tool_overrides` speca, a
  jego `description` powinien być własnym podsumowaniem docstringa narzędzia —
  osoba wybierająca, co wymaga approvalu, i model wybierający, kiedy działać,
  powinni czytać ten sam tekst, a nie dwie rozjeżdżające się parafrazy.
- **`config_schema`** generuje formularz w Builderze i jest walidowany przy
  publikacji, więc zła wartość oblewa, kiedy ktoś patrzy na formularz, a nie w
  środku runa.
- **`scopes`** są odmawiane na etapie budowania, gdy organizacja ich nie
  przyznała.
- **`side_effecting=True`** przepuszcza narzędzia capability przez bramkę
  approvalu.
- **Zwrócenie `None`** znaczy „nie wnosi nic do *tego* agenta” i capability nie
  jest w ogóle podpinana. `knowledge` robi tak, gdy nie związano żadnych
  kolekcji: narzędzie wyszukiwania, które zawsze zwraca pustkę, jest gorsze niż
  jego brak, bo model próbuje go dalej.
- **`ctx.resources`** niesie to, co rozwiązano z bazy dla tego runa — nazwy
  kolekcji, skille. Capability nigdy nie odpytuje o nie sama; model pyta, *czego*
  szukać, nigdy gdzie.

!!! danger "Niezadeklarowane narzędzie działa bez bramki i nic tego nie mówi"

    `tools=` jest tym, dla czego Builder oferuje approval per narzędzie, i tym,
    na czym dopasowuje się bramka approvalu. Niebezpieczna połowa tej awarii jest
    cicha: autor dodaje drugie narzędzie, mające skutki uboczne, zapomina je
    zadeklarować, a ono działa bez nadzoru na zawsze.
    `tests/test_capability_registry.py` porównuje zadeklarowaną listę z
    narzędziami, które faktycznie dostaje model — i tylko to to wyłapuje.

**Builder może zwrócić capability, której nie napisaliśmy.** Jego sygnatura to
`CapabilityBuildContext -> AbstractCapability[Any] | None`, więc poprawnym
zwrotem jest wszystko, co dostarcza Pydantic AI — `thinking/` rejestruje
`pydantic_ai.capabilities.Thinking` i w ogóle nie ma `_capability.py`. Opakowanie
jednej z ich capabilities, żeby uczynić ją „naszą”, dokłada tylko drugie miejsce,
w którym ustawia się tę samą wartość. Rejestr stempluje zwrócony obiekt id z
rejestru, a to właśnie na nim dopasowuje się bramka approvalu, więc obca
capability przybywa z tą samą tożsamością co lokalna.

Zawężanie przez `isinstance`, a nie przez rzutowanie, to sposób, w jaki robi to
każda wbudowana: `ctx.config` jest typowany jako model bazowy, bo rejestr nie
wie, jaki schemat zadeklarowała ta capability, a capability związana zupełnie bez
konfiguracji dostaje swoje wartości domyślne zamiast wysypki.

!!! important "Potem dodaj moduł do `load_builtins()` w `_registry.py`"

    Moduł, którego nikt nie importuje, nie istnieje z punktu widzenia Buildera.
    To sprzężenie jest zamierzone — rejestracja jest importem, a nie skanowaniem.

## 3. Napisz README { #3-write-the-readme }

Każdy folder capability ma swój. Powiedz, po co istnieje, czego celowo nie robi i
jaką decyzję przyszły czytelnik inaczej by cofnął. To tutaj mieszka uzasadnienie,
a nie w wiadomości commita.

## 4. Przetestuj to { #4-test-it }

!!! danger "`app/agents/**` jest na 100% pokrycia, egzekwowanym w CI"

    Nowa capability z nieprzetestowaną gałęzią oblewa build. **Nie** musisz
    poszerzać dla niej bramki: obie listy w `backend/pyproject.toml` już niosą
    glob `app/agents/**`, a
    `test_every_file_in_a_platform_package_is_gated` istnieje po to, by tak
    pozostało. Edytowanie tych list jest od nowej *paczki* platformowej, spoza
    tych już objętych globem. Zobacz `## Testing` w
    `CLAUDE.md`, a `tests/test_capability_registry.py` — dla stylu.

Warto pokryć w szczególności:

- schemat konfiguracji odmawiający złej wartości, bo to jest bramka przy
  publikacji
- builder zwracający `None`, gdy nie ma nic wnosić
- odmowę na scope, jeśli capability jakiś deklaruje
- samo narzędzie, łącznie z tym, co robi, gdy to, co wywołuje, jest niedostępne

## Gdzie się to pojawia { #where-it-shows-up }

Nic więcej nie wymaga zmiany. `GET /api/v1/agents/capabilities` serwuje rejestr,
picker Buildera renderuje się z niego, a `schema-form.tsx` generuje formularz
konfiguracji z `config_json_schema()`. Capability dodana tutaj jest w produkcie
po następnym restarcie.

Dwie rzeczy, które czyta wygenerowany formularz, a które warto znać, pisząc
schemat:

- **Wartość domyślna pola jest rysowana jako jego wartość**, a nie jako szary
  placeholder. Nic nie jest zapisywane, dopóki ktoś tego nie edytuje, więc pole
  nadal śledzi wartość domyślną, która później zmienia się w kodzie — ale to, co
  widzi człowiek, jest tym, co się stanie, jeśli zostawi je w spokoju. Daj
  każdemu opcjonalnemu polu sensowną wartość domyślną, a formularz jest wypełniony
  już na wejściu.
- **`Literal` renderuje swoje surowe wartości**, chyba że schemat mówi inaczej, a
  surowe wartości to format speca: `clear_tool_results` w liście rozwijanej jest
  wyborem, którego ktoś dokonuje, zgadując. Powiedz, co każda z nich robi, przez
  `json_schema_extra={"x-enum-labels": {value: "what it does"}}` na polu — słowo
  kluczowe rozszerzenia, bo JSON Schema żadnego nie ma, trzymane przy definicji z
  tego samego powodu co `description`.
- **Napis to jednoliniowe pole**, chyba że schemat mówi inaczej, a prompt w takim
  polu to pole, w którym nikt nie przeczyta, co edytuje.
  `json_schema_extra={"x-multiline": True}` daje mu ten edytor Markdowna, który
  dostają własne instrukcje agenta — źródło albo podgląd, z odmową podpiętą do
  pola. Ten sam kształt rozszerzenia, ten sam powód.

## Dodanie narzędzia do istniejącej capability { #adding-a-tool-to-an-existing-capability }

Zwykle właściwy ruch, gdy nowe zachowanie należy do decyzji, którą ktoś już
podjął — drugi sposób czytania bazy wiedzy to nadal „wyszukiwanie w wiedzy”.
Trzy kroki, a drugi jest tym zapominanym:

1. **Napisz funkcję** w `_toolset.py` i dodaj ją do toolsetu. Jej docstring jest
   promptem; powiedz, *kiedy po to sięgnąć*, a nie co funkcja robi.
2. **Zadeklaruj ją** w krotce `tools=` w `__init__.py`. Narzędzie, o którym
   rejestr nie wie, nie może zostać zatwierdzone, nie może zostać przemianowane
   per agent i nie pojawia się w Builderze — po prostu działa.
3. **Sprawdź test rozjazdu.** `tests/test_capability_registry.py` buduje każdą
   zarejestrowaną capability i porównuje zadeklarowaną listę z narzędziami, które
   faktycznie dostaje model. To on wyłapuje pominięcie kroku 2 i to on zgłasza
   dzień, w którym paczka z góry przemianuje któreś z narzędzi, które
   reeksportujemy — trzy narzędzia capability `skills` pochodzą z
   `pydantic-ai-skills`, więc ich nazwy należą do kogoś innego.

!!! tip "Narzędzie ze skutkami ubocznymi obok tylko-do-odczytu to sygnał"

    `side_effecting` jest per capability, więc ta capability jest teraz dwiema
    decyzjami noszącymi jedną nazwę. Wolej drugą capability; `approval` per
    narzędzie w specu pozwala *autorowi agenta* być surowszym niż domyślnie i nie
    zastępuje zadeklarowania prawdy.

## Dodanie narzędzia, którego nikt tutaj nie musi pisać { #adding-a-tool-nobody-here-has-to-write }

Jeśli narzędzie jest wywołaniem zewnętrznego API, które już publikuje serwer MCP,
rozważ, czy w ogóle należy do kodu. Capability jest właściwa dla czegoś, co
platforma musi zagwarantować; serwer utrzymywany przez dostawcę jest właściwy dla
reszty. Zobacz [MCP](../mcp.md) oraz
[Dodaj serwer do katalogu MCP](add-mcp-server.md).
