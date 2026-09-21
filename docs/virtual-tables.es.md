---
source_sha: "fd68c2def472"
---

# Virtual Tables { #virtual-tables }

Una **virtual table** es una tabla tipada de registros que una organización mantiene
para sus agents, workflows e integraciones: pedidos por conciliar, archivos por
procesar, leads a los que dar seguimiento.

Las tablas son metadatos más JSONB. Nada crea una tabla SQL física, así que crear una
tabla cuesta una fila, renombrar una columna no cambia ningún registro y ningún tenant
puede hacer crecer el catálogo de la base de datos. Toda lectura y escritura pasa por
un único servicio, `VirtualTableService`, de modo que la consola, las herramientas del
agent, los nodos de workflow y la API pública comparten las mismas reglas. Esta página
describe el servicio y sus rutas HTTP bajo `/api/v1/tables`; el documento OpenAPI es su
contrato.

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
| `number` | Un número finito | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Un número entero, como máximo 2^53 - 1 | igual que `number` |
| `boolean` | `true` o `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | igual que `number` |
| `datetime` | ISO 8601 con zona horaria, guardado como UTC | igual que `number` |
| `single_select` | El id de una opción | `eq` `ne` `in` `is_null` |
| `multi_select` | Una lista de ids de opciones | `contains` `is_null` |

El texto se guarda exactamente como se envía. Los espacios al principio y al final, los
saltos de línea y los valores formados solo por espacios son datos del usuario, así que
no se recortan. Solo se aplica un límite de longitud, y el carácter NUL se rechaza, en las celdas y también en nombres, etiquetas,
descripciones y external ids, porque PostgreSQL no puede almacenarlo.

Las comparaciones solo coinciden con celdas que tienen valor. Usa `is_null` para
encontrar las vacías.

## Cambiar un esquema { #changing-a-schema }

`PUT /tables/{id}/schema` recibe la lista completa de columnas que debe tener la tabla y
la `expected_version` que el llamante leyó por última vez. El servicio la concilia con
las columnas actuales:

- Una columna con `id` es esa columna. Una columna sin él es nueva.
- El **tipo de una columna nunca cambia**, porque los valores guardados bajo él dejarían
  de significar lo que significaban. Añade una columna nueva en su lugar.
- No se borra nada. Una columna u opción omitida se **archiva**: sus valores siguen
  siendo legibles y filtrables, y escribir en ella se rechaza con `ARCHIVED_COLUMN`.
- Una columna nueva obligatoria necesita un valor por defecto, ya que los registros
  existentes no guardan nada para ella. Una columna existente no puede pasar a ser
  obligatoria mientras algún registro no tenga valor en ella, y una columna obligatoria no
  puede volver del archivo sin un valor por defecto, porque los registros escritos mientras
  estaba archivada no podían guardar uno.
- Una `expected_version` obsoleta es un `SCHEMA_VERSION_CONFLICT`.

Los registros no se reescriben. Un registro escrito con la versión 1 sigue siendo legible
y editable con la versión 4; una columna obligatoria que nunca tuvo recibe su valor por
defecto la próxima vez que se edita el registro.

Una escritura de registro y un cambio de esquema o el archivado de la misma tabla se
turnan: la escritura espera a la que está en curso y se juzga luego según lo que esta
confirmó, así que un registro nunca cae en una tabla archivada un momento antes.

Archivar una columna, o la tabla entera, pregunta primero a cada comprobador de
dependencias registrado si algo aún la usa. Los workflows, las vistas y los triggers
todavía no existen, así que no hay ninguno registrado y nada bloquea;
`app/services/virtual_tables/dependencies.py` es donde una función registra el suyo, y
un rechazo nombra a los dependientes en `SCHEMA_DEPENDENCY`.

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
igual que las rutas, y un identificador o `Idempotency-Key` que incumpla una regla es
`INVALID_RECORD`.

Los upserts concurrentes de un mismo external id crean un solo registro. El que pierde lo
encuentra y se le responde como a una actualización: necesita la revision o se le dice
cuál enviar.

Un borrado es un borrado definitivo. El historial del registro se conserva.

## Reintentos seguros { #safe-retries }

Toda escritura de registros acepta una cabecera `Idempotency-Key` (como máximo 128
caracteres). Un reintento con la misma clave y el mismo cuerpo devuelve la primera
respuesta, con `Idempotent-Replayed: true`, y no escribe nada, aunque el registro haya
cambiado entretanto. La misma clave con un cuerpo distinto se rechaza con
`IDEMPOTENCY_KEY_REUSED`.

Una clave pertenece al llamante y al tipo de escritura, así que dos llamantes pueden usar
la misma cadena y un mismo llamante puede usarla para un create y un upsert. Solo se
guardan los éxitos: una escritura rechazada no deja recibo, de modo que la corriges y
reintentas con la misma clave.

Una repetición solo se responde a un llamante que aún pueda editar la tabla. Una vez
revocado el acceso, el mismo reintento es un 404.

## Listar y filtrar { #listing-and-filtering }

`GET /tables/{id}/records` recorre una tabla por páginas; `POST /tables/{id}/records/query`
añade filtros tipados, que deben cumplirse todos. Ambos están acotados: `limit` va de 1 a
100, `skip` es como máximo 10.000 y una consulta tiene como máximo 20 filtros.

El orden es total. Al orden pedido (`created_at`, `updated_at` o una columna ordenable) le
sigue el id del registro, de modo que una página nunca repite ni se salta un registro en
una tabla sin cambios. Los registros sin valor en la columna ordenada van al final en
ambas direcciones. Una columna `multi_select` no se puede ordenar. `updated_at` se fija al crear un registro y
avanza con cada edición, así que los registros que nadie ha editado se ordenan por su
momento de creación.

No hay `total`, porque contar una tabla filtrada no es barato. `has_more` indica si sigue
otra página.

## Qué se confirma junto { #what-commits-together }

Una escritura de registro, su fila de historial, su recibo de idempotencia y, en un
create, una fila de outbox `table.record.created` se escriben en una transacción y se
confirman o se revierten juntas. Un fallo en cualquier paso no deja ninguna. Los cambios
de tabla y de esquema se registran en el [audit log](governance.md); los cambios de
registros, en el historial por registro, que conserva los valores antes y después de cada
cambio.

Tres de estos almacenes conservan datos sin retención. El historial por registro y los
receipts guardan los valores, así que borrar un registro elimina la fila actual y deja
ambos. Un receipt guarda el registro completo tal como lo devolvió la escritura y solo
desaparece con su cuenta o su organización. Las filas de outbox guardan ids y no se purgan
tras la entrega. Trátalos como datos personales si lo son las celdas; consulta
[protección de datos](data-protection.md#the-database).

La fila de outbox es el traspaso a lo que reaccione a un registro nuevo. Por ahora nada
la consume. Un consumidor reclama las filas sin entregar en su propia sesión y las marca
como entregadas.

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
| `ALREADY_EXISTS` | 409 | El nombre de la tabla o el external id ya está en uso |
| `INVALID_RECORD` | 422 | Un valor no encaja con su columna; `details.fields` nombra cada uno |
| `ARCHIVED_COLUMN` | 422 | Un valor nombra una columna archivada |
| `INVALID_QUERY` | 422 | Un filtro u orden que la tabla no puede responder |
| `INVALID_SCHEMA` | 422 | Un cambio de esquema incoherente |
| `IDEMPOTENCY_KEY_REUSED` | 422 | La clave se usó para una solicitud distinta |
| `NOT_FOUND` | 404 | No existe esa tabla o registro, o no es alcanzable para el llamante |

## Llamar al servicio desde Python { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(ctx, TableCreate(name="Orders", columns=[
    ColumnInput(label="Customer", type="text"),
]))
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx, table.id, "ORD-1042", RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx, table.id, "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

La organización siempre viene de `ctx`, nunca de un argumento. El servicio nunca hace
commit: lo hace la sesión de la solicitud, y un worker es dueño de su propio ámbito de
sesión.

## Aún no construido { #not-built-yet }

- **Un principal para las claves de API.** El acceso, los recibos y el historial nombran
  a un usuario autenticado. Cómo actúa una clave de API sobre una tabla en la API externa
  está aún por acordar.
- Las herramientas del agent, los nodos de workflow y las pantallas de la consola, que
  llamarán a este servicio.
- Consumidores del outbox y comprobadores de dependencias para workflows, vistas y
  triggers.
