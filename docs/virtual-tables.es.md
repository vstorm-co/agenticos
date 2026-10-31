---
source_sha: "2adc37c143bf"
---

# Virtual Tables { #virtual-tables }

Una **virtual table** es una tabla tipada de registros que una organización mantiene
para sus agents, [workflows](workflows.md) e integraciones: pedidos por conciliar, archivos por
procesar, leads a los que dar seguimiento.

Las tablas son metadatos más JSONB. Nada crea una tabla SQL física, así que crear una
tabla cuesta una fila, renombrar una columna no cambia ningún registro y ningún tenant
puede hacer crecer el catálogo de la base de datos. Toda lectura y escritura pasa por
un único servicio, `VirtualTableService`, de modo que la consola, las herramientas del
agent, los nodos de workflow y la API pública comparten las mismas reglas. Esta página
describe el servicio y sus rutas HTTP bajo `/api/v1/tables`; el documento OpenAPI es su
contrato.


El espacio de la tabla ocupa automáticamente el área disponible, sin botón de ampliación. El panel de registro tiene su propio botón **Full screen**, que amplía todos los campos conservando las modificaciones; **Exit full screen** restaura el panel lateral. Las filas quedan directamente bajo la barra, sin un segundo marco ni un panel vacío con márgenes. El catálogo ocupa el espacio disponible, ofrece su propio botón de pantalla completa y solo muestra paginación cuando hay varias páginas.

Cada tabla muestra los campos bloqueados `created_at`, `updated_at`, `created_by` y `updated_by` del registro. Son las mismas propiedades que aparecen sobre Markdown, no copias editables en celdas. Antes de la primera actualización, `updated_at` muestra la fecha de creación. Permanecen visibles al ocultar columnas propias. Sus nombres están reservados al añadir o renombrar columnas; los nombres antiguos existentes siguen siendo legibles.

Configura un **Default value** con su tipo en los ajustes o al añadir una columna. Los registros nuevos lo usan solo si se omite el campo; un valor explícito o null tiene prioridad. Al enviar un esquema, los valores predeterminados de selección pueden usar IDs o etiquetas; el servidor guarda IDs. Elige el color de cada opción en su lista; **Automatic** conserva la paleta original. Cambiar el color mantiene los IDs y la revisión de significado de la columna.

La entrada rápida está justo después de las filas cargadas, en su área de desplazamiento. El CSV de la consola incluye las cuatro propiedades del registro. Las exportaciones API mantienen su formato salvo que se solicite `include_metadata: true`. Al crear una tabla desde un CSV exportado se omiten las propiedades del sistema; los registros importados reciben nuevos metadatos del sistema.

## Clientes externos { #external-clients }

Las claves de API de la organización se aceptan en `/api/v1/tables`. Envía
`Authorization: Bearer aos_…`; la organización procede de la clave. Leer requiere
`tables:view`, escribir registros y esquemas `tables:edit`, y crear una tabla
`tables:create`. Se aplican tanto el acceso actual del emisor como los permisos de
la clave. El historial y los recibos identifican al emisor; la clave no amplía su
acceso. Una tabla inaccesible responde `404`, un permiso de colección ausente `403`,
una revisión obsoleta `409`, y una consulta o registro no válido `422`. Repetir una
escritura con el mismo `Idempotency-Key` y cuerpo devuelve el resultado original
sin otro evento de creación.

`POST /api/v1/tables/{id}/records/query` acepta `columns` (hasta 100 IDs de columnas
activas) además de filtros, orden, skip y limit. Solo esas celdas y etiquetas de enlaces
llegan a la respuesta. `null` conserva el registro completo; `[]` devuelve solo
metadatos. Las columnas calculadas se evalúan antes de la proyección, sin tener que
seleccionar sus dependencias. Los mismos registros aparecen inmediatamente en la
consola; el trigger de la tabla se ejecuta de forma asíncrona sin retrasar el CRUD.

## Cómo se construye una tabla { #how-a-table-is-built }

| Parte | Qué es | Identidad |
|---|---|---|
| **Table** | Un nombre, un propietario, una visibilidad y grants, como un [archivo de contexto](context.md) | `id`, estable |
| **Schema version** | Una instantánea inmutable de las columnas. Un cambio añade la versión N+1 | `version` |
| **Column** | Una etiqueta, un tipo, si puede estar vacía y un valor por defecto opcional | `id`, estable |
| **Option** | Una opción de una columna select | `id`, estable |
| **Record** | Valores de celda indexados por el id de la columna, una revision y un `external_id` opcional | `id`, estable |

Los valores se indexan por el **id** de la columna, nunca por su etiqueta. Por eso
renombrar reescribe una versión del esquema y ningún registro. Un registro recuerda la
versión del esquema con la que se escribió por última vez.

Un registro guarda solo las celdas que tienen valor. Una celda enviada como `null` se
vacía, y una lectura no muestra nada para ella. En un create, el valor por defecto de una
columna rellena solo las celdas que omites; una celda que envías como `null` queda vacía.

## Tipos de columna { #column-types }

| Tipo | Se guarda como | Filtros |
|---|---|---|
| `text` | Texto de hasta 1.000 caracteres | `eq` `ne` `contains` `starts_with` `in` `is_null` |
| `long_text` | Texto de hasta 100.000 caracteres | igual que `text` |
| `rich_text` | Fuente Markdown de hasta 100.000 caracteres | igual que `text` |
| `email` | Una dirección con una `@` y un punto en el dominio, de hasta 254 caracteres | igual que `text` |
| `url` | Una dirección `http` o `https` con host, de hasta 2.048 caracteres | igual que `text` |
| `phone` | Dígitos, espacios y `+ ( ) - . /`, al menos cinco dígitos | igual que `text` |
| `number` | Un número finito | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Un número entero, como máximo 2^53 - 1 | igual que `number` |
| `rating` | Un número entero de 1 a 5 | igual que `number` |
| `boolean` | `true` o `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | igual que `number` |
| `datetime` | ISO 8601 con zona horaria, guardado como UTC | igual que `number` |
| `single_select` | El id de una opción | `eq` `ne` `in` `is_null` |
| `multi_select` | Una lista de ids de opciones | `contains` `is_null` |
| `link` | Una lista de hasta 100 ids de registros de la tabla que enlaza | `contains` (un id de registro) `is_null` |
| `lookup`, `rollup` | Nada: se calcula al leer un registro | ninguno |
| `formula` | Nada: se calcula al leer el registro a partir de sus otras columnas | ninguno |

El texto se guarda exactamente como se envía. Los espacios al principio y al final, los
saltos de línea y los valores formados solo por espacios son datos del usuario, así que
no se recortan. Solo se aplica un límite de longitud, y el carácter NUL se rechaza, en las celdas y también en nombres, etiquetas,
descripciones y external ids, porque PostgreSQL no puede almacenarlo.

Las comparaciones solo coinciden con celdas que tienen valor. Usa `is_null` para
encontrar las vacías. `contains` y `starts_with` toman un trozo de un valor, así que
`@example.com` encuentra en una columna `email` las direcciones de un dominio.

Las herramientas de tablas de un agente y los pasos de tabla de un workflow nombran una
elección por la etiqueta de su opción, sin distinguir mayúsculas: escriben y filtran por
etiqueta, y leen las elecciones de un registro como etiquetas, también la de una opción
archivada. Un valor que no nombra ninguna opción activa se rechaza con las opciones de
la columna.

### Texto enriquecido y Markdown { #rich-text }

Elige **Rich text (Markdown)** para notas con encabezados, listas, tareas, tablas, enlaces y código. Al pulsar la celda se abre el panel del registro. **Write** edita el Markdown con resaltado de sintaxis; **Preview** muestra la vista previa y **Expand editor** abre un espacio mayor. Los registros de solo lectura empiezan en vista previa y permiten leer la fuente. Las imágenes remotas aparecen como enlaces y no se cargan automáticamente.

Las propiedades del documento aparecen encima del editor Markdown. **Created**, **Last updated** y **Created by** proceden del registro y no se pueden modificar mediante Markdown. La fecha de actualización sigue las escrituras de todo el registro, incluidas otras celdas; antes de la primera actualización se muestra la fecha de creación.

Las propiedades de texto propias se añaden, editan y eliminan sin escribir YAML. Las propiedades estructuradas importadas se conservan en modo de solo lectura. El frontmatter importado no válido se conserva con un aviso; editar el contenido no lo elimina. Editar el contenido conserva los bytes originales de la cabecera; cambiar una propiedad serializa solo la cabecera YAML. La API y CSV siguen incluyendo el frontmatter propio con Markdown, mientras las fechas y el autor permanecen en los metadatos del registro.

Elige una plantilla predeterminada al crear una columna de texto enriquecido o en **Columns**. Puedes personalizar un documento vacío, una nota, notas de reunión o una descripción de proyecto. Se utiliza el `default` existente de la columna: consola, API y workflow lo aplican al crear cuando se omite la celda. Un valor explícito, incluida una cadena vacía, tiene prioridad. Cambiar la plantilla solo afecta a registros nuevos. **Use column template** sustituye el contenido de un documento existente tras confirmar y conserva sus propiedades. Las consultas de texto y las conversiones mantienen sus contratos anteriores.

## Enlaces, búsquedas y resúmenes { #links-lookups-and-rollups }

Una columna `link` guarda registros de otra tabla, o de la misma, indicada por
`link_table_id`. Al escribir se comprueba que cada registro existe en esa tabla
y que quien escribe puede verla, así que un enlace no sirve para averiguar qué
ids tiene una tabla privada. Un registro devuelve sus enlaces con nombre, en
`links`, por el primer valor de texto de cada registro enlazado, y si no, por su
id externo. Un registro enlazado que se borró después simplemente desaparece.

Un `lookup` lee una columna de los registros enlazados a través de una columna de
enlace de la misma tabla (`link_column_id`, `target_column_id`): los valores, y
una elección por su etiqueta. Un `rollup` calcula algo a partir de ellos:
`count` de los enlaces, o `sum`, `avg`, `min` o `max` de una columna de números -
`min` y `max` también de fechas. Ambos se calculan al leer el registro y nunca se
guardan, escriben, filtran ni ordenan.

Lo que muestra una búsqueda no llega más allá de lo que su lector puede ver: una
tabla enlazada que el lector no ve deja los enlaces sin nombre y vacía cada
búsqueda y resumen a través de ellos. Un enlace conserva su tabla para siempre.
Una búsqueda lee una columna con valores, no otro enlace ni otra búsqueda, y
archivar una columna de enlace se rechaza mientras algo lea a través de ella. Una
exportación escribe un enlace con los nombres de sus registros y una búsqueda con
lo que leyó.

## Fórmulas { #formulas }

Una columna `formula` calcula un valor a partir de las otras columnas del
registro: `{Price} * {Quantity}`, `IF({Total} > 100, "large", "small")`,
`ROUND({Total} / {Count}, 2)`, `DAYS({Due}, TODAY())`. Una columna se nombra por su
etiqueta entre llaves, y renombrarla reescribe cada fórmula que la nombra. Una
fórmula calcula con `+ - * / %`, compara con `= <> < <= > >=`, une condiciones con
`and`, `or` y `not`, y llama a `IF`, `ROUND`, `ABS`, `MIN`, `MAX`, `CONCAT`, `LEN`,
`UPPER`, `LOWER`, `DAYS` y `TODAY`. Una elección se lee por su etiqueta.

Puede leer cualquier columna viva con valores, incluido el resultado de una
búsqueda o un resumen, pero no un enlace ni otra fórmula, y una columna que lee
una fórmula no se puede archivar. Guardar el esquema comprueba la fórmula y dice
qué le pasa. Un valor que no puede calcular - una división por cero, texto en una
suma, una celda vacía - deja vacía la celda de ese registro. Una fórmula se
calcula al leer el registro y nunca se guarda, escribe, filtra ni ordena.

## Cambiar un esquema { #changing-a-schema }

`PUT /tables/{id}/schema` recibe la lista completa de columnas que debe tener la tabla y
la `expected_version` que el llamante leyó por última vez. El servicio la concilia con
las columnas actuales:

- Una columna con `id` es esa columna. Una columna sin él es nueva.
- El **tipo de una columna cambia solo a uno como el que se leen sus valores**, y el
  cambio reescribe el valor de cada registro. Cualquier valor pasa a texto; el texto
  pasa a número, sí/no, fecha o selección única cuando lo dice - una selección recibe
  una opción por cada valor distinto; un entero pasa a número y vuelve cuando es
  entero; una fecha pasa a fecha y hora; una elección pasa a varias y vuelve cuando es
  una. Cualquier otro cambio se rechaza, igual que uno que algún valor no supera - con
  cuántos y un ejemplo, y no se escribe nada. Lo que usa la columna lo rechaza como a un
  archivado. La revisión del registro avanza, así que una edición contra su valor
  antiguo es un conflicto.
- El texto pasa a una columna `email`, `url`, `phone` o `rating` cuando cada valor se
  lee como tal, y un número pasa a valoración cuando es un entero de 1 a 5. Cada una
  vuelve a texto, y una valoración también a número.
- No se borra nada. Una columna u opción omitida se **archiva**: sus valores siguen
  siendo legibles y filtrables, y escribir en ella se rechaza con `ARCHIVED_COLUMN`.
- Las archivadas cuentan para los límites. Una tabla tiene como máximo 100 columnas y una
  columna select como máximo 100 opciones, archivadas incluidas. Un cambio que superara
  alguno se rechaza con `INVALID_SCHEMA` y no añade versión, así que no se puede sustituir
  una lista llena de opciones; añade una columna nueva en su lugar.
- Una columna nueva obligatoria necesita un valor por defecto, ya que los registros
  existentes no guardan nada para ella. Una columna existente no puede pasar a ser
  obligatoria mientras algún registro no tenga valor en ella, y una columna obligatoria no
  puede volver del archivo sin un valor por defecto, porque los registros escritos mientras
  estaba archivada no podían guardar uno.
- Una `expected_version` obsoleta es un `SCHEMA_VERSION_CONFLICT`.
- Un envío idéntico a las columnas actuales, con los mismos ids, orden, etiquetas y
  opciones, no cambia nada: no se añade versión y se devuelve la tabla actual. Reordenar o
  cambiar una etiqueta es un cambio.

Los registros no se reescriben. Un registro escrito con la versión 1 sigue siendo legible
y editable con la versión 4; una columna obligatoria que nunca tuvo recibe su valor por
defecto la próxima vez que se edita el registro.

Cada columna lleva una **`revision`** de solo lectura, que es `0` para una columna nueva y
para toda columna que existía antes de añadirla. Cuenta los cambios en lo que *significan* los
valores de la columna, para que una [página](artifacts.md#live-data) publicada pueda saber que
la columna contra la que se publicó ya no es esa. Sube una unidad con:

- una conversión de tipo;
- un cambio en una fórmula, comparada después de propagar un renombrado, de modo que renombrar
  una columna que lee una fórmula no cuenta, pero que otra columna tome la etiqueta sí;
- un destino distinto de un enlace, lookup o rollup, o un agregado distinto;
- archivar o restaurar la columna, o archivar o restaurar una de sus opciones de selección.

Una etiqueta, un valor por defecto o una obligatoriedad nuevos, una opción de selección
renombrada y una opción nueva la dejan como estaba. Un filtro guarda ids de opción, así que
ninguno de esos cambios altera lo que coincide con un filtro. Una columna de `TableRead` se
puede devolver en un cambio de esquema tal como llegó: el campo se acepta y se ignora, y solo
el propio cambio la fija.

Una escritura de registro y un cambio de esquema o el archivado de la misma tabla se
turnan: la escritura espera a la que está en curso y se juzga luego según lo que esta
confirmó, así que un registro nunca cae en una tabla archivada un momento antes.

Archivar una columna, o la tabla entera, pregunta primero a cada comprobador de
dependencias registrado si algo que el llamante puede ver y también cambiar aún la usa.
Las vistas guardadas (ver [Vistas guardadas](#saved-views)) y los workflows que leen o
escriben la tabla registran los suyos en `app/services/virtual_tables/dependencies.py`,
y también los disparadores de tabla, que bloquean a quien archive: un disparador que
filtra por una columna que ya no existe volvería roto.

Un rechazo enumera cada
dependiente en `SCHEMA_DEPENDENCY` con su `kind`, `id` y `name`, y `name` es null para
un disparador de un workflow que el llamante no puede abrir. La consola los muestra en
el diálogo que preguntó, un workflow como enlace a él. Cualquier otro dependiente nunca
se nombra y nunca bloquea al llamante: su función se adapta al cambio por sí misma.

## Archivar y restaurar una tabla { #archiving-a-table }

Una tabla nunca se borra; se archiva. Una tabla archivada conserva sus registros,
columnas, vistas e historial, y toda lectura sigue respondiendo. Toda escritura se rechaza
con `TABLE_ARCHIVED`, la pida quien la pida: no se crea, cambia ni borra ningún registro,
y no cambian ni su nombre ni sus columnas. Su nombre queda libre para una tabla nueva, y
sigue contando para el [límite de tablas](#limits-and-retention) de la organización.

En la consola, un miembro que puede editar la tabla encuentra **Archive table** en el
menú **More actions** de su página. El diálogo explica qué hace archivar antes de que
cambie nada. Un workflow publicado que aún lee o escribe la tabla, y que el llamante
puede editar, rechaza el archivado con `SCHEMA_DEPENDENCY`, y el diálogo lo muestra como
enlace. Las vistas guardadas y los triggers solo bloquean el archivado de una columna.

La página de una tabla archivada indica cuándo se archivó. Para un miembro que puede
editar la tabla, el aviso incluye **Restore**, que la devuelve con su nombre; cualquier
otro lee sus registros y se le dice quién puede restaurarla. El catálogo muestra las
tablas activas hasta que se elige **Archived included** encima de él, y la tarjeta de una
tabla archivada indica que está archivada.

| Acción | Ruta | Se rechaza con |
|---|---|---|
| Archivar | `POST /tables/{id}/archive` | `SCHEMA_DEPENDENCY` (409) mientras algo use la tabla. Archivar dos veces no es un error |
| Restaurar | `POST /tables/{id}/unarchive` | `BAD_REQUEST` (400) si la tabla no está archivada; `ALREADY_EXISTS` (409) si entretanto una tabla activa tomó su nombre |

Ambas necesitan el derecho a editar esa tabla, por rol o por un grant sobre ella, y
cualquier otro recibe un 404. `can_edit` es false en una tabla archivada, así que
`TableRead.can_restore` dice si este llamante puede restaurarla. Cada una se audita, como
`table.archived` y `table.unarchived`, y cuenta para el límite de escrituras de tablas.
Si entretanto el nombre se tomó, se cambia primero en la tabla activa, porque una
archivada no se puede renombrar.

## Registros y revisions { #records-and-revisions }

Cada registro tiene una `revision`, que empieza en 1 y sube con cada cambio.

| Operación | Ruta | Necesita `expected_revision` |
|---|---|---|
| Crear | `POST /tables/{id}/records` | No |
| Actualizar celdas indicadas | `PATCH /tables/{id}/records/{record_id}` | Sí |
| Borrar | `DELETE /tables/{id}/records/{record_id}?expected_revision=` | Sí |
| Upsert | `PUT /tables/{id}/records/by-external-id/{external_id}` | Solo si el registro existe |
| Leer, exists | `GET .../records/{record_id}`, `.../by-external-id/{external_id}`, `.../exists` | No |

Una actualización o un borrado que indica una revision antigua se rechaza con
`REVISION_CONFLICT` (409) y `details.current_revision`; no se sobrescribe nada. Lee el
registro de nuevo y reintenta. Un upsert que encuentra un registro existente y no recibe
`expected_revision` obtiene `REVISION_REQUIRED` (428), de nuevo con la revision que debe
enviar.

Un external id tiene de 1 a 255 caracteres y puede contener `/`, como en `2026/ORD-1`. No puede contener NUL ni un salto de línea. El servicio lo comprueba
igual que las rutas. Por HTTP la ruta lo rechaza primero, con `VALIDATION_ERROR`; un
llamante que usa el servicio directamente recibe `INVALID_RECORD`.

Los upserts concurrentes de un mismo external id crean un solo registro. El que pierde lo
encuentra y se le responde como a una actualización: necesita la revision o se le dice
cuál enviar.

Una actualización que dejaría cada celda como está no cambia nada. La revision se mantiene,
no se escribe fila de historial ni receipt, y se devuelve el registro actual. Una
`expected_revision` obsoleta sigue siendo un conflicto, porque se comprueba primero. Un
upsert que encuentra el registro sigue la misma regla.

Un borrado es un borrado definitivo. El historial del registro se conserva hasta que su retención lo elimina.

## Editar registros en la consola { #editing-in-the-console }

El catálogo y las vistas Table, Kanban y List comparten un panel con búsqueda y vistas guardadas. **Add record** usa dos columnas en pantallas grandes y una en el teléfono; el texto largo y los vínculos conservan todo el ancho. El panel del registro usa el control de teclado y foco compartido de la consola. **Columns** pliega las opciones existentes bajo su número. Los errores al cargar registros ofrecen **Retry**.

Las tarjetas del catálogo dicen cuántos registros y columnas activas tiene cada tabla,
quién puede verla y cuándo cambió por última vez. En la página de una tabla, cada
cabecera muestra el tipo de su columna con un icono, los números van alineados a la
derecha y las fechas se leen como las escribe tu idioma. El panel de un registro lleva
como título su primera columna y dice cuándo se añadió y cuándo cambió por última vez.

Un miembro que puede editar la tabla añade, cambia y elimina registros desde su página.
**Add record** pide un valor por cada columna activa, con el tipo de la columna. Una
columna obligatoria sin valor predeterminado lleva la marca `*` y hay que rellenarla
antes de escribir el registro; cualquier otra columna vacía toma su valor
predeterminado. Al hacer clic en una celda se edita en su sitio: Enter o hacer clic
fuera la guarda, Escape la deja sin cambios, y un sí/no que no puede quedar vacío
cambia con un clic. Las flechas mueven entre celdas, y el botón de expandir al final de
una fila abre el registro entero.

La línea bajo la cuadrícula añade registros mientras escribes: lo que escribes va a la
primera columna de texto, y Enter crea el registro y deja la línea lista para el
siguiente. Una tabla con otra columna obligatoria abre en su lugar **Add record** con el
valor escrito ya puesto, así que no se escribe nada hasta que están todos los valores
obligatorios.

Cada edición es un `PATCH` contra la revisión que se ve en pantalla, así que una
edición que pierde frente a un cambio más reciente se rechaza en lugar de escribirse
encima. El registro se abre entonces con el valor rechazado junto a **Reload and
reapply**. Marcar filas ofrece **Delete** para todas, cada una contra su propia
revisión: un registro que alguien cambió entretanto se conserva, y la consola dice
cuántos. El panel del registro elimina uno solo de la misma forma.

Un borrado espera unos
segundos con **Undo** en su aviso antes de enviarse; los registros salen de todas las
vistas a la vez, y Undo los devuelve intactos. Un miembro que solo
puede ver la tabla ve la misma cuadrícula en modo lectura, y hacer clic en una fila abre
el registro.

Para un miembro que puede editar la tabla, la cabecera de una columna abre un menú.
**Sort ascending** y **Sort descending** ordenan la cuadrícula por ella, y **Hide in this
view** la quita de la pantalla hasta que el botón de columnas ocultas la vuelve a mostrar;
**Save view** guarda ambas cosas. **Rename** y **Archive column** cambian la tabla para
todos, cada una como la misma nueva versión del esquema que escribiría el diálogo
Columns, y un archivado de algo que aún se usa se rechaza, con los workflows, vistas y
disparadores enumerados en el diálogo. El **+** tras la última columna añade una, opcional al principio.

El tipo de una columna cambia en **Columns**, a los tipos a los que se convierten sus valores.

En **Columns**, **Required** hace que una columna necesite un valor, y una columna
archivada pasa a **Archived columns**, donde **Restore** la devuelve con sus valores.

### Importar y exportar { #import-and-export }

Las exportaciones leen como máximo 4 MiB de JSON descomprimido por página (o un
registro), con hasta 500 registros por página. Una organización puede transmitir
una exportación a la vez e iniciar diez por minuto. Las solicitudes adicionales
reciben `429` con `Retry-After`; vuelve a intentarlo después. El límite de inicios
se mantiene por proceso sin Redis; la base de datos sigue imponiendo una
exportación simultánea por organización.
Un cursor del servidor mantiene estable la instantánea de registros y precarga
como máximo cuatro registros. Se cierra al terminar o cancelar; las páginas
posteriores no vuelven a recorrer registros anteriores.

**Export**, bajo **…** junto a **Share**, guarda lo que muestra la página como un archivo CSV: los registros que
coinciden con los filtros y la búsqueda, en el orden de la cuadrícula, con sus columnas
visibles. `POST /tables/{id}/records/export` hace lo mismo para quien llama, con los
mismos filtros, búsqueda, orden y una lista de `columns`. Una opción se escribe como su
etiqueta, varias como `a; b`, y una celda de texto que una hoja de cálculo leería como
fórmula empieza por `'`. Más de 100.000 registros coincidentes se rechazan con
`EXPORT_TOO_LARGE` (413).

**Import**, en el mismo menú, lee un archivo CSV separado por comas o punto y coma cuya primera fila nombra
sus columnas. Cada columna del archivo se asocia a la columna de la tabla con el mismo
nombre, o a **External id**, y puede dirigirse a otra u omitirse. Un valor que no se lee
en el tipo de su columna hace fallar su fila antes de enviar nada. El resto va de 200 en
200 a `POST /tables/{id}/records/batch`, que escribe cada registro por separado y
enumera los rechazados con sus códigos, y la consola enumera cada fila fallida con su
línea. Cada registro añadido inicia los disparadores de la tabla, como cualquier otro.

Con **External id** asignado, **Update records already here** vuelve a importar un archivo
para poner la tabla al día: una fila cuyo id externo ya tiene la tabla cambia las celdas
que nombra de ese registro, en lugar de rechazarse como ocupada (`update_existing` en el
lote), y la importación cuenta lo que añadió y lo que actualizó.

**New table** empieza con una columna **Name**. Primero indica el nombre y las columnas; la descripción y la visibilidad están en **More options**, con visibilidad privada por defecto. En su lugar puede empezar desde un
archivo: **Start from a CSV file** convierte la cabecera en columnas y da a cada una el tipo más estrecho
en que se leen todos sus valores - entero, número, sí/no, fecha, fecha y hora ISO, una dirección de correo o un enlace -
y si no, texto, o texto largo cuando un valor tiene un salto de línea o pasa de 1.000
caracteres. El nombre sale del archivo, y ambos se pueden cambiar antes de crear, lo
que cuesta menos que un cambio de tipo después. Cuando la tabla existe, la importación se abre
con cada columna ya asignada, y después se abre la tabla.

## Reintentos seguros { #safe-retries }

Toda escritura de registros acepta una cabecera `Idempotency-Key` (como máximo 128
caracteres). Un reintento con la misma clave y el mismo cuerpo devuelve la primera
respuesta, con `Idempotent-Replayed: true`, y no escribe nada, aunque el registro haya
cambiado entretanto. La misma clave con un cuerpo distinto se rechaza con
`IDEMPOTENCY_KEY_REUSED`.

La cabecera marca un create, update o upsert repetido. Un borrado repetido responde 204
como la primera vez y no se marca.

Una clave pertenece al llamante y al tipo de escritura, así que dos llamantes pueden usar
la misma cadena y un mismo llamante puede usarla para un create y un upsert. Solo se
guardan los éxitos: una escritura rechazada no deja recibo, de modo que la corriges y
reintentas con la misma clave.

Una repetición solo se responde a un llamante que aún pueda editar la tabla. Una vez
revocado el acceso, el mismo reintento es un 404.

Un receipt dura 24 horas. Después la clave se olvida, y la misma clave con el mismo cuerpo
es una escritura nueva: se ejecuta de nuevo en vez de devolver la primera respuesta.
Reintenta dentro de la ventana y trata una pausa más larga como una solicitud nueva. La duración se aplica al usar la
clave, así que se cumple a la hora exacta; el barrido diario solo recupera el espacio de los
receipts que nadie reintentó.

## Listar y filtrar { #listing-and-filtering }

`GET /tables/{id}/records` recorre una tabla por páginas; `POST /tables/{id}/records/query`
añade filtros tipados, que deben cumplirse todos. Ambos están acotados: `limit` va de 1 a
100, `skip` es como máximo 10.000 y una consulta tiene como máximo 20 filtros.

`search` es el texto que un registro debe contener, sin distinguir mayúsculas, en
cualquier columna activa de texto o texto largo o en la etiqueta de una opción de
selección que guarda. Se combina con los filtros, y una búsqueda en blanco no busca
nada. Una vista guardada la conserva junto a sus filtros. En la consola la envía el
cuadro de búsqueda, y **Filter** escribe las condiciones: una columna, un operador que
su tipo admite y un valor. Cada condición completa acota los registros al momento, y
**Save view** guarda las condiciones, la búsqueda y el orden en la vista en pantalla.

El orden es total. Al orden pedido (`created_at`, `updated_at` o una columna ordenable) le
sigue el id del registro, de modo que una página nunca repite ni se salta un registro en
una tabla sin cambios. Los registros sin valor en la columna ordenada van al final en
ambas direcciones. Una columna `multi_select` no se puede ordenar. `updated_at` se fija al crear un registro y
avanza con cada edición, así que los registros que nadie ha editado se ordenan por su
momento de creación.

Un listado no tiene `total`, porque contar una tabla filtrada no es barato: `has_more`
indica si sigue otra página. `POST /tables/{id}/records/count` responde a esa pregunta
por separado, para los filtros y la búsqueda de una consulta, y cuenta como mucho hasta
100.000; `capped` indica que coinciden más. La consola muestra ese número junto a las
pestañas de vistas, y su cuadrícula carga cien registros cada vez al desplazarse y dibuja
solo las filas visibles. Más allá de los 10.000 registros que una consulta puede saltar,
pide un filtro o una búsqueda.

## Vistas guardadas { #saved-views }

Un tablero kanban sin agrupación guardada utiliza automáticamente la única columna activa de selección única. Si hay varias, elige cuál forma los carriles. Guardar una vista conserva la agrupación. Las filas de lista nombran los campos secundarios y muestran **Unnamed record** si el título está vacío. **Triggers** ofrece **Open workflows** cuando ningún workflow se inicia aún desde la tabla.

Una **vista** es un filtro, orden y agrupación guardados sobre los registros de una
tabla - lo que guardan las pantallas de tabla/kanban/lista de la consola para que
nadie tenga que rehacer el mismo tablero en cada visita. Es un subrecurso de la
tabla, no un recurso compartible propio: una vista no tiene propietario ni grants
de su propio tipo, y `shared` significa solo "visible para cualquiera que ya tenga
`tables:view` sobre la tabla superior" - nunca amplía el acceso más allá de lo que
permite la propia tabla.

En la consola, la pantalla sin vista elegida se llama **All records**, y **+** a su
lado guarda lo que muestra como una vista nueva. Un tablero kanban usa automáticamente la única columna activa de selección única;
si hay varias, pregunta cuál forma sus carriles. Guardar una vista conserva la agrupación. Una tarjeta muestra bajo su título hasta cuatro
columnas de la pantalla, sin las vacías. Una tabla sin columna de selección única ofrece en su
lugar **Add a column**.

El propietario de una vista la cambia entre **Private** y **Shared** con el botón
junto a **Rename**. Quien gestiona la vista de otro miembro, como un administrador, no
recibe ese interruptor: compartir los filtros de una persona es decisión suya.

`GET/POST /tables/{id}/views` y `GET/PATCH/DELETE /tables/{id}/views/{view_id}` las
listan, crean, leen, actualizan y borran. La lista se pagina con `skip` y `limit`
(como máximo 100): primero las vistas propias del llamante, luego las compartidas,
cada grupo por nombre; `total` las cuenta todas. `config` es `{filters, search, sort,
visible_columns, group_by}` - una `RecordQuery` más los dos campos que solo
necesita la presentación de la consola: `visible_columns` (`null` significa cada
columna viva) y `group_by` (una columna `single_select` viva, para los carriles de
un tablero kanban).

| Campo | Significado |
|---|---|
| `kind` | `table`, `kanban` o `list` - una vista se guarda *para* un tipo |
| `visibility` | `private` (solo su propietario) o `shared` (cualquiera que vea la tabla) |
| `can_manage` | Si este llamante puede renombrarla, reconfigurarla o compartirla |
| `can_delete` | Si este llamante puede borrarla |

Listar, leer y borrar se resuelven contra la tabla (`tables:view`); crear o cambiar
una vista necesita `tables:edit` sobre la tabla, así que un propietario al que se le
retiró el permiso de edición aún puede borrar sus vistas, pero ya no reformarlas ni
compartirlas.

Cambiar o borrar una vista es más estrecho:
solo su propietario, o un llamante cuyo [scope](permissions.md) de `tables:edit`
sea `ALL` - no "cualquiera que pueda editar la tabla" - de modo que un editor
compartido no pueda redirigir en silencio el filtro guardado de otro miembro. Se
rechaza igual que cualquier otra escritura sobre un recurso individual aquí:
`NOT_FOUND` (404), nunca un 403 que revelaría la existencia de una vista a un
llamante al que se le niega. `can_manage` y `can_delete` dicen cuál de las dos cosas
puede hacer este llamante.

Archivar una columna se rechaza con `SCHEMA_DEPENDENCY`, nombrando la vista, cuando
una vista que el llamante puede ver y también cambiar aún la usa para filtrar,
ordenar o agrupar: una de las suyas o - para un llamante cuyo scope de `tables:edit`
sea `ALL` - una compartida. Ninguna otra vista bloquea el archivado ni se nombra,
porque el llamante no podría quitarla de en medio; eso incluye toda vista privada de
otro miembro, que no se revela ni siquiera a un llamante con scope `ALL`. Mostrar
una columna en `visible_columns` tampoco bloquea.

Lo que una vista aún nombra de una columna que ya no está viva se omite al leer la
vista: un filtro sobre ella desaparece, un orden por ella vuelve a `created_at`, una
agrupación por ella se vacía, y sale de `visible_columns` - una vista que ya no
muestra ninguna de sus columnas elegidas muestra todas las vivas. La configuración
guardada no se reescribe.

### Páginas y vistas { #views-for-pages }

Un [artefacto](artifacts.md#live-data) publicado no lee a través de una vista. Sus bindings
son **page queries**: una tabla, filtros, un orden, un límite y los campos que lee la página,
que la plataforma guarda en la versión de la página al publicarla. Un binding puede partir de
una vista guardada - un agent encuentra una con `list_views`, que devuelve el id de cada vista,
sus columnas y si está compartida, para las tablas que puede leer - pero los filtros y el orden
de la vista se **copian** entonces a la página.

Editar, compartir, renombrar o borrar la vista
después no cambia nada en la página, y los `visible_columns` y `group_by` de una vista se
ignoran: los `fields` del binding deciden las columnas.

Una vista con búsqueda de texto libre no se puede vincular, porque una búsqueda coincide con
todas las columnas de texto vivas y se ampliaría al añadir columnas; la publicación se rechaza
y nombra la vista. Lo mismo ocurre con una vista cuyo filtro nombra una columna que ya no existe.

Quién puede leer los registros de la página no lo decide la vista. Se leen con el acceso del
propietario de la página, una vez que este ha consentido, y el acceso a una tabla es todo o
nada: `read` da todas las filas y todas las columnas vivas. Una page query es la forma en que
las filas de una tabla llegan a gente que no podría abrirla, y primero se pregunta al
propietario. Consulta [Artefactos](artifacts.md#consent-the-owner-decides-who-reads-the-data).

Una page query registra la `revision` de cada columna que alcanza: sus campos, las columnas de
sus filtros y de su orden, las entradas de una fórmula, el enlace y el destino de un lookup o
rollup, y la columna por la que cada tabla vinculada etiqueta sus registros. Un binding pasa a
`unavailable` (`source_changed`) cuando una de esas columnas cambió de significado o se archivó,
o cuando se archivó una tabla que alcanza, y los demás bindings siguen funcionando. Nada
impide por ello un cambio de tabla: una página no es una dependencia que bloquee un archivado.
`share_view` ya no existe; no hay una vista privada que compartir para una página.

## Triggers { #triggers }

Las columnas Kanban cargan 25 tarjetas por página. **Load more** conserva las tarjetas existentes; un error de página permite reintentar. Los cambios de agrupación pueden guardarse en la vista activa. Al leer una vista privada después de que otro miembro cambie los tipos de columna, se eliminan filtros, ordenación y agrupación incompatibles de la respuesta sin reescribir la vista guardada de su propietario. Una consulta de página que pierda un filtro requiere renovar el consentimiento.

Los eventos de tabla usan el reloj real al insertarse después del bloqueo de mutación, coherente con la activación del disparador. Una transacción iniciada antes de la activación puede producir un evento posterior válido. La migración `0229_table_event_wall_clock.py` cambia las marcas futuras; no reproduce eventos omitidos anteriormente, lo que podría duplicar efectos.


Un [workflow](workflows.md#when-a-table-record-is-added) cuyo nodo trigger es **Table
record** se ejecuta, una vez publicado, por lo que les pasa a los registros de su
tabla - añadirlos, cambiarlos o borrarlos, según nombre `events`; por defecto solo
añadirlos -, llegue por donde llegue: en la consola, por la API, con la herramienta de
tablas de un agent o con el paso de tabla de otro workflow. Un upsert que crea un
registro es una adición, y uno que lo actualiza, un cambio.

Publicarlo requiere acceso de lectura a la tabla y permiso para ejecutar el workflow,
porque se ejecuta como el miembro que lo publicó, nunca como el autor del registro. El
acceso de ese miembro se vuelve a comprobar con cada evento.

El trigger ejecuta la versión que lo encendió, y la siguiente publicación lo pasa a la
nueva versión. Sus filtros usan los operadores de [Listar y
filtrar](#listing-and-filtering) y se evalúan sobre el registro tal como se añadió o
se cambió, o como era antes de borrarse. Un cambio solo lo inicia cuando cambió una de
las columnas elegidas para la tabla, si hay columnas elegidas.

Pasa al run el registro: `record_id`, `event`, `values` por id de columna, los mismos
valores como `fields` por etiqueta y `author_id`, y en un cambio o un borrado también
`before` y las columnas `changed` por etiqueta. **Triggers**, en la página de la
tabla, enumera los workflows, pausa y reanuda cada uno y abre su historial.

Un trigger solo se inicia con los registros añadidos mientras está activo. Activarlo - una
publicación o reanudarlo - toma el bloqueo de esquema de la tabla, el que espera toda escritura de
registros, así que ningún registro confirmado antes de ese momento lo inicia y nada de lo
añadido mientras estuvo apagado se reproduce. El job `workflow-table-triggers`, que se ejecuta cada diez segundos, lee el evento de
outbox de cada registro nuevo, así que un trigger arranca en unos diez segundos. Decide una vez por trigger y registra
la decisión; una segunda pasada, o un segundo worker, la encuentra y no inicia nada.

**History** lista cada decisión, de la más reciente a la más antigua, sin los valores del
registro:

| Se muestra como | Por qué |
|---|---|
| Started a run | Se cumplió cada filtro; el run está enlazado |
| Skipped | El registro no coincidió, o se añadió antes de activar el trigger |
| Blocked | Se habría iniciado a sí mismo de nuevo, la cadena superó cinco triggers de profundidad o 50 runs, o la cuota de admisión rechazó el run |
| Could not start | El miembro con el que se ejecuta ya no puede leer la tabla ni ejecutar el workflow, o no se pudo leer la creación del registro |

Un workflow que escribe en una tabla puede iniciar los triggers de esa tabla, y así
sucesivamente a través de otras tablas. Cada run lleva la cadena a la que pertenece, y un
trigger por el que la cadena ya pasó se bloquea en lugar de iniciarse otra vez: eso impide
que dos workflows que añaden registros a las tablas del otro entren en bucle. Una columna
que un trigger filtra no se puede archivar hasta que el trigger de su workflow deje de
filtrar por ella y se publique, aunque esté pausado, y una tabla por la que empieza un
workflow publicado no se puede archivar hasta que ese workflow empiece de otra forma.

## Qué se confirma junto { #what-commits-together }

Una escritura de registro, su fila de historial, su recibo de idempotencia y, en un
create, una fila de outbox `table.record.created` se escriben en una transacción y se
confirman o se revierten juntas. Un fallo en cualquier paso no deja ninguna. Los cambios
de tabla y de esquema se registran en el [audit log](governance.md); los cambios de
registros, en el historial por registro, que conserva las celdas que tocó cada cambio.

Dos de estos almacenes guardan copias de lo escrito. Un receipt guarda el registro completo
tal como lo devolvió la escritura, y el historial guarda lo que cambió, así que borrar un
registro elimina la fila actual y deja ambos hasta que su retención los elimina. Las filas
de outbox guardan ids. Trátalos a los tres como datos personales si lo son las celdas;
consulta [protección de datos](data-protection.md#the-database) y
[límites y retención](#limits-and-retention).

La fila de outbox es el traspaso a lo que reaccione a un registro nuevo: hoy, los
[triggers](#triggers). Su heartbeat reclama las filas sin despachar en su propia sesión,
evalúa cada una frente a los triggers de la tabla y la marca como despachada en la misma
transacción. Una fila sin despachar solo se elimina por su propia ventana de retención,
mucho más larga (más abajo) - un corte de carta muerta para un worker caído todo ese
tiempo, no una afirmación de que el evento llegó a recogerse.

## Límites y retención { #limits-and-retention }

Un tenant solo puede hacer crecer la base compartida hasta donde el deployment lo permita.
Cada límite es un ajuste del deployment, se aplica **por organización**, de modo que el uso
de un tenant nunca cuenta contra otro, y se rechaza con `QUOTA_EXCEEDED` (402) cuando una
escritura lo superaría.

| Ajuste | Por defecto | Limita |
|---|---|---|
| `TABLES_MAX_PER_ORGANIZATION` | 200 | Tablas de una organización. Las archivadas cuentan, porque una tabla nunca se borra |
| `TABLES_MAX_RECORDS_PER_TABLE` | 100.000 | Registros en una tabla. Actualizar un registro en una tabla llena está permitido |
| `TABLES_MAX_RECORD_BYTES` | 1.000.000 | Los valores serializados de un registro, en bytes |
| `TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION` | 1,073,741,824 | Bytes JSONB almacenados en PostgreSQL por organización entre registros, historial, recibos y outbox; el espacio de tablas e índices se cuenta aparte |

El límite total se comprueba en el savepoint de la modificación, bajo un bloqueo de la organización, antes del commit. Superarlo revierte el registro y todas sus copias, también en una fila de importación; las filas restantes se informan como rechazadas. Repetir un recibo, escribir sin cambios, leer y borrar siguen funcionando tras reducir el límite. La retención libera los bytes eliminados.

El rechazo nombra el límite y su techo en `details` (`{"quota": "records", "limit":
100000}`), nunca el contenido, y escribe una entrada `table.quota_refused` en el
[audit log](governance.md) con esos mismos dos campos. La solicitud rechazada no escribe
nada. Las escrituras están además limitadas a `RATE_LIMIT_TABLE_WRITES_PER_MINUTE` (300) por
miembro y organización, en la consola igual que por la API; un miembro por encima recibe un
429 con `Retry-After`. Consulta [configuración](configuration.md#rate-limiting).

**Qué guarda el historial.** Un create guarda el registro completo en `after`, y un delete
guarda el registro completo en `before`; el límite del registro acota ambos. Un registro
anterior al límite, o escrito antes de que se bajara `TABLES_MAX_RECORD_BYTES`, puede seguir
superándolo - su delete guarda entonces `before` como
`{"omitted": {"bytes": <su tamaño>, "limit": <el límite>}}` en vez de los valores, y aun así
se completa. Un update guarda solo las celdas que cambiaron: `before` contiene sus valores
anteriores y `after` los nuevos, y una columna ausente de un lado estaba vacía allí. Editar
una celda de un registro grande cuesta por tanto una celda, por muchas veces que se repita.

**Retención.** El [barrido de retención](governance.md#retention) diario elimina también los
datos de las tablas, de verdad y por lotes, para cada organización:

| Qué | Se elimina cuando | Ajuste |
|---|---|---|
| Receipts | Más antiguos de 24 horas | `TABLES_RECEIPT_TTL_HOURS` |
| Filas de outbox | Despachadas hace más de 3 días | `TABLES_OUTBOX_RETENTION_DAYS` |
| Filas de outbox sin despachar | Nunca despachadas y con 30 días: el heartbeat de los triggers lleva ese tiempo sin ejecutarse, y ningún trigger se iniciará para esos registros | `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` |
| Historial | Más antiguo de 365 días, para un registro borrado igual que para uno vivo | `TABLES_HISTORY_RETENTION_DAYS` |

El barrido escribe una entrada de auditoría por organización, que nombra la clase
(`table_receipts`, `table_outbox`, `table_history`) y el recuento. Son ajustes del
deployment, no por organización. Los registros y las tablas nunca los elimina.

`RATE_LIMIT_TABLE_WRITES_PER_MINUTE` es una cuota *por miembro*, así que el presupuesto de
un barrido para cada una de las tres clases escala tanto con ese límite como con el número
de miembros activos de la organización, con margen para que un rezago existente se reduzca
en vez de solo mantenerse plano - cada miembro que escribe sin parar a la vez nunca adelanta
al barrido, hasta un límite generoso de para cuántos miembros se dimensiona el barrido de una
organización. Las cifras están en
[configuración](configuration.md#virtual-tables-limits-and-retention). Un rezago mayor se
trabaja en varios barridos más, igual que en cualquier otra clase.

## Quién puede hacer qué { #who-can-do-what }

| Permission | Quién la tiene |
|---|---|
| `tables:view` | Owner, admin, builder y operator ven todas las tablas; un member o viewer ve las suyas, las visibles para la organización y las compartidas |
| `tables:edit` | Owner y admin editan todas; un builder edita las suyas y las compartidas; un member edita las suyas |
| `tables:create` | Owner, admin, builder, member |

`tables:view` y `tables:edit` son permissions de recurso, así que un [grant](permissions.md)
sobre una tabla amplía un rol solo para esa tabla: un viewer con `edit` sobre una tabla
edita esa tabla y nada más. Compartir usa las mismas rutas `/tables/{id}/sharing` que los
demás recursos compartidos. Los registros heredan el acceso de su tabla, y el esquema lo impone: una fila de records,
history u outbox referencia su tabla también a través de la organización, así que no puede
nombrar una tabla de otro tenant.

La tabla de otra organización y una a la que el llamante no puede acceder son ambas un
404. Un contexto sin sujeto autenticado no alcanza nada.

Si un llamante concreto puede editar una tabla concreta también está directamente
en la respuesta: `TableSummary.can_edit` y `TableRead.can_edit` se resuelven en el
servidor (scope del rol o un grant explícito) y se envían en cada lectura, igual
que `Agent.can_run` - así una fila del catálogo o una página de detalle nunca
tienen que adivinar si sus controles de edición serían rechazados. El propio
`can_manage` y `can_delete` de una vista guardada son la misma idea, un nivel más abajo (ver
[Vistas guardadas](#saved-views)).

## Errores { #errors }

Cada rechazo responde `{"error": {"code", "message", "details"}}`, y el `code` es lo que
un cliente usa para bifurcar.

| Código | Estado | Significado |
|---|---|---|
| `REVISION_CONFLICT` | 409 | El registro cambió desde que se leyó |
| `REVISION_REQUIRED` | 428 | Un upsert de un registro existente necesita `expected_revision` |
| `SCHEMA_VERSION_CONFLICT` | 409 | El esquema cambió desde que se leyó |
| `SCHEMA_DEPENDENCY` | 409 | Algo depende de lo que el cambio elimina |
| `TABLE_ARCHIVED` | 409 | La tabla rechaza escrituras |
| `BAD_REQUEST` | 400 | Una restauración nombró una tabla que no está archivada |
| `ALREADY_EXISTS` | 409 | El nombre de la tabla, el de una vista o el external id ya está en uso |
| `INVALID_RECORD` | 422 | Un valor no encaja con su columna; `details.fields` nombra cada uno |
| `ARCHIVED_COLUMN` | 422 | Un valor nombra una columna archivada |
| `INVALID_QUERY` | 422 | Un filtro u orden que la tabla no puede responder |
| `INVALID_SCHEMA` | 422 | Un cambio de esquema incoherente |
| `IDEMPOTENCY_KEY_REUSED` | 422 | La clave se usó para una solicitud distinta |
| `QUOTA_EXCEEDED` | 402 | La escritura superaría un límite de almacenamiento; `details` nombra el límite (`tables`, `records`, `record_bytes`, `storage_bytes`) y su techo |
| `RATE_LIMIT_EXCEEDED` | 429 | Demasiadas escrituras de tablas en el último minuto; consulta `Retry-After` |
| `VALIDATION_ERROR` | 422 | La solicitud misma es defectuosa: un tipo erróneo, un campo desconocido, un límite, o NUL, un salto de línea o un sustituto aislado en un id, clave o nombre. La ruta la rechaza antes de que se ejecute el servicio |
| `AUTHORIZATION_ERROR` | 403 | Al llamante le falta la permission que exige una ruta de colección (`tables:view`, `tables:create`) |
| `CONCURRENT_CHANGE` | 409 | Un upsert perdió una carrera con el borrado del mismo registro. Reinténtalo |
| `NOT_FOUND` | 404 | No existe esa tabla o registro, o no es alcanzable para el llamante |

## Llamar al servicio desde Python { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(
    ctx,
    TableCreate(
        name="Orders",
        columns=[
            ColumnInput(label="Customer", type="text"),
        ],
    ),
)
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx,
    table.id,
    "ORD-1042",
    RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx,
    table.id,
    "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

La organización siempre viene de `ctx`, nunca de un argumento. El servicio nunca hace
commit: lo hace la sesión de la solicitud, y un worker es dueño de su propio ámbito de
sesión.

## Añadir un tipo de columna { #adding-a-column-type }

Un tipo de columna es una entrada de `COLUMN_TYPES` en
`backend/app/services/virtual_tables/types.py`, con su nombre en `ColumnTypeName` en
`backend/app/schemas/virtual_table.py`. La entrada dice cómo se lee la celda del
registro para comparar y ordenar (un `SqlKind`), qué operadores de filtro admite, si se
ordena y qué validador atraviesa cada escritura y cada operando de filtro. El validador
devuelve el valor tal como se guarda o lanza `CellProblem` con un mensaje para quien lo
escribió. Todas las superficies llaman al mismo servicio, así que la consola, la API,
los agents y los workflows aceptan el tipo nuevo a la vez, y un [trigger](#triggers)
filtra por él con las mismas reglas.

La consola necesita el tipo en `ColumnTypeName` en `frontend/src/types/tables.ts`, un
editor en `record-cell-editor.tsx`, una opción en los diálogos de esquema y de crear
tabla, y su etiqueta en los tres catálogos de mensajes. Las pruebas van en
`backend/tests/test_virtual_table_types.py` para el validador, y en una prueba de
integración que escribe, filtra y ordena un registro del tipo nuevo.
