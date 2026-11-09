---
source_sha: "740acc9b4b0d"
---

# Skills { #skills }

Un skill es saber hacer algo, escrito una vez y adjuntado a muchos agents: cómo
se gestionan los reembolsos, cuál es el estilo de la casa, qué comprobaciones
tiene que pasar un informe antes de salir.

Lo que sustituye es un campo de instrucciones que no para de crecer.

Veinte procedimientos en un solo prompt significa que cada run paga por los
veinte, y el vigesimoprimero empuja la conversación fuera de la ventana. Los
skills le dan la vuelta a eso:

```mermaid
flowchart LR
    A["available skills<br/><i>names + one-line descriptions only</i>"] --> B{is one relevant?}
    B -->|no| Z["no body loaded"]
    B -->|yes| C["read_skill - the body"]
    C --> D{does the body<br/>point at a file?}
    D -->|no| Z2[answer]
    D -->|yes| E["read_skill_resource - one file beside it"]
    E --> Z2
```

Veinte skills cuestan aproximadamente veinte *descripciones* en lugar de veinte
*procedimientos*.

!!! note "Descubrir es barato, no gratis"

    Cada skill vinculado está en el catálogo de capabilities que el modelo lee en
    cada turno, con su nombre y su descripción de una línea — así que vincular un
    skill cuesta tokens tanto si el modelo llega a abrirlo como si no.

    Es una línea por skill frente a un cuerpo por skill, y por eso salen las
    cuentas. No es motivo para vincular un catálogo sin límite.

La otra mitad de la cuestión es **quién los escribe**. Un skill es una fila en
la base de datos, editable en la UI, así que un responsable de soporte puede
arreglar la política de reembolsos un martes por la tarde. Sin deploy, sin pull
request, sin ingeniero.

!!! info "¿Skill, archivo de contexto o colección de conocimiento?"

    Un **skill** es un procedimiento que el modelo carga cuando decide que la
    tarea ha llegado. Un [archivo de contexto](context.md) es conocimiento
    permanente — corto, siempre relevante, inyectado o leído bajo demanda. Una
    [colección de conocimiento](file-processing.md) es un corpus demasiado
    grande para leerlo, al que se llega por búsqueda.

En Agent Builder, **Skills → New skill** permite escribir un skill sin salir del panel de capacidades. Al guardar se crea la entrada de biblioteca, se vincula al borrador actual y se activa la capacidad Skills. La publicación sigue siendo un paso separado. La acción requiere permisos para editar tanto el agente como los skills.

## La forma { #the-shape }

```markdown
---
name: refund-policy
description: When a refund is given without asking, when it needs approval, and how to say no.
category: support
---

# Refunds

Most refund questions are decided by the order date and one exception. Check
those before escalating anything.

La página **Skills** muestra en cada tarjeta el comienzo del cuerpo — sin front
matter, unas pocas líneas — con una hoja apilada detrás por cada archivo que
lleva el skill. `GET /api/v1/skills` devuelve ese comienzo como `excerpt`; el
cuerpo en sí se carga al abrir el skill.

## Decide without asking
...
```

!!! tip "`description` es el campo que decide si el skill llega a cargarse alguna vez"

    Es la única parte que el modelo ve gratis. Escríbela como **cuándo recurrir
    a esto**, no como un título.

Un skill puede llevar **recursos** — más archivos a su lado, cargados bajo
demanda. `refund-policy` incluye un `exceptions.md`, y el cuerpo dice cuándo
consultarlo.

Eso es la misma revelación progresiva un nivel más abajo: el detalle que solo
algunas conversaciones necesitan no tiene por qué estar en el cuerpo que carga
cada conversación relevante.

`category` es una de veinte sugerencias (`support`, `engineering`, `finance`,
`legal`, `security`, `marketing`, …) y alimenta el filtro del listado de skills.
No tiene ningún efecto sobre lo que ve el agent — el modelo elige por
`description`, nunca por categoría.

Los recursos de texto largos se paginan para no incluir manuales completos en cada solicitud al modelo: 8.000 caracteres por defecto y un máximo de 20.000. Pasa `args` con `offset` y `limit` a `read_skill_resource`; la respuesta indica el siguiente desplazamiento. Lee solo los fragmentos pertinentes y reutiliza el material ya cargado.

## Cómo lee uno un agent { #how-an-agent-reads-one }

A través de la [capability `skills`](reference/capabilities.md#skills). Cada skill
que recibe un agent se convierte en una **capability propia**, listada para el
modelo con su nombre y su descripción y abierta cuando hace falta:

| Cómo | Qué hace |
|---|---|
| Skills disponibles | Nombres y descripciones de una línea de todo lo vinculado a este agent |
| `read_skill` | El cuerpo completo de un skill, traído a la conversación |
| `read_skill_resource` | Un archivo al lado de un skill |

`read_skill` presenta el cargador diferido nativo del framework con nombres de
skills. Las políticas de aprobación conservan la clave estable `load_capability`,
por lo que los specs publicados y las aprobaciones pendientes siguen funcionando.
La antigua clave de aprobación `load_skill` sigue migrándose a ella. No hay una
herramienta separada para listar. `read_skill_resource` lee archivos auxiliares
solo después de abrir el skill.

Un spec vincula skills por id en `skill_ids`, así que un agent ve los que se le
dieron y nada más.

**Desde el propio skill.** Cada tarjeta de la página de Skills tiene **Add to an
agent**: eliges el agent y el skill se añade a su borrador, con la capability
Skills activada, listo para publicar en el Builder. La tarjeta dice también qué
agents usan el skill, o que todavía ninguno. Los archivos de contexto y las bases
de conocimiento ofrecen lo mismo.

**El nombre de un skill es el id con el que un modelo lo carga**, así que
tiene la forma en que los modelos escriben ids: minúsculas y dígitos unidos por
guiones simples, como `refund-policy`. Un nombre con espacios o mayúsculas se
rechaza al crear el skill. Un nombre que el modelo tuviera que reproducir
exactamente, como `Refund policy`, lo cargaba como `refund-policy`, y dos
suposiciones erróneas terminan el turno ([#1911](https://github.com/vstorm-co/agenticos/issues/1911)).

**Un skill no puede llamarse como una capability.** Cada uno se archiva bajo su
propio nombre en el mismo espacio que `knowledge`, `planning` y los demás, así que
un skill llamado `planning` en un agent que también tiene la capability de planning
es un duplicado que el framework rechaza antes del primer token. Crearlo se rechaza,
y publicar un agent vinculado a un skill con ese nombre, también.

Habilitar la capability sin ningún skill vinculado no sirve de nada — dale skills
al agent, o deja la capability apagada.

## En un workspace, un skill también son archivos { #in-a-workspace-a-skill-is-also-files }

Un agent que tiene a la vez skills y un
[workspace](reference/capabilities.md#files-shell) recibe además cada skill
escrito dentro de él:

```
/workspace/skills/<name>/SKILL.md      the body, with its name and description
/workspace/skills/<name>/<resource>    each resource, beside it
```

Esto es lo que hace útil el script de un skill. Un skill cuyo recurso era
`reconcile.py` antes se le entregaba al modelo como texto que podía citar y no
ejecutar, mientras el mismo agent tenía `execute` a una llamada de herramienta
de distancia. En disco, se ejecuta.

!!! note "No existe `run_skill_script`"

    El propio `execute` de la sandbox ya lleva las reglas de permisos del
    workspace y los techos que fija el operador. Una segunda forma de ejecutar
    cosas sería un segundo conjunto de reglas que equivocar.

## Un agent puede proponer un cambio; una persona lo hace { #an-agent-can-propose-a-change-a-person-makes-it }

Esos archivos se pueden escribir, y lo que el agent escribe **no** se aplica.

Un skill son instrucciones que sigue en cada run todo agent vinculado a él. Un
agent que pudiera editar uno directamente podría reescribir lo que hace otro
agent, dentro de una conversación que nadie está revisando, y el siguiente
lector no tendría forma de distinguir una mejora meditada de una alucinada.

Así que una escritura se convierte en una **propuesta**, y aparece encima de la
lista en la página Skills para cualquiera que pueda editar esa skill. Una propuesta
de una skill nueva aparece para cualquiera que tenga `skills:edit`. Nadie más puede
verla en la lista ni abrirla:

- **Apply** reescribe el skill y sube su versión, lo que alcanza a cada agent
  vinculado en su siguiente run.
- **Discard** conserva el registro. Un agent que propone la misma edición una y
  otra vez le está diciendo algo a alguien sobre ese skill, y una fila borrada
  lo vuelve invisible.

!!! warning "Una decisión sobre una propuesta es definitiva"

    Aplicar dos veces subiría una versión contra un cuerpo ya almacenado, y
    descartar algo aplicado le diría a un lector que nunca llegó a entrar.

La propuesta lleva el **cuerpo entero** en lugar de un diff, así que un revisor
semanas después está comparando dos versiones completas en vez de aplicando un
parche en un sitio al que nunca estuvo destinado.

Dos cosas se rechazan en lugar de adivinarse: un directorio que el agent creó
sin ningún `SKILL.md` dentro, y uno cuyo frontmatter destrozó. Y un recurso
*borrado* deliberadamente no es un cambio, porque un archivo que el modelo nunca
tocó y uno que quiso borrar dejan la misma ausencia.

Tres turnos de una conversación refinando el mismo skill dejan **una** propuesta,
no tres. A un revisor al que se le hace la misma pregunta tres veces se le ha
dado más trabajo, no más información.
Las propuestas del workspace respetan los mismos límites que los skills
almacenados: nombre de 1 a 64 caracteres y descripción de hasta 500. Una
propuesta fuera de estos límites se omite con una advertencia; sus archivos
originales permanecen intactos. Un savepoint aísla la escritura para que una
propuesta rechazada no impida guardar el estado y el coste del turno.


## Cómo llegan los skills a una organización { #getting-skills-into-an-organization }

**Escribe uno.** Skills → New, en la UI. Este es el camino normal.

**La biblioteca incluida se instala automáticamente.** Las organizaciones
nuevas reciben procedimientos de construcción de plataforma, trabajo prolongado,
investigación, visualización, Apps y presentaciones. Skills marca las copias como
`built-in`: son skills normales de la organización, no enlaces a un registro.

La etiqueta `built-in` también identifica las copias instaladas de la galería incluida, entre ellas los skills añadidos por los agentes iniciales. Indica su origen en la plataforma, no una instalación automática. La galería sigue siendo opcional y las personalizaciones existentes se pueden editar.

Las instalaciones existentes reciben nuevos skills al actualizar sus agentes
incluidos después de abrir la consola. Crear un agente desde la plantilla
predeterminada también sincroniza la biblioteca. No hace falta un seed manual.
Las copias intactas se actualizan con sus recursos; se conservan las editadas o
las distintas sin historial. Los recibos de instalación identifican una retirada
voluntaria: la actualización automática no restaura esos skills. El comando seed
explícito puede restaurarlos. El listado de skills sigue siendo de solo lectura.

AgenticOS, Architect y los nuevos agentes predeterminados incluyen:
`platform-agents`, `platform-workflows`, `platform-automation`, `durable-work`, `document-production`, `research-and-evidence`.

Los opcionales `platform-tables`, `platform-context`, `platform-skills` y las guías de API de la galería siguen disponibles en la biblioteca, pero ya no se vinculan por defecto. Las lecturas y ediciones habituales por MCP no requieren cargar un skill. Las descripciones actuales de las herramientas definen operaciones, parámetros y permisos; los skills aportan criterios de diseño y verificación. Las recetas visuales detalladas se cargan como recursos solo cuando hacen falta.

También incluyen procedimientos de Apps, visualización y presentaciones, con
narrativa y revisión. Primero se cargan nombres y descripciones; los cuerpos y
recursos solo cuando hacen falta. Los skills no conceden herramientas, cuentas
ni compiladores. Architect también recibe Apps y Charts.

La actualización protege por separado los campos personalizados de prompt,
herramientas y skills. Cambiar solo el modelo no impide actualizar las otras
opciones intactas. Los nuevos valores se aplican a agentes nuevos; no se
reescriben los agentes existentes creados por el usuario.

El MCP de plataforma permite buscar, crear y editar Context, vincular
`context_ids` a un borrador y leer/editar skills o añadir recursos de texto.
Context admite `inject` para material permanente y `link` para lectura bajo
demanda. Editar un archivo vinculado afecta al siguiente uso; cambiar el vínculo
del borrador requiere publicación. Se mantienen permisos y aprobaciones.

El skill documental incluye fuentes iniciales LaTeX y un proceso de compilación,
renderizado y revisión. Apps HTML y diapositivas web no equivalen a PDF compilado
ni PPTX editable. El agente verifica compilador, generador y renderizador reales
y declara cualquier compilación o revisión visual pendiente.

El comando de seed hace lo mismo desde un terminal, para instalaciones con
scripts:

```bash
uv run agenticos cmd seed-skills                    # every organization
uv run agenticos cmd seed-skills --org <org-id>     # one
uv run agenticos cmd seed-skills --dry-run          # say what would happen, do nothing
uv run agenticos cmd seed-skills --replace          # also overwrite copies edited here
```

Instala lo que falta y **actualiza lo que nadie ha editado**. Cada copia registra
de qué versión incluida se escribió, así que cuando una versión mejora un skill
incluido, la copia intacta de una organización se sustituye por la nueva — con sus
archivos, con la versión incrementada y una entrada de auditoría
`skill.refreshed`.

Una copia editada aquí se deja exactamente como está, así que una política de
reembolsos editada sobrevive a un reseed; `--replace` es la única forma de tomar
la versión incluida por encima de esas ediciones, y la entrada de auditoría lo
dice. Una copia hecha antes de que se registraran las versiones y distinta de la
incluida también se informa y se deja, porque nada puede decir si se editó.

El comando imprime qué hizo con cada skill, y `--dry-run` imprime el mismo plan
sin escribir.

`e2e/seed.setup.ts` también crea uno a través de la UI, que es contra lo que
afirma la suite E2E.

### La galería — setenta más, y ninguno llega sin invitación { #the-gallery-seventy-more-and-none-of-them-arrive-uninvited }

**Skills → Skill gallery** abre un catálogo de skills listos para usar agrupados
por sector: sanidad, finanzas y seguros, comercio electrónico e impresión bajo
demanda, equipos de software, sector público y utilities, servicios jurídicos y
profesionales, fabricación y logística. Diez de cada.

Elige un sector y luego instala un skill o el estante entero. Desde ese momento
es un skill normal que la organización posee y edita, exactamente igual que uno
incluido.

!!! info "La galería es opcional, y esa es toda la diferencia"

    La biblioteca incluida vive en `app/core/catalog/skills/` y se copian
    automáticamente en **todas** las organizaciones. La galería vive en
    `app/core/catalog/skill_gallery/` y no se copia en **ninguna** — la lee el
    mismo parser, desde un segundo directorio, y nunca se siembra.

    Setenta skills sectoriales en el primer directorio habrían sido setenta filas
    que nadie pidió, en cada tenant, en el siguiente deploy.

Instalar un estante del que ya tienes uno de sus skills instala el resto y deja
ese en paz: un nombre existente se omite en lugar de sobrescribirse, y la
petición responde con lo que instaló, lo que omitió y cualquier clave que este
deployment no incluya.

Añadir a la galería es igual que añadir un skill incluido — una carpeta con un
`SKILL.md`, bajo el sector al que pertenece — con una regla extra: **su nombre no
puede chocar con el de un skill incluido ni con el de otro skill de la galería,**
y es el nombre de su carpeta. La instalación empareja por nombre, así que una
colisión se saltaría en silencio para siempre. Un test lee los setenta y falla
con cualquiera de los dos errores.

### Sembrar crea copias { #seeding-copies }

Un skill sembrado es un skill normal propiedad de la organización, editable desde
el momento en que la organización existe. Es una **copia**, no un enlace.

Eso es deliberado. La gracia de un skill es que un responsable de soporte pueda
arreglar la política de reembolsos sin un deploy, y un enlace vivo a la copia del
repositorio le quitaría exactamente eso — la organización estaría leyendo un
archivo que solo un ingeniero puede cambiar.

Editar y borrar son los dos definitivos, como siempre. Deshabilitar sigue ahí
para un skill que la organización quiere conservar pero no ejecutar — cada agent
lo respeta —, pero ha dejado de ser la única forma de deshacerse de un
built-in.

### Por qué la biblioteca se distribuye y no se descarga { #why-the-library-is-bundled-and-not-fetched }

Añadir un skill a la biblioteca distribuida o a la galería es un deploy.

La alternativa — importar desde una URL de git — cuesta red saliente desde el
backend, un parser apuntando al repositorio de otra persona y una promesa sobre
un contenido que nadie aquí ha leído. Cada carpeta de
`app/core/catalog/skills/` y `app/core/catalog/skill_gallery/` es la misma
pequeña promesa que hace el [catálogo MCP](mcp.md#the-catalog): alguien lo miró.

## ¿Skills o conocimiento? { #skills-or-knowledge }

Responden a preguntas distintas, y la diferencia importa cuando un agent recibe
la equivocada.

|  | Skills | [Conocimiento](file-processing.md) |
|---|---|---|
| Contiene | Procedimiento — cómo hacemos esto | Documentos — lo que sabemos |
| Lo escribe | Una persona, deliberadamente | Se ingiere en bloque |
| Se recupera por | El modelo eligiendo un nombre | Búsqueda semántica sobre fragmentos |
| Cita | Nada; *es* la instrucción | El pasaje y su fuente |
| Escala | Decenas | Miles de documentos |

!!! example "Cuál es cuál"

    "Los reembolsos de más de 500 £ necesitan un manager" es un **skill**. El
    contrato firmado que lo dice es **conocimiento**.

    Un agent que gestiona reembolsos normalmente quiere las dos cosas, y las dos
    capabilities se componen — `skills` para el procedimiento, `knowledge` para
    la evidencia.

## Acceso { #access }

Los skills son recursos con ámbito de organización, gobernados igual que los
agents y las colecciones: visibilidad más grants por fila encima del rol.
Consulta [Permisos](permissions.md#layer-3-visibility-and-grants).

!!! important "Vincular un skill lo presta"

    Cada run del agent lee el cuerpo y los archivos, lo haya ejecutado quien lo
    haya ejecutado — así que publicar exige que el **publicador** tenga
    `skills:view` sobre esa fila.

Esa comprobación pasa por `resolve_access`, así que un grant cuenta: un miembro
con quien se compartió un skill puede vincularlo sin ser promovido.

Un skill al que no pueden llegar se rechaza como `Skill not found: <id>`,
redactado exactamente igual que un id que no existe. Los skills se vinculan por
UUID desde la API y desde un borrador editado a mano, no solo se eligen de la
lista del Builder, y un rechazo que se leyera distinto iría cartografiando los
skills privados de la organización a golpe de conjetura.

La misma comprobación se ejecuta sobre los `skill_ids` de un
[especialista inline](concepts.md#delegate-vs-inline-specialist), y se informa
con el nombre del especialista.

En tiempo de ejecución no se vuelve a comprobar nada. Los skills del spec
congelado se resuelven dentro de la organización del run y se le entregan al
agent — la regla que ya siguen las colecciones y los delegados, la de que
[la referencia se comprueba una vez, al publicar](permissions.md#delegation-is-not-a-privilege-boundary).

La alternativa es peor de dos maneras concretas:

- Todo contexto sin sujeto — una clave de API, un widget embebido, un mensaje de
  canal — es rechazado por `resolve_access` por diseño, así que una comprobación
  por runner despojaría de todos sus skills precisamente a esas superficies.
- Donde *sí* hay un sujeto, una misma versión publicada le daría a un miembro
  —cuyo rol solo alcanza los skills compartidos— instrucciones más pobres que las
  que le da a un builder, con la diferencia visible en ninguna parte.

Los skills no tienen un interruptor de activación propio: un agente puede usar
los skills que tiene vinculados. Elimina el vínculo y publica el agente para
dejar de usar ese skill. Un skill borrado después de publicar se omite con un
aviso en lugar de interrumpir el run.

## Recapitulación { #recap }

- Un skill es **procedimiento**, escrito por una persona, y solo se carga cuando
  el modelo decide que su *description* es relevante — descubrir cuesta una línea
  por skill, y el cuerpo no cuesta nada hasta que se abre.
- En un workspace un skill también son **archivos**, que es lo que hace
  ejecutables sus scripts.
- Un agent **propone** una edición; una persona la aplica, una sola vez, y la
  decisión es definitiva.
- Vincular un skill lo **presta**, así que el publicador tiene que poder verlo — y
  no se vuelve a comprobar nada en tiempo de ejecución.
- La **galería** son setenta skills listos para usar por sector, instalados a
  petición — a diferencia de la biblioteca incluida, que llegan solos.
