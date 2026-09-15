---
source_sha: "2dd7d32f5e67"
---

# Seguridad { #security }

Esta página es lo que se entrega a una revisión de seguridad con forma de HIPAA o
SOC 2: las fronteras de confianza, qué datos salen del deployment y hacia quién,
qué se cifra y dónde, y una matriz de controles que nombra — para cada control —
el mecanismo de este código que lo satisface y el test que lo sostiene.

Describe lo que **hay**, no lo que estaría bien tener. Una fila sin mecanismo lo
dice y enlaza la issue que lo construiría. Para cómo informar de una
vulnerabilidad y la lista de endurecimiento para producción, consulta
[`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md) en
la raíz del repositorio; esta página es todo lo demás, en una sola copia.

Dos páginas vecinas responden a las preguntas que una revisión hace a
continuación y no se repiten aquí: [Protección de datos](data-protection.md) para
dónde viven los datos personales, qué alcanza realmente un borrado y qué huecos
siguen abiertos, y [Licencias](licenses.md) para cada componente de terceros que
envían las imágenes.

## Modelo de amenazas { #threat-model }

La plataforma es autoalojada y multi-tenant. La suposición de diseño es que la
infraestructura del operador es de confianza y que cada petición que entra en
ella no lo es, así que las fronteras que importan son las que una petición cruza
de camino a los datos.

| Frontera | Qué la cruza | ¿De confianza al otro lado? |
|---|---|---|
| Navegador → BFF (los route handlers de Next.js) | Una cookie de sesión, la cabecera de organización, la entrada del formulario | No — pero el BFF no verifica la cookie: lee el `access_token` `httpOnly` y lo reenvía como cabecera bearer (`frontend/src/lib/platform-proxy.ts`). Es una frontera que reenvía una credencial; la verificación es trabajo de la API |
| BFF → API (FastAPI) | Un JWT ligado a una sesión en la base de datos, la cabecera `X-Organization-Id` | No — el token se verifica en cada petición, la sesión se comprueba por si fue revocada y la organización se resuelve desde el token |
| API → PostgreSQL / Redis | Consultas y lecturas de caché, sobre TLS cuando está configurado | Sí — el almacén es del operador; lo que protege en reposo está bajo «Qué se cifra y dónde» |
| API / worker → proveedores de modelos, canales, servidores MCP, proveedores de búsqueda, Logfire | Prompts, llamadas a herramientas, consultas, respuestas, trazas | No — son terceros; lo que les llega es una decisión por agent, salvo el tracing a nivel de deployment (abajo) |
| Worker → conectores (Google Drive, S3, …) | Credenciales desselladas del vault, documentos descargados | No — la credencial de un conector es un secreto del vault referenciado por id |

La autoridad dentro de un tenant nunca es un nombre de rol en una ruta: es una
fila de membresía más el catálogo de permisos (`app/core/permissions.py`),
resuelto por recurso. Dos llamantes con el mismo rol pueden alcanzar filas
distintas, porque un grant sobre un recurso amplía lo que el rol permite sin
ascender al miembro.

## Qué sale del deployment { #what-leaves-the-deployment }

Nada llama a casa. Cada llamada saliente es una que el deployment configuró, y
cada una es una frontera por la que preguntará la revisión de un cliente.

| Hacia | Qué | Cuándo |
|---|---|---|
| El proveedor de modelos configurado | El prompt, la salida del modelo, los argumentos y resultados de las herramientas | Cada run — salvo que el modelo corra en la infraestructura del propio operador, en cuyo caso no sale nada |
| El canal configurado (Slack, Telegram, Mattermost) | Las respuestas generadas por el agent — texto, imágenes y adjuntos | Siempre que un agent esté expuesto por ese canal; cada `send_message` publica en el proveedor (`app/services/channels/`) |
| Logfire | Trazas, que llevan prompts y salidas salvo que el agent diga otra cosa | Dos caminos independientes. Un token de observabilidad por agent traza ese agent, y su modo `content` decide cuánto lleva el span - `none` lo reduce a tiempo, tokens, coste y nombres de herramienta (#1413). Un `LOGFIRE_TOKEN` a nivel de deployment instrumenta **todos** los runs, tanto en la API como en el worker de Prefect (`app/core/logfire_setup.py`), así que con él puesto sale el contenido de todo agent que no haya pedido `none`; el que sí lo pidió queda fijado a una instrumentación sin contenido también en ese tracer (`suppress_content`), de modo que el modo se sostiene en ambos caminos, y un especialista de ese agent lo hereda - escrito inline o inventado a mitad del run. Un hueco que no cubre: una fijación que falla, que se registra y se deja. Ninguno de los dos caminos está activo por defecto. No hay término medio filtrado a propósito - una exportación parcialmente depurada es una garantía que nadie puede auditar ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)) |
| Servidores MCP | Llamadas a herramientas y sus argumentos | Solo para las herramientas a las que el agent está ligado |
| Un proveedor de búsqueda web (Tavily, DuckDuckGo) | La consulta de búsqueda | Solo cuando se concede la capability de búsqueda |
| Un proveedor de embeddings | El texto del documento, en la ingesta | Solo para una base de conocimiento cuyo proveedor sea remoto |

## Qué se cifra y dónde { #what-is-encrypted-where }

Hay un mecanismo de cifrado a nivel de aplicación, y es deliberadamente el único:
el vault (`app/core/vault.py`). Cada **credencial de conector y de API** en reposo
está sellada en un sobre por propietario cuya clave de envoltura se deriva, por
HKDF, de la organización (o el usuario) a la que pertenece — de modo que un texto
cifrado copiado a la fila de otra organización no se puede desellar. La clave
maestra es rotable sin volver a cifrar los payloads.

No todo lo que la plataforma almacena es una credencial del vault, y esto se dice
sin rodeos porque una revisión lo va a encontrar:

- **Tokens bearer de vida corta** — invitaciones a organizaciones
  (`OrganizationInvitation.token`), solicitudes de vinculación de canal
  (`ChannelLinkRequest.token`) y enlaces de conversación compartida
  (`ConversationShare.share_token`) — son columnas `String(64)` aleatorias
  buscadas por igualdad, no selladas en el vault. Quien tiene el valor puede
  usarlo, así que los protege la caducidad y el uso único, no el cifrado. Los
  refresh tokens de sesión son la excepción que sí se hashea en reposo
  (`sessions.refresh_token_hash`).
- **Los archivos subidos y los del chat** están en claro en el sistema de
  archivos del contenedor de la API (`app/services/file_storage.py`) —
  protegidos solo por el cifrado del volumen.
- **Los cuerpos de los mensajes, `rag_documents` y sus vectores, y los workspaces
  del sandbox** se guardan como columnas en texto plano, filas de pgvector y
  archivos del workspace. El vault sella credenciales, no contenido; la
  protección en reposo de esto es a nivel de disco.

Un backend de archivos compatible con S3 y cifrado del lado del servidor es la
respuesta a nivel de aplicación para el almacenamiento de objetos y se sigue en
[#1423](https://github.com/vstorm-co/agenticos/issues/1423).

## Matriz de controles { #controls-matrix }

Una fila por control, el mecanismo que lo satisface y el test que lo sostiene.
Encuadrado frente a las salvaguardas técnicas de HIPAA §164.312 y SOC 2 CC6–CC8.

### Control de acceso · HIPAA §164.312(a) · SOC 2 CC6 { #access-control-hipaa-164312a-soc-2-cc6 }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| Aislamiento entre tenants, incluso cuando el llamante es dueño de la fila | `resolve_access` rechaza un recurso cuyo `organization_id` difiere antes de comprobar la propiedad (`app/services/access.py`) | `test_resource_access.py::TestTenantBoundary`, `test_conversation_tenant_isolation.py`, `test_platform_flows.py` |
| Un permiso en cada ruta de colección | Dependencia de ruta `require(*perms)` en las rutas de listado, creación y catálogo (`app/api/deps.py`), catálogo en `app/core/permissions.py` | `test_platform_routes.py::TestEachRouteDemandsItsOwnPermission` |
| Las rutas por recurso autorizan en el servicio, no en la ruta | Una ruta que actúa sobre un agent, un skill o una colección no lleva gate `require()` — un gate de rol rechazaría al portador de un grant antes de que el grant se aplicara — y en su lugar llama a `resolve_access` (`app/services/access.py`) | `test_platform_routes.py::TestEveryPlatformRouteIsGuarded` (toda ruta está gateada o la decide el servicio) |
| Un grant amplía el acceso sin ascender al miembro | El `resolve_access` por recurso toma `max(alcance del rol, grant)` (`app/services/access.py`) | `test_resource_access.py::TestGrantsWidenAccess`, `::TestPermissionsGrantsCannotWiden` |
| Una mención en un canal se ejecuta como el remitente, no como el bot | Se usa el `AuthContext` propio de un remitente vinculado y activo (`app/services/channels/mentions.py`) | `test_channel_mentions.py::TestAnswer::test_the_run_carries_the_senders_own_role` |

### Autenticación · HIPAA §164.312(d) · SOC 2 CC6 { #authentication-hipaa-164312d-soc-2-cc6 }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| JWT (HS256), contraseñas con bcrypt | `app/core/security.py` — `verify_token`, `get_password_hash` | `test_security.py`, `test_auth.py` |
| Claves de API comparadas en tiempo constante | `secrets.compare_digest` (`app/api/deps.py`) | `test_auth.py`, las comprobaciones HMAC de webhooks en los adaptadores de canal |
| Sesiones en base de datos con revocación | Tabla `sessions` + `SessionService`; token ligado a un claim `sid` (`app/services/session.py`, `app/api/routes/v1/sessions.py`) | `test_session_verify.py`, `test_session_revocation.py` |
| Límite de peticiones en el login | `enforce_auth_limit` (`app/api/deps.py`) | `test_auth_rate_limit.py` |

### Controles de auditoría · HIPAA §164.312(b) · SOC 2 CC7 { #audit-controls-hipaa-164312b-soc-2-cc7 }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| Las mutaciones relevantes para la governance quedan registradas, dentro de la transacción de la petición | `record_audit` (`app/core/audit.py`) en el servicio que muta — rotación de secretos, vinculación de skill / sincronización / MCP, membresía, compartición, aprobaciones, exportaciones y más; escrito en `app_admin_audit_logs`. No es cobertura general de toda escritura (el CRUD de la base de conocimiento, por ejemplo, no se audita) | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| El rastro es legible por un auditor | `GET /audit`, gateado en `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Exportar el rastro (CSV/JSONL) | `GET /audit/export` sobre una ventana, con puerta en `audit:read`, registrando su propia lectura en el rastro; las exportaciones de runs, aprobaciones y gasto hacen lo mismo (#1422) | `test_exporting.py` (la exportación y su propia entrada de auditoría) |
| Evidencia de manipulación (una cadena de hashes) | **Todavía no** — [#1622](https://github.com/vstorm-co/agenticos/issues/1622) | — |

### Integridad · HIPAA §164.312(c) · SOC 2 CC8 (gestión del cambio) { #integrity-hipaa-164312c-soc-2-cc8-change-management }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| Un spec se rechaza al publicar, nunca en tiempo de ejecución | `validate_spec` (`app/services/agent_registry.py`) — capability desconocida, scope no concedido, `secret_id` de tipo equivocado o de otra organización, una conexión MCP personal | `test_agent_registry.py`, `test_capability_secrets.py::TestPublishValidation` |
| El budget se comprueba antes de la petición al modelo, y el coste se registra incluso si falla | `BudgetGuard.wrap_model_request` gatea antes de la llamada (`app/agents/capabilities/budget/`); el coste del run se escribe en un `finally` terminal (`app/services/agent_runner.py`) | `test_spend.py::TestBudgetGuard`, `test_agent_runner.py::…::test_a_failed_run_still_records_its_cost` |
| Una aprobación se decide exactamente una vez | `ApprovalService.decide` rechaza una fila que no esté pendiente leída `for_update` (`app/services/approvals.py`) | `test_approvals_queue.py::TestDecidingTwiceIsRefused` |

### Confidencialidad de las credenciales · HIPAA §164.312(a)(2)(iv) { #confidentiality-of-credentials-hipaa-164312a2iv }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| Ningún secreto en claro en una respuesta de la API ni en una entrada de auditoría | `SealedStr`/`CredentialStr` enmascaran cada repr; las pistas son solo los últimos 4 caracteres (`app/core/secret_kinds.py`, `app/core/vault.py`) | `test_no_secret_escapes.py` (barre toda la superficie de OpenAPI), `test_capability_secrets.py::TestInjection` |
| Los logs no forman parte de esa garantía | Una respuesta de token MCP OAuth mal formada llega a los logs a través de un `ValidationError` de Pydantic que repite su entrada — un hueco conocido, [#1626](https://github.com/vstorm-co/agenticos/issues/1626) | `test_mcp_connections.py::test_an_unreadable_token_response_does_not_echo_its_input` (documenta que el token acaba en `caplog`) |
| Una credencial está ligada a su organización en reposo | Sobre HKDF por propietario (`app/core/vault.py`); el alcance son las credenciales de conectores y de API — para los tokens bearer que no cubre, ver «Qué se cifra y dónde» | `test_secret_tenant_isolation.py`, `test_vault.py` |

### Seguridad en la transmisión · HIPAA §164.312(e) · SOC 2 CC6 { #transmission-security-hipaa-164312e-soc-2-cc6 }

| Control | Mecanismo | Sostenido por |
|---|---|---|
| TLS hacia PostgreSQL y Redis | `POSTGRES_SSLMODE`, `REDIS_SSL` (`app/core/config.py`); `doctor` informa del estado en vivo de Postgres desde `pg_stat_ssl` | Postgres, sobre una conexión real: `test_store_tls.py`; Redis, al construir la URL y en `doctor`: `test_config.py`, `test_doctor_sandbox.py` |
| Cabeceras de framing y MIME en cada respuesta; CSP en todas salvo los endpoints de la referencia de la API | `SecurityHeadersMiddleware` (`app/core/middleware.py`), cuyos `exclude_paths` quitan la CSP — no el framing ni el MIME — para OpenAPI, Swagger y ReDoc; más la CSP propia del frontend por deployment (`frontend/src/middleware.ts`), cuyo `script-src` lleva un nonce por petición y `'strict-dynamic'` en vez de `'unsafe-inline'` | `test_security_headers.py`, incluido `test_an_excluded_path_keeps_its_framing_but_drops_the_csp`; `csp.test.ts`, `middleware.test.ts` |
| HTTPS y HSTS | Terminados en el reverse proxy — el `nginx/nginx.conf` incluido pone HSTS; la aplicación no, por diseño | Asunto del deployment; ver la lista de endurecimiento |
| Límites de peticiones en las superficies públicas | Límites sobre Redis en la API de runs, el widget embed y las páginas alojadas (`app/services/rate_limit.py`); límites por remitente en los bots de canal (`app/services/channels/router.py`) | `test_rate_limited_surfaces.py`; el límite del bot de canal está implementado, pero poco testeado |

### Los rechazos como conjunto { #the-refusals-as-a-set }

Los tests de rechazo de arriba llevan el marcador `security`. `make test-security`
ejecuta todo el conjunto, y CI publica la lista recogida como artefacto
`security-tests.txt` en cada ejecución del backend (#1417) — así los rechazos se
pueden contar y leer, en vez de darlos por supuestos. Un test cuyo nombre o módulo
mencione un tenant, un permiso, un budget, una aprobación, un secreto o texto en
claro y no lleve el marcador hace fallar `tests/test_security_marker.py`, que
mantiene la lista completa a medida que crece la suite.

## El perfil HIPAA, y lo que no afirma { #the-hipaa-profile-and-what-it-does-not-claim }

Una revisión de seguridad no pregunta «¿es este software conforme?». HHS no
certifica software alguno y la OCR no reconoce certificaciones privadas.
Pregunta **¿podemos ejecutar esto dentro de nuestro entorno conforme, y podéis
demostrarlo?** — y la respuesta es una configuración que viene con el producto
más un comando que comprueba un despliegue en marcha contra ella (#1448).

```bash
uv run agenticos cmd doctor --profile hipaa
```

Una fila por control, cada una nombrando el ajuste que lo satisface o el que no,
y salida distinta de cero ante cualquier fallo, para que corra en la CI del
propio cliente. La configuración es `deploy/profiles/hipaa/`: una superposición
de compose que se niega a arrancar sin los ajustes que no puede poner por
defecto, y un archivo env comentado.

**Este párrafo se lee del tirón junto al perfil.** Responde a las salvaguardas
**técnicas**, §164.312, y solo a ellas. Las salvaguardas administrativas
(§164.308 —análisis de riesgos, formación del personal, política sancionadora,
plan de contingencia, acuerdos de business associate) y las físicas (§164.310)
son de la operadora y lo seguirán siendo. Un perfil que insinuara otra cosa sería
una afirmación que nadie puede sostener.

### La hoja { #the-sheet }

| Control | Salvaguarda | Lo satisface |
|---|---|---|
| `postgres-tls` | §164.312(e)(1) | `POSTGRES_SSLMODE=verify-full`. `require` cifra y no verifica certificado alguno, así que el perfil no lo acepta |
| `redis-tls` | §164.312(e)(1) | `REDIS_SSL=true` |
| `vault-key` | §164.312(a)(2)(iv) | Una clave maestra del vault, con la que toda credencial de proveedor y conector queda sellada por organización |
| `content-at-rest` | §164.312(a)(2)(iv) | **De la operadora.** Los datos de Postgres, el volumen de medios y la raíz de workspaces del sandbox los cifra un volumen o un disco, no esta aplicación |
| `local-model` | §164.312(e)(1) | Todo perfil de modelo servido desde tu propia red. Uno sin `base_url` es, por definición, la API pública del proveedor |
| `traces-local` | §164.312(e)(1) | `LOGFIRE_TOKEN` sin definir. Un span con `observability.content: full` lleva el mensaje, la salida y todos los argumentos de herramienta |
| `sso` | §164.312(d) | `OIDC_ISSUER`. La autenticación multifactor es del proveedor de identidad, y la hoja lo dice en vez de atribuírsela |
| `signup` | §164.312(a)(1) | `invite_only` o `closed` |
| `audit-retention` | §164.312(b) | Un suelo de auditoría de al menos 2190 días — los seis años de §164.316(b)(2) |
| `audit-chain` | §164.312(c)(1) | La cadena de hashes y su checkpoint. Detección, no prevención — véase [Controles de auditoría](#audit-controls-hipaa-164312b-soc-2-cc7) |

Tres resultados, y el del medio pesa. `ok` y `!!` son respuestas de este código.
`--` es un control que de verdad es de la operadora, **nombrado** en vez de
aprobado en silencio —una hoja que se saltara lo que no puede ver se leería como
completa y no lo estaría— y no hace fallar el comando, porque un control que
desde aquí nadie puede evidenciar es uno que nadie podría aprobar nunca.

### Quién es la business associate { #who-is-the-business-associate }

Una clienta que ejecuta esto en su propia infraestructura recibe software. Nadie
de aquí toca su PHI y no hace falta acuerdo alguno. Un despliegue que otra parte
opere para ella convierte a esa parte en business associate, y eso es un contrato,
no una casilla de configuración.

### Por qué el perfil usa por defecto un modelo local { #why-the-profile-defaults-to-a-local-model }

Un modelo alojado se lleva el contenido de cada ejecución, así que usarlo implica
un acuerdo con ese proveedor — y esos acuerdos son más estrechos de lo que la
gente supone. Una organización con HIPAA habilitado en un proveedor grande suele
excluir la ejecución de código y la descarga web, que es exactamente la forma de
las capabilities `sandbox`, `code_execution` y `web_fetch`. Quien firma uno y
luego construye un agente sobre ellas se entera durante un incidente.

La inferencia local elimina la pregunta, y por eso es el valor por defecto del
perfil y no una sugerencia.

## Resumen { #recap }

- Confía en la infraestructura del operador; no confíes en ninguna petición que
  entre en ella. Las fronteras que importan son navegador → BFF → API → almacén,
  y API/worker → terceros. El BFF reenvía la cookie de sesión; la API es donde se
  verifica una petición.
- Los únicos datos que salen son los que el deployment configuró para que
  salieran — proveedores de modelos, canales, servidores MCP, proveedores de
  búsqueda y de embeddings, y Logfire — que es opcional y, en cuanto se pone un
  token a nivel de deployment, traza todos los runs que sirve el proceso de la
  API, con el contenido de todo agent que no haya pedido `none`.
- Las credenciales de conectores y de API están selladas por organización en el
  único vault; los tokens bearer de vida corta y el contenido en reposo
  (archivos, mensajes, RAG, sandboxes) no lo están, y
  [#1423](https://github.com/vstorm-co/agenticos/issues/1423) es la respuesta a
  nivel de aplicación para el almacenamiento de objetos.
- Cada control de la matriz nombra un mecanismo y un test, y nombra sus huecos en
  la misma frase — la evidencia de manipulación y el cifrado de archivos a nivel
  de aplicación enlazan la issue que los construiría.
- Informa de vulnerabilidades y ejecuta la lista de endurecimiento desde
  [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md);
  lee [Protección de datos](data-protection.md) y [Licencias](licenses.md) junto a
  esta página.
