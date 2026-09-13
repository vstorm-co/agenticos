---
source_sha: d1e087eb1bf7
---

# La consola { #the-console }

La consola es la aplicación web desde la que se configura todo lo demás de este
sitio. Esta página es el mapa: para qué sirve cada área, y qué página la explica
como es debido.

Si buscas una pantalla concreta, el camino más rápido es el **"?"** de la
cabecera de cada página — reproduce el recorrido guiado de esa página, y una
página cuya cabecera no lleva "?" no tiene recorrido que reproducir.

## El dashboard { #the-dashboard }

La página de inicio es una **cuadrícula de widgets que tú ordenas**, y es la
respuesta a "qué está pasando" sin abrir cinco páginas.

Existen treinta y cinco tarjetas. No las verás todas: **cada tarjeta está
protegida por el permiso que necesitan sus datos**, así que un widget que no
puedes leer nunca se monta y sus consultas nunca se lanzan. Una banda vacía
desaparece junto con su título en lugar de quedarse ahí vacía.

Llegan agrupadas en bandas:

| Banda | Responde a |
|---|---|
| *(sin título, arriba del todo)* | El resumen del que el resto de la página es el detalle |
| **Deployment** | Solo para un [administrador del despliegue](permissions.md) — totales de la plataforma, salud, inquilinos más activos, valoraciones |
| **Attention** | Lo que está esperando: [aprobaciones](governance.md#approvals), fallos recientes, margen de budget, salud de MCP, conocimiento obsoleto |
| **Usage** | Runs, resultados, superficies, latencia, gasto, mezcla de modelos, comparación de versiones |
| **People** | Miembros, usuarios activos, valoraciones, quién hace qué |
| **Sandboxes** | [Capacidad, sesiones en curso, política](sandbox.md) |
| **Workspace** | Lo tuyo: tus agents, tus conversaciones, tu actividad, lo que han compartido contigo |

### Reordenarlo { #rearranging-it }

Arrastra una tarjeta, cambia su tamaño, oculta otra. La disposición es **tuya** —
ligada a ti y a la organización en la que estás, no a la organización — así que
cambiarla no cambia la página de nadie más.

Guarda una disposición como **preset** con nombre para tener más de una e ir
alternando. Un nombre repetido se rechaza en lugar de sobrescribir en silencio la
instantánea que querías conservar.

!!! info "La comprobación de permisos corre la última, sobre lo que le llegue"

    Una disposición guardada puede reordenar y ocultar, pero no puede revelar. El
    filtrado por permisos corre después de resolver la disposición, venga esta de
    la de serie o de una que tú guardaste.

## Chat { #chat }

Donde hablas con un agent publicado. El selector elige qué agent responde, y el
run se comporta exactamente igual que en Slack o detrás de la API — mismo budget,
misma puerta de aprobación, mismo rastro de auditoría, porque
[todas las superficies pasan por un único runner](channels.md).

Tres cosas del compositor que conviene saber.

**Tus propias cuentas.** Un agent ligado a
[la cuenta de cada persona](mcp.md#whose-account-a-binding-speaks-through) en un
servicio le habla como tú. Los controles del chat enumeran qué servicios del
agent necesitan una cuenta tuya y si cada uno está listo, con un botón de conexión
que abre el consentimiento del provider en una pestaña nueva. Si preguntas antes
de conectar, el agent dice que no puede llegar al servicio - y una tarjeta bajo la
respuesta ofrece ese mismo botón, así que el arreglo está a un clic del rechazo.

**Los adjuntos** se parsean y se entregan solo a esa conversación; no se añaden a
una [colección de conocimiento](file-processing.md). Consulta
[Procesamiento de archivos](file-processing.md#chat-file-uploads).

**Los comandos de barra** se expanden a un prompt antes de enviar el mensaje. Los
de serie vienen con el producto; puedes escribir los tuyos en
**Settings → Slash commands**, y ocultar cualquiera de los de serie que no uses.
Son tuyos, no de la organización.

## Para qué sirve cada área { #what-each-area-is-for }

| Área | Contiene | Lee |
|---|---|---|
| **Agents** | El catálogo, el Builder, las versiones, el uso compartido, las pruebas, la actividad | [Tu primer agent](first-agent.md) |
| **Chat** | Hablar con un agent publicado | [Superficies](channels.md) |
| **Knowledge** | Colecciones, documentos, fuentes de sincronización, ajustes de ingesta | [Procesamiento de archivos](file-processing.md) |
| **Skills** | Procedimientos escritos que un agent carga cuando hacen falta | [Skills](skills.md) |
| **Context** | Conocimiento permanente ligado a muchos agents | [Archivos de contexto](context.md) |
| **Routines** | Horarios y disparadores por evento | [Disparadores](triggers.md) |
| **Runs** | Qué se ejecutó, cuánto costó, qué tocó, si falló | [Governance](governance.md#audit) |
| **Sandboxes / Workspaces** | Sesiones aisladas de archivos y shell en las que trabajó un agent | [La sandbox](sandbox.md) |
| **MCP servers** | Conexiones a herramientas externas, personales y de toda la organización | [MCP](mcp.md) |
| **Channels** | Bots de Slack, Telegram y Mattermost, widgets, páginas alojadas | [Superficies](channels.md) |
| **Vault** | Credenciales, selladas por organización | [Secretos](secrets.md) |
| **Organizations** | Miembros, roles, invitaciones | [Permisos](permissions.md) |
| **Settings** | Providers, valores de ingesta por defecto, notificaciones, tu propio perfil | [Configuración](configuration.md) |
| **Admin** | El despliegue en sí: usuarios, inquilinos, sistema, ajustes del despliegue | [El despliegue](deployment.md) |

## Cuando una página parece vacía { #when-a-page-looks-empty }

**Un estado vacío y una petición fallida se ven igual.** Todas las páginas de aquí
se abren en varias consultas y muestran "todavía nada" cuando una de ellas falla.

Así que antes de concluir que una colección está vacía o que un agent no tiene
runs, mira la pestaña de red. Esta es, con diferencia, la forma más habitual de
que un problema real se lea como algo tranquilo.

## Recapitulación { #recap }

- El dashboard son **treinta y cinco widgets protegidos por permisos** que
  ordenas tú, guardados por persona y por organización.
- Una disposición guardada **puede ocultar y reordenar, pero nunca revelar** — la
  comprobación de permisos corre la última.
- **Chat, Slack y la API son el mismo runner**, así que lo que ves en la consola
  es lo que recibe un cliente.
- **Los comandos de barra son tuyos**, incluidos los de serie, y puedes ocultar
  los que no uses.
- Una página que muestra "todavía nada" puede ser **una petición fallida**, no un
  recurso vacío.
