---
source_sha: "4f82ed9ae1fd"
---

# Departamentos y grupos { #departments-and-groups }

Las empresas se organizan en departamentos: ventas, finanzas, RR. HH., soporte.
En AgenticOS un departamento es un [grupo](directory.md#groups), y un grupo decide
quién puede usar qué. Finanzas puede tener sus propios agents, skills, archivos de
contexto, bases de conocimiento y servidores MCP que ventas nunca ve, mientras lo que necesita
todo el mundo sigue abierto a toda la organización.

## Añadir tus departamentos { #adding-your-departments }

**Groups** en la navegación principal lista los grupos de la organización. Un
miembro con `members:manage` los añade de uno en uno con **New group**, o varios a
la vez con **Add departments**, que ofrece Sales, Finance, HR, Support,
Engineering, Marketing, Legal y Operations, cada uno con un icono y una breve
descripción. Después se pueden renombrar, cambiar de icono o borrar como
cualquier otro grupo.

Las personas se añaden a un grupo desde su página, a mano, o mediante un
[mapeo de grupo de directorio](directory.md#directory-group-mappings) si tu
empresa ya lleva sus equipos en un directorio.

## Quién puede usar algo nuevo { #who-can-use-a-new-thing }

Crear un agent, un skill, una base de conocimiento, un archivo de contexto o un
servidor MCP compartido hace una pregunta: **quién puede usarlo** (*Who can use
it* en la consola).

| Opción | A quién llega | Se guarda como |
|---|---|---|
| **Everyone** - por defecto | A todos los miembros de la organización | Visibilidad `org` |
| **Only me** | A ti y a quien se lo compartas después | Visibilidad `private` (una base de conocimiento pasa a ser personal) |
| **Chosen groups or people** | A los miembros de los grupos que elijas y a las personas que nombres | Visibilidad `private`, compartida con cada uno a nivel `use` |

Los grupos aparecen en cuanto eliges la tercera opción; a las personas se las
encuentra escribiendo un nombre o una dirección de correo. Cada elección queda
como un chip hasta que la quitas.

Los miembros de un grupo encuentran lo que se le ha compartido, lo usan y lo
vinculan a sus propios agents. Quien está fuera del grupo no lo ve en las listas,
en la búsqueda, en los selectores del Builder, a través de la API ni a través del
AI Architect, que actúa con los permisos de quien pregunta. Los miembros cuyo rol
alcanza todos los recursos - por defecto owner, admin y builder - siguen viéndolo
todo; consulta [Permisos](permissions.md).

Las aplicaciones las publican los agents y empiezan siendo privadas para la
persona para la que se hizo el run; se comparten con un grupo desde su panel
**Share**. El panel **Sharing** de cada recurso también añade o quita grupos
después de crearlo.

## Los servidores MCP de un departamento { #a-departments-mcp-servers }

Un servidor MCP de la organización - una cuenta compartida, conectada una vez -
se limita del mismo modo, para que el servidor contable de Finanzas sea de
Finanzas. Quienes gestionan servidores MCP ven los de toda la organización, los
que conectaron ellos mismos y los compartidos con sus grupos o con ellos; owners
y admins los ven todos. Un builder fuera de Finanzas no encuentra su servidor en
la lista, no lo abre por su id y no publica un agent que lo use. Consulta
[MCP](mcp.md#personal-or-organization-wide).

Un agent que ya lo usa sigue funcionando para todos los que pueden ejecutarlo. La
elección decide quién puede escoger el servidor, no quién recibe respuestas a
través de él, por eso el Builder lo muestra donde viene el conocimiento del agent.

## La página de un grupo { #a-groups-page }

Abrir un grupo muestra sus personas y todo lo que se le ha compartido, agrupado
por tipo - agents, bases de conocimiento, skills, contexto, aplicaciones y
servidores MCP - con el nivel al que se compartió cada uno. Quien lee solo ve lo que podría abrir de todos
modos, así que un miembro de Ventas que lee la página de Finanzas no se entera de
lo que guarda Finanzas.

## De dónde viene el conocimiento de un agent { #where-an-agents-knowledge-comes-from }

Un agent puede vincularse a una base de conocimiento, un skill, un archivo de
contexto o un servidor MCP compartidos con menos gente que el propio agent, y nada lo impide. Todo
aquel al que llega el agent recibe entonces respuestas de esa fuente, incluidas
personas que no podrían abrirla por sí mismas.

La pestaña **Toolbox** del Builder muestra de dónde viene el conocimiento del
agent: a quién llega el agent y, para cada fuente, si es de toda la organización
o de qué grupos. Una fuente compartida con menos personas que el agent aparece
marcada, con un aviso encima de la lista. Si no es lo que querías, limita el agent
a los mismos grupos o amplía la fuente.

## Los grupos de la persona en las instrucciones { #the-persons-groups-in-instructions }

Las instrucciones pueden nombrar los grupos de la persona con la que habla el
agent con `{{groups}}` - por ejemplo, *"Estás ayudando a alguien de {{groups}}."* Se
convierte en los nombres de sus grupos separados por comas, o en nada para un
visitante. Consulta [Variables](reference/spec.md#variables).

## Lo que aún no cubre { #what-is-not-covered-yet }

Los presupuestos y la analítica por grupo aún no forman parte de esto.
