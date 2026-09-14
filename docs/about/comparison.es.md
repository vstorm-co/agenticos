---
source_sha: "0683b5318348"
---

# Cuándo usar otra cosa { #when-to-use-something-else }

Esta página está escrita para ser útil cuando la respuesta no es AgenticOS. Una
comparación que siempre acaba igual no es una comparación, y las categorías de
abajo se solapan lo bastante como para que elegir mal cueste meses.

La versión corta: una **biblioteca** es lo adecuado para un solo agent dentro de
un producto, una **plataforma alojada** es lo adecuado cuando no quieres la
máquina, un **workspace de agents** es lo adecuado cuando el usuario es tu propio
empleado, y AgenticOS es lo adecuado cuando los agents tienen que ser editables
por alguien que no es ingeniero, gobernados por alguien que responde de ellos y
ejecutarse en hardware que tú controlas — las tres cosas a la vez.

## Las categorías { #the-categories }

| | Qué es | Cuándo usarlo en su lugar |
|---|---|---|
| [Pydantic AI](https://ai.pydantic.dev) | La biblioteca de agents sobre la que corre AgenticOS | Estás construyendo un solo agent, en Python, como parte de un producto |
| LangGraph, LangChain, LlamaIndex, elizaOS | Bibliotecas y frameworks para componer llamadas a modelos | Lo mismo — quieres código, no una plataforma, y te parece bien hacerte cargo del despliegue |
| [Cloudflare OS](https://github.com/cloudflare/cloudflare-os) | Un workspace de agents de código abierto sobre Cloudflare Workers | Tus usuarios son tus propios empleados, ya estás en Cloudflare y quieres apps por persona más que un catálogo de agents gobernado |
| [Glean](https://www.glean.com) | Búsqueda empresarial alojada con agents encima | Quieres más de 275 connectors conscientes de las ACL indexados para ti y los datos pueden vivir en la nube de un proveedor |
| Dify, Flowise | Constructores visuales de agents, autoalojables | Quieres el constructor y un lienzo de workflows, y el modelo de governance te importa menos que la rapidez con la que alguien puede montar un flujo |
| Plataformas empresariales de agents alojadas | Plataformas de código cerrado que se venden con un equipo de implantación | Quieres que sea otro quien responda del resultado y el coste de la licencia no es la restricción |
| OpenAI Assistants, Bedrock Agents | Runtimes de agents alojados | Estás a gusto con un solo proveedor y no necesitas los datos en tu propio hardware |

## Código abierto no es lo mismo que autoalojable { #open-source-is-not-the-same-as-self-hostable }

Son dos promesas distintas y la diferencia decide despliegues.

**Código abierto** significa que puedes leer el código y hacerle un fork.
**Autoalojable** significa que puedes ejecutarlo de principio a fin sobre
infraestructura que ya posees, sin ninguna dependencia de la plataforma del
proveedor.

AgenticOS necesita PostgreSQL con pgvector, Redis y Docker. Nada más, ninguna
cuenta en ningún sitio, y las únicas peticiones salientes son las que hacen tus
agents. Esa es toda la superficie de despliegue, y por eso puede ejecutarse
dentro de la red de un hospital o en un entorno aislado de la red.

Cloudflare OS está bajo Apache-2.0 y es genuinamente abierto, y está construido
sobre Durable Objects, Dynamic Workers y Cap'n Web. Ejecutarlo fuera de
Cloudflare significa ejecutar `workerd` tú mismo, y el propio README del proyecto
señala que la documentación para eso todavía no está escrita. Si la restricción
del despliegue es "esto no puede depender de una nube concreta", eso es lo
primero que hay que comprobar.

!!! info "Ninguna de las dos posturas es errónea"

    Construir sobre las primitivas de una sola plataforma es la vía por la que
    Cloudflare OS consigue sandboxing por documento y acceso acotado por
    capabilities que son de verdad difíciles de reproducir sobre infraestructura
    corriente. Es un intercambio, y qué lado de él quieres depende de dónde tenga
    que ejecutarse el software.

## Cloudflare OS { #cloudflare-os }

Lo más cercano a este proyecto por el nombre, y un producto distinto por la
forma.

**Cloudflare OS es un workspace.** Cada persona recibe un agent, un runtime en el
que escribir y ejecutar código, y apps personales que puede construir y
compartir. El modelo de seguridad es excelente: los agents empiezan sin acceso a
nada, las credenciales nunca llegan al agent, y cada recurso que un agent lee
queda registrado y se comprueba contra quienquiera que abra el resultado después.

**AgenticOS es un catálogo.** Publicas agents, y responden a personas que a
menudo no son empleados — un cliente en un widget, un usuario en Slack, un
sistema detrás de una clave de API. La unidad es un agent publicado y versionado
con un budget y un público, no el workspace de una persona.

Elige Cloudflare OS si el usuario del agent es tu propia plantilla y estás en
Cloudflare. Elige AgenticOS si el agent tiene que mirar hacia fuera, ser
gobernado agent por agent y ejecutarse donde tú digas.

## Glean { #glean }

Glean es ante todo búsqueda empresarial, con agents construidos sobre el índice.
Su punto fuerte es justo la parte que AgenticOS ni siquiera intenta: connectors a
más de 275 sistemas que llevan al índice las reglas de acceso propias de cada
documento, de modo que una respuesta nunca puede citar algo que quien pregunta no
podría abrir.

De ahí se siguen dos cosas. Si tu problema es *"nuestro conocimiento está en
cuarenta sistemas y la búsqueda no funciona"*, para eso está Glean y AgenticOS no
va a igualarlo — nuestro retrieval funciona por colección y todavía no hereda las
ACL del origen.

Si tu problema es *"necesitamos agents gobernados y los datos no pueden salir"*,
la comparación va en el otro sentido: Glean es alojado, con precio por puesto y
un mínimo empresarial, y no es algo que ejecutes tú mismo.

## Una biblioteca, y construir el resto tú mismo { #a-library-and-building-the-rest-yourself }

LangGraph, LangChain, LlamaIndex, Pydantic AI. La respuesta correcta más habitual,
y aquella con la que este proyecto menos compite: AgenticOS **corre sobre**
Pydantic AI, así que una biblioteca es la capa de debajo y no la alternativa a
ella.

Una biblioteca más una cola más una base de datos te da un agent funcionando
rápido, y para uno o dos agents eso es menos trabajo que aprenderse una
plataforma.

Usa la biblioteca directamente cuando:

- **El agent es el producto.** Su comportamiento es una funcionalidad que
  entregas, versionada con tu código, revisada en tus pull requests. Una UI que
  permite a otra persona cambiarlo no es una ventaja aquí — es una manera de que
  tu producto cambie sin una release.
- **Necesitas el bucle.** Un flujo de control propio, un grafo con ciclos, una
  política de reintentos que no expresa la abstracción de nadie más. Una
  plataforma te da un runner bien definido; eso es justo lo que estás intentando
  no tener.
- **No hay ningún no-ingeniero en la historia.** Si cada cambio lo iba a escribir
  igualmente un ingeniero, el rodeo no te aporta nada.
- **Hay un agent.** O dos. Los números de abajo solo cambian de signo a partir de
  un puñado.

Lo que asumes a cambio son las
[siete funciones](index.md#what-makes-something-an-operating-system-for-agents),
de una en una y normalmente en este orden, cada una después de haber dolido ya
una vez:

| Acabarás escribiendo | Porque |
|---|---|
| Un budget que detiene un run | Contar el gasto a posteriori no es un budget, y la primera factura sorpresa lo enseña |
| Una aprobación que se decide una sola vez | La segunda decisión sobre una aprobación ya decidida es una condición de carrera, y no es teórica |
| Aislamiento entre inquilinos | La primera vez que se olvida un `WHERE organization_id`, es un incidente de datos y no un bug |
| Un almacén de secretos por inquilino | Una única clave para todo el despliegue significa que una filtración es la filtración de todos los clientes |
| Un único camino de ejecución en todas las superficies | Si no, Slack y tu API no se ponen de acuerdo sobre lo que costó un agent |
| Un rastro de auditoría que registra los fallos | Un libro de cuentas que solo anota los éxitos responde a la pregunta equivocada durante un incidente |

Nada de eso es difícil. Todo eso es trabajo que no estás dedicando a tu producto,
y es exactamente en lo que consiste esta plataforma.

!!! info "La línea está más o menos en el quinto agent"

    O antes, en la primera persona que necesita cambiar lo que dice un agent y no
    tiene acceso de commit. Hasta ahí, una biblioteca y una cola son menos
    trabajo y deberías usarlas.

Y si de todos modos vas a construir esas seis filas, las
[siete funciones](index.md#what-makes-something-an-operating-system-for-agents)
son una especificación razonable contra la que construir — uses o no esta.

## Resumen { #recap }

- Usa una **biblioteca** para un solo agent dentro de un producto; usa esto para
  un catálogo de ellos — la línea está en el quinto agent, o en el primer
  constructor que no es ingeniero.
- **Código abierto y autoalojable son promesas distintas** — comprueba cuál
  necesitas de verdad.
- **Cloudflare OS** es un workspace para empleados; esto es un catálogo de agents
  que miran hacia fuera.
- **Glean** gana en connectors y en búsqueda consciente de las ACL; esto gana
  cuando los datos no pueden salir de tu infraestructura.
- **Construirlo tú mismo** es lo correcto hasta aproximadamente el quinto agent,
  y las siete funciones son la especificación en cualquiera de los dos casos.
