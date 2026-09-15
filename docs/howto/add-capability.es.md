---
source_sha: "35c351a5e658"
---

# Añade una capability { #add-a-capability }

Una **capability** es la unidad con la que se ensambla un agent. Es lo que el
Builder muestra como un interruptor y lo que un spec nombra por su id.

Deliberadamente no es "una herramienta". Una herramienta es un detalle de
implementación: "knowledge search" es una sola decisión para quien configura un
agent, y que hoy exponga una función y mañana tres no es problema suyo. Una
capability cubre además cosas que no son herramientas en absoluto: una guarda de
budget, una puerta de aprobación, una estrategia de compactación. Un solo
concepto cubre todo el ensamblaje en lugar de dos que se solapan con torpeza.

!!! abstract "El código define lo que existe; la configuración solo lo compone"

    Nada de lo que teclee un operador puede traer una capability nueva a la
    existencia, y eso es lo que hace revisable el conjunto de cosas que un agent
    puede hacer.

## La forma { #the-shape }

Una carpeta por capability bajo `backend/app/agents/capabilities/`:

```
weather/
  __init__.py       registration — the id, the name the picker shows, the builder
  _capability.py    the AbstractCapability subclass
  _toolset.py       the tools, and the text the model reads before calling them
  README.md         why this exists and what it deliberately does not do
```

!!! warning "La disposición se impone, y una de sus reglas falla en silencio"

    `@register` aparece en `__init__.py` y en ningún otro sitio. Un registro en
    un submódulo solo se dispara si algo importa ese módulo, que es la forma en
    que una capability desaparece del Builder con todos los tests aún en verde.
    `tests/test_capability_layout.py` es lo que falla en su lugar.

Esta disposición no es una sugerencia: `tests/test_capability_layout.py` la
impone. Cada paquete tiene un `_capability.py` y cada paquete que ofrece
herramientas propias tiene un `_toolset.py`. Una capability sin herramientas
—`clock`, `thinking`— figura en ese test con el motivo, en vez de arrastrar un
módulo vacío.

Las herramientas viven aparte de la clase de la capability porque el **nombre y
la descripción de una herramienta son prompt**: el modelo los lee antes de
decidir si llama, y quien escribe un agent puede reescribir ambos por agent.
Enterrados en una clausura `get_toolset` solo los encuentra quien escribió la
clase.

Lee `clock/` como el ejemplo completo más pequeño y `knowledge/` como uno con
esquema de configuración, recursos y un scope.

## 1. La capability { #1-the-capability }

`_capability.py`: una dataclass que extiende `AbstractCapability` y construye su
toolset de forma perezosa:

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

El docstring de la herramienta es el prompt. Es lo que el modelo lee al decidir
si la llama, así que dice *cuándo usar esto*, no lo que hace la función; ver
`~/.claude/standards/prompting.md`.

## 2. Regístrala { #2-register-it }

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

- **`id`** entra en cada spec publicado y es lo único que no debe cambiar nunca.
  Renombra cuanto quieras; recodifica nunca.
- **`tools`** no tiene valor por defecto, a propósito. Omitir el argumento es un
  `TypeError`; una capability realmente sin herramientas escribe `tools=()`. El
  `id` de cada entrada es aquello a lo que apuntan el `tool_approval` y los
  `tool_overrides` de un spec, y su `description` debería ser el resumen del
  propio docstring de la herramienta: quien elige qué necesita aprobación y el
  modelo que elige cuándo actuar deberían leer el mismo texto, no dos paráfrasis
  que se separan.
- **`config_schema`** genera el formulario del Builder y se valida al publicar,
  así que un valor malo falla mientras alguien mira un formulario y no a mitad de
  un run.
- **`scopes`** se rechazan en el momento de construir cuando la organización no
  los ha concedido.
- **`side_effecting=True`** encamina las herramientas de la capability por la
  puerta de aprobación.
- **Devolver `None`** significa "no aporta nada a *este* agent" y la capability
  no se adjunta en absoluto. `knowledge` lo hace cuando no hay colecciones
  vinculadas: una herramienta de búsqueda que siempre devuelve vacío es peor que
  ninguna, porque el modelo sigue intentándolo.
- **`ctx.resources`** lleva lo que se resolvió desde la base de datos para este
  run: nombres de colecciones, skills. Una capability nunca los consulta por su
  cuenta; el modelo pregunta *qué* buscar, nunca *dónde*.

!!! danger "Una herramienta no declarada se ejecuta sin puerta, y nada lo dice"

    `tools=` es aquello para lo que el Builder ofrece aprobación por herramienta
    y con lo que la puerta de aprobación hace la correspondencia. La mitad
    peligrosa del fallo es silenciosa: alguien añade una segunda herramienta con
    efectos, olvida declararla y se ejecuta desatendida para siempre.
    `tests/test_capability_registry.py` compara la lista declarada con las
    herramientas que de verdad se le ofrecen al modelo, que es lo único que lo
    detecta.

**El constructor puede devolver una capability que no hemos escrito nosotros.**
Su firma es `CapabilityBuildContext -> AbstractCapability[Any] | None`, así que
cualquier cosa que traiga Pydantic AI es un retorno válido: `thinking/` registra
`pydantic_ai.capabilities.Thinking` y no tiene `_capability.py` en absoluto.
Envolver una de las suyas para hacerla "nuestra" solo añade un segundo sitio
donde fijar el mismo valor. El registro estampa en la instancia devuelta el id
del registro, que es con lo que la puerta de aprobación hace la correspondencia,
de modo que una capability ajena llega con la misma identidad que una propia.

El estrechamiento con `isinstance` en lugar de un cast es como lo hace cada
capability incorporada: `ctx.config` está tipado como el modelo base porque el
registro no sabe qué esquema declaró esta capability, y una capability vinculada
sin configuración alguna recibe sus valores por defecto en vez de un fallo.

!!! important "Después añade el módulo a `load_builtins()` en `_registry.py`"

    Un módulo que nadie importa no existe para el Builder. Ese acoplamiento es
    intencionado: registrar es importar, no escanear.

## 3. Escribe el README { #3-write-the-readme }

Cada carpeta de capability tiene uno. Di por qué existe, qué no hace
deliberadamente y cualquier decisión que un lector futuro deshiciera de otro
modo. Aquí es donde vive el razonamiento, no en el mensaje del commit.

## 4. Pruébala { #4-test-it }

!!! danger "`app/agents/**` está al 100% de cobertura, impuesto en CI"

    Una capability nueva con una rama sin probar rompe el build. **No** hace
    falta que ensanches la puerta por ella: las dos listas de
    `backend/pyproject.toml` ya llevan el glob `app/agents/**`, y
    `test_every_file_in_a_platform_package_is_gated` existe para que siga siendo
    cierto. Editar esas listas es para un *paquete* de plataforma nuevo, fuera de
    los que ya cubren los globs. Ver `## Testing` en
    `CLAUDE.md`, y `tests/test_capability_registry.py` para el estilo.

Vale la pena cubrir en concreto:

- el esquema de configuración rechazando un valor malo, ya que esa es la puerta
  del momento de publicar
- el constructor devolviendo `None` cuando no debe aportar nada
- el rechazo por scope, si la capability declara alguno
- la herramienta misma, incluido lo que hace cuando aquello que llama no está
  disponible

## Dónde aparece { #where-it-shows-up }

No hace falta cambiar nada más. `GET /api/v1/agents/capabilities` sirve el
registro, el selector del Builder se dibuja a partir de él y `schema-form.tsx`
genera el formulario de configuración desde `config_json_schema()`. Una
capability añadida aquí está en el producto en el siguiente reinicio.

Dos cosas que lee el formulario generado y que vale la pena saber mientras
escribes el esquema:

- **El valor por defecto de un campo se dibuja como su valor**, no en gris de
  marcador de posición. No se guarda nada hasta que alguien lo edita, así que el
  campo sigue rastreando un valor por defecto que después cambia en el código,
  pero lo que una persona ve es lo que ocurrirá si lo deja en paz. Dale a cada
  campo opcional un valor por defecto sensato y el formulario llega relleno.
- **Un `Literal` dibuja sus valores en crudo** salvo que el esquema diga otra
  cosa, y los valores en crudo son formato de spec: `clear_tool_results` en un
  desplegable es una elección que alguien hace adivinando. Di lo que hace cada
  uno con `json_schema_extra={"x-enum-labels": {value: "what it does"}}` en el
  campo: una palabra clave de extensión, porque JSON Schema no tiene ninguna,
  guardada junto a la definición por la misma razón que `description`.
- **Una cadena es una caja de una línea** salvo que el esquema diga otra cosa, y
  un prompt dentro es un campo en el que nadie puede leer lo que está editando.
  `json_schema_extra={"x-multiline": True}` le consigue el editor Markdown que
  reciben las instrucciones del propio agent: fuente o vista previa, y un rechazo
  cableado al campo. La misma forma de extensión, la misma razón.

## Añadir una herramienta a una capability existente { #adding-a-tool-to-an-existing-capability }

Suele ser el movimiento correcto cuando el comportamiento nuevo pertenece a una
decisión que alguien ya ha tomado: una segunda manera de leer la base de
conocimiento sigue siendo "knowledge search". Tres pasos, y el segundo es el que
se olvida:

1. **Escribe la función** en `_toolset.py` y añádela al toolset. Su docstring es
   el prompt; di *cuándo echar mano de esto*, no lo que hace la función.
2. **Declárala** en la tupla `tools=` de `__init__.py`. Una herramienta que el
   registro no conoce no puede aprobarse, no puede renombrarse por agent y no
   aparece en el Builder: simplemente se ejecuta.
3. **Mira el test de deriva.** `tests/test_capability_registry.py` construye cada
   capability registrada y compara la lista declarada con las herramientas que de
   verdad se le ofrecen al modelo. Es lo que detecta que se ha saltado el paso 2,
   y lo que avisa el día en que un paquete upstream renombra una de las
   herramientas que reexportamos: las tres de la capability `skills` vienen de
   `pydantic-ai-skills`, así que sus nombres son de otros.

!!! tip "Una herramienta con efectos junto a otras de solo lectura es una señal"

    `side_effecting` va por capability, así que la capability son ahora dos
    decisiones bajo un mismo nombre. Prefiere una segunda capability; el
    `approval` por herramienta en un spec deja que quien escribe un agent sea más
    estricto que el valor por defecto, y no sustituye a declarar la verdad.

## Añadir una herramienta que aquí nadie tiene que escribir { #adding-a-tool-nobody-here-has-to-write }

Si la herramienta es una llamada a una API de terceros que ya publica un servidor
MCP, plantéate si pertenece siquiera al código. Una capability es lo correcto
para algo que la plataforma tiene que garantizar; un servidor que mantiene el
fabricante es lo correcto para el resto. Ver
[MCP](../mcp.md) y
[Añade un servidor al catálogo MCP](add-mcp-server.md).
