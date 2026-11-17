---
source_sha: "ce72ae8886cc"
---

# Integraciones incorporadas { #built-in-integrations }

Las cuentas personales se conectan en **Controles del chat → Preferencias → Tus cuentas** en `/chat`, o **Configuración → Perfil → Tus cuentas conectadas**. Las cuentas de la organización se conectan en **Vault → Conectar cuenta**. Se admiten varias cuentas del mismo proveedor. Cada producto de Google, Microsoft y Slack es una capability independiente en la **Toolbox**. Las integraciones usan las API directamente; no requieren servidores MCP del proveedor, Google Workspace MCP Preview ni licencia de Microsoft Copilot.


## Continuar con AgenticOS { #continue-with-agenticos }

La opción compartida **Continuar con AgenticOS** está oculta de forma predeterminada. Solicite acceso a **dev@vstorm.co** indicando su organización, la URL pública exacta de AgenticOS, los proveedores deseados y un contacto para incidentes. Vstorm revisa cada solicitud individualmente; el acceso no es automático. Tras la aprobación, configure en el backend `OAUTH_BRIDGE_URL=https://bridge-agenticos.testapp.ovh` y el `OAUTH_BRIDGE_ACCESS_KEY` recibido. Guarde la clave solo en la configuración secreta del servidor, nunca en variables del frontend, especificaciones de agentes ni el repositorio. La opción aparece únicamente cuando se aceptan la clave, el destino y el proveedor. **Usar credenciales propias** sigue disponible sin aprobación de Vstorm ni clave del bridge.

Solo el intercambio de códigos OAuth y la renovación pasan por el bridge. Los tokens se cifran en el Vault de esta instancia, vinculado a su propietario; los datos de trabajo van directamente a Google, Microsoft o Slack. El bridge mantiene credenciales de aplicación y una clave de cifrado en la configuración del servidor, sin base de datos de tokens de usuarios. Sus tickets cifrados y temporales requieren PKCE; renovar requiere un comprobante vinculado al token y la aplicación OAuth. Se debe confiar en el operador porque los tokens existen temporalmente en la memoria del proceso. Siguen vigentes la verificación del proveedor, las reglas de distribución y el consentimiento del tenant.

El bridge admite capabilities nativas y cuentas personales o de organización, incluso varias simultáneamente. Los montajes Mirage que necesitan el secreto de la aplicación OAuth siguen usando credenciales propias. Reconectar conserva la fuente original. Cambiar el origen del broker exige reconectar; nunca se envían tokens a otro broker.

El operador gestiona el acceso exclusivamente mediante CLI. Cada clave está vinculada a un origen exacto, proveedores aprobados y una fecha de caducidad; se guardan hashes y metadatos de acceso/contacto, no tokens de usuarios.

Revocarla bloquea los siguientes inicios, callbacks, intercambios y renovaciones, pero no retira tokens ya emitidos por el proveedor ni detiene una operación en curso. Ante una posible intrusión, revoque también la autorización en el proveedor. Una clave de sustitución requiere volver a conectar las cuentas gestionadas. Los operadores de bridges propios emiten sus claves. Antes de conectar, lea la política de privacidad y las condiciones del bridge y de su instancia; el bridge es una parte de confianza porque procesa tokens en memoria.


## Configurar una cuenta { #set-up-an-account }

Al usar credenciales propias, primero un administrador abre **Vault → Integraciones**, registra la aplicación del proveedor y guarda un único cliente OAuth visible para la organización. Este paso muestra callback, consola y permisos. «Cliente OAuth guardado» solo confirma la configuración almacenada; el proveedor puede exigir consentimiento o aprobación. La ausencia o duplicación de clientes bloquea el inicio de sesión e indica que debe intervenir un administrador. Después, los miembros eligen aplicaciones e inician sesión desde el chat o su perfil, sin configurar la consola del proveedor. La lectura es el valor predeterminado; la escritura requiere una elección explícita.

En **Conectar cuenta**, elija un servicio concreto, como Gmail, Google Calendar, Outlook mail o Excel. Los servicios de Google y Microsoft tienen entradas y logotipos independientes. El formulario selecciona solo ese servicio; puede añadir otros antes de iniciar sesión. Elegir un servicio no concede acceso hasta que acepte el consentimiento del proveedor.

Google: cree un proyecto Cloud, active las API indicadas (el asistente proporciona `gcloud services enable`), configure el consentimiento y un cliente OAuth **Web application**. Copie el callback exactamente y guarde `google_oauth_app`. Internal corresponde a la organización Workspace propietaria del proyecto. En External/Testing, los refresh tokens pueden caducar a los siete días. El acceso normal no necesita un cliente AI-powered-agent ni las API MCP alojadas.

Microsoft: registre una app Entra, elija tipos de cuenta y tenant, añada una redirección Web y los permisos delegados Graph indicados, y guarde `microsoft_oauth_app`. Las cuentas personales y empresariales funcionan donde el producto Graph las admite; Teams requiere cuenta empresarial. La política del tenant puede exigir consentimiento del administrador.

Slack: el botón de consola abre un manifiesto con el callback y los permisos de usuario admitidos. Revise los permisos antes de registrar la app; cada cuenta sigue solicitando solo el acceso de lectura o escritura elegido. Guarde `slack_oauth_app`. Puede reutilizar una app de bot añadiendo el callback y los permisos de usuario. Siguen vigentes los límites de apps y la aprobación del administrador. **Agents → MCP Server** solo es necesario para el MCP alojado de Slack.

## Alternativas a OAuth { #alternatives-to-oauth }

Elegir la identidad de una cuenta de aplicación requiere permiso de edición de su credencial en Vault, también para cuentas personales. Ver una credencial compartida no autoriza la suplantación. Las cuentas personales comprueban ese permiso antes de cada intercambio de tokens.

Google admite `gcp_service_account` de Vault con un subject para delegación de dominio Workspace. El administrador Workspace debe autorizar los scopes mostrados. Una cuenta de servicio normal solo accede a recursos compartidos con ella; no se convierte en una cuenta Gmail personal.

Microsoft admite un secreto de cliente `entra_app` y permisos de aplicación con consentimiento administrativo. Configure el buzón para correo/calendario y el ID de objeto de directorio del usuario para Teams: permite reconocer menciones sin acceso a todo el directorio. Excel exige OAuth delegado. Los permisos de aplicación no permiten publicar mensajes normales de Teams; use OAuth delegado. El asistente muestra los permisos correspondientes al método.

Las cuentas de aplicación Microsoft guardan solo los roles Graph devueltos por el tenant para los productos seleccionados. El modo de solo lectura también bloquea escrituras localmente aunque Entra haya concedido un rol más amplio. Cada renovación comprueba que los roles guardados sigan concedidos; vuelva a conectar tras cambiar el consentimiento.

Esta configuración necesita un claim de roles Graph legible en el token devuelto por el endpoint fijo de Microsoft. Los tokens de aplicación opacos o cifrados se rechazan indicando OAuth delegado como alternativa; AgenticOS no solicita permisos de todo el directorio para inspeccionar el consentimiento. El claim es metadato de configuración, no autenticación de un usuario de la plataforma; Microsoft Graph valida el token bearer.

Slack acepta tokens existentes de usuario `xoxp-` o de bot `xoxb-`. Un bot publica como app, pero no puede usar búsqueda exclusiva de usuarios. Se comprueban los scopes realmente concedidos antes de cada operación. Tokens y claves quedan cifrados en Vault, nunca en la especificación del agente.

Antes de guardar un trigger, watch o fuente de conocimiento Slack, AgenticOS comprueba el acceso al historial de cada conversación seleccionada. Verifica el permiso correspondiente a canales públicos/privados o mensajes directos/grupales y la pertenencia, sin solicitar permisos adicionales de directorio. Las conversaciones inaccesibles se rechazan durante la configuración.

**IMAP** es una conexión de correo separada y de solo lectura: host, puerto con TLS verificado, usuario, contraseña de app y carpeta fija. El operador debe permitir el host exacto en `MIRAGE_ALLOWED_HOSTS`. Se reutiliza el cliente Mirage instalado. IMAP con autenticación básica de Microsoft 365 no se ofrece como alternativa a OAuth.

## Qué puede hacer un agente { #choose-what-an-agent-can-do }

Google: Gmail (búsqueda, lectura, etiquetas, borradores/envío), Calendar (eventos y disponibilidad), Drive (búsqueda, metadatos, lectura, subida y copia), Docs, Sheets y Slides (lectura/creación/edición). Sheets incluye rangos, añadir filas y actualizar celdas.

Microsoft: correo Outlook, Calendar, archivos OneDrive/SharePoint, Excel, documentos Word y chats/canales Teams. Slack ofrece búsqueda, mis menciones, historial/hilos, canales/usuarios, consultas, publicaciones/respuestas, DM y reacciones. IMAP busca y lee sin marcar mensajes como leídos.

Los lectores conectados de Drive, SharePoint y Slack vuelven a obtener el token de la cuenta autorizada antes de cada petición al proveedor. Una sincronización larga puede renovar OAuth sin guardar secretos de renovación en la configuración del conector. Revocar el permiso de la cuenta de entrada también detiene el sondeo de triggers nativos antes de abrir el token. Los triggers de archivos Microsoft reconocen cambios propios de cuentas de aplicación por el usuario configurado y el ID de aplicación; el filtro predeterminado los omite.

Seleccione **personal** para usar las cuentas propias de la persona actual. Deje el nombre vacío para disponer de sus cuentas durante la ejecución, o indique un nombre, etiqueta o dirección exactos para limitar la capability a una cuenta coincidente. Las herramientas personales requieren conversación privada y pertenencia actual a la organización. El agente nunca toma la cuenta de otro miembro ni la de su autor.

Seleccione **organization** y las cuentas permitidas para el agente. Las especificaciones existentes con una `connection_id` siguen siendo válidas; `connection_ids` permite varias cuentas. La publicación comprueba cada cuenta y las operaciones activadas. Cada operación vuelve a comprobar el acceso actual del autor de la configuración.

El modelo recibe nombres y etiquetas antes de responder. Selecciona la cuenta mediante el argumento `account_name` y puede usar varias cuentas en una petición. Si la petición no identifica la cuenta, pregunta antes de acceder a los datos. Cuando falta acceso, explica el problema e indica la configuración del chat o Vault. Las operaciones de workflow también aceptan `account_name` en su entrada cuando hay varias cuentas configuradas. Añadir o volver a autorizar una cuenta exige revisar las fuentes de la rutina antes de que pueda usarla.

Toda escritura en ejecuciones de agentes requiere aprobación humana, incluso con una configuración individual más permisiva. Las herramientas desactivadas desaparecen. Los workflows usan las mismas operaciones como `integration.<product>.<operation>` y las mismas comprobaciones de cuenta y transporte. No se reintentan escrituras automáticamente; ponga un nodo de aprobación antes de las que deban revisarse en un workflow.

Los nodos de archivo reciben base64, nunca rutas locales del servidor. Word crea `.docx` desde título y párrafos. Subidas/descargas tienen límite de 20 MB, JSON de 2 MB y texto extraído de 100 000 caracteres. Una escritura fallida puede haber llegado: compruebe el resultado remoto antes de repetirla.

La opción de solo lectura limita localmente las cuentas OAuth, de aplicación y con token Slack pegado. Los permisos de escritura previos del proveedor no evitan ese límite, incluido el consentimiento incremental de Google. Para cambiarlo, vuelva a conectar la cuenta y active explícitamente la escritura.

La publicación de un vínculo con una cuenta de organización comprueba los permisos de cada herramienta habilitada. Si la cuenta solo permite lectura, desactive las herramientas de escritura antes de publicar o vuelva a conectar con permisos de escritura.

## Conocimiento, triggers y watches { #knowledge-triggers-and-watches }

Las fuentes Drive y SharePoint seleccionan la misma conexión de organización en vez de credenciales separadas. OneDrive usa el conector SharePoint con unidad/carpeta elegida. Slack indexa solo canales elegidos y sus hilos. Cada sincronización revalida la autorización; una fuente compartida no utiliza cuentas privadas de miembros.

Los triggers reutilizan la cola transaccional, deduplicación y política de fuentes aprobadas existentes. Filtros Gmail/Outlook, anticipación de eventos y cambios de archivos funcionan con cuentas nativas. Slack añade mensajes, menciones y DM; Teams mensajes/menciones; IMAP correo nuevo. Sheets sigue **filas añadidas al final** de una hoja elegida. La base es la última fila ocupada en las columnas A:ZZ; insertar/eliminar filas y editar filas existentes no son eventos de adición.

Una watch elige una conexión personal y producto, y recibe solo una herramienta fija de cambios de lectura. Active el producto en el agente primero. Elija conversaciones Slack y chats Teams delegados en la capability. Los canales Teams usan `channel/team-id/channel-id`; app-only sin conversaciones lee todos los chats del usuario configurado.

Cada watch mantiene un cursor persistente independiente que avanza tras consumir correctamente la revisión. Los cursores nuevos/restablecidos crean una base silenciosa. Gmail usa history IDs, Outlook/calendarios cursores del proveedor, Slack timestamps por conversación e IMAP UIDVALIDITY/UID. Teams delegado usa `lastModifiedDateTime`; canales y aplicación usan Graph delta. Si una lectura acotada informa demasiados cambios, reduzca la fuente.

Vuelva a conectar desde la fila de la cuenta afectada para sustituir las credenciales en el mismo registro. Se conservan el ID y el nombre estable para las referencias de agentes, fuentes y triggers; cambia la generación de autorización y las rutinas existentes necesitan revisar sus fuentes. Use el mismo método de autenticación. Los errores de sondeo aparecen en la cuenta y se borran tras una lectura correcta. Una hoja inaccesible conserva su cursor mientras las hojas sanas continúan. Los feeds Slack excluyen mensajes enviados por el usuario o bot conectado para evitar bucles de respuestas.

Consulte [capabilities](reference/capabilities.md), [triggers](triggers.md), [gobernanza y watches](governance.md#proactive-work) y [MCP](mcp.md).

Asigne una etiqueta como Trabajo al conectar; use la misma etiqueta para la cuenta correspondiente de cada persona.

Los triggers nativos creados mediante API requieren `connection_id`. Las modificaciones de filtros vuelven a comprobar la cuenta, permisos y conversaciones seleccionadas. Cada selección distinta de conversaciones Slack/Teams conserva su propio cursor y solo alimenta sus triggers asociados; una selección admite hasta 20 conversaciones.

## Conexión sin navegador { #connect-without-a-browser }

IMAP y Odoo se pueden conectar mediante la API HTTP. Copie la [plantilla IMAP](assets/setup/imap-account.example.json) u [Odoo](assets/setup/odoo-account.example.json) y la [plantilla de autenticación curl](assets/setup/agenticos-auth.example.conf) fuera del repositorio. Sustituya todos los ejemplos por la cuenta de prueba autorizada y un [token de acceso AgenticOS](api.md). Restrinja ambos archivos al operador (`chmod 600 account.json auth.conf`); nunca guarde credenciales reales en git. Las plantillas no contienen credenciales válidas.

Añada el host IMAP exacto a `MIRAGE_ALLOWED_HOSTS` o el host Odoo a `ODOO_ALLOWED_HOSTS` del backend, conservando las entradas existentes. IMAP utiliza TLS verificado; Odoo requiere HTTPS y JSON-2 de la versión 19 o posterior. Envíe la solicitud a su despliegue AgenticOS:

```bash
curl --fail-with-body --config auth.conf --json @account.json \
  https://agenticos.example.com/api/v1/me/connected-accounts/imap
```

Para Odoo, cambie el final de la ruta a `/odoo`; la plantilla mantiene desactivada la escritura. Las cuentas de organización usan `/api/v1/connected-accounts/imap` u `/odoo`; el usuario necesita `mcp:manage`. Una respuesta correcta devuelve el ID de conexión, no las credenciales. Para reconectar, añada `connection_id`. Corrija cualquier host rechazado o credencial inválida antes de usar la cuenta. Las plantillas y pruebas locales no acreditan una conexión real con el proveedor.

### Configurar rutinas desde el terminal { #configure-polled-routines-from-the-terminal }

Para una cuenta ya conectada, `integration-trigger-setup --list` muestra las plantillas nativas de sondeo del catálogo sin acceder a la red. `--accounts` lee los identificadores de cuentas accesibles, su propietario y el estado de reconexión o de errores de sondeo desde la propia instancia; no contacta con Google, Microsoft ni otro proveedor. La lista corresponde al origen seleccionado; puede omitir cuentas no disponibles o sin los permisos necesarios. Introduzca el token personal de acceso de AgenticOS en el campo oculto o mediante `--access-token-file`. La lista requiere `agents:view`; la API existente comprueba el acceso al agente y a la cuenta al crear la rutina.

```bash
uv run agenticos cmd integration-trigger-setup --list
uv run agenticos cmd integration-trigger-setup --accounts --portal google \
  --base-url https://agenticos.example.com --org ORGANIZATION_UUID
uv run agenticos cmd integration-trigger-setup \
  --portal google --preset inbox_only --agent AGENT_UUID \
  --connection CONNECTION_UUID --prompt-file prompt.txt
```

El último comando solo muestra localmente una solicitud JSON con las instrucciones; no crea ni ejecuta una rutina. Sustituya los UUID y proporcione un archivo de instrucciones UTF-8. La opción `--filter-file filters.json` admite un objeto JSON con filtros que sustituyen valores de la plantilla. Sin conexión se valida la estructura, no la disponibilidad de la cuenta ni la semántica de filtros del origen. Sheets requiere indicar la hoja; Slack y Teams necesitan seleccionar conversaciones cuando corresponda. El servidor valida esos campos al crear la rutina.

Añada `--apply --base-url https://agenticos.example.com --org ORGANIZATION_UUID` para crearla **pausada**, con revisión de fuentes obligatoria antes de activarla. Se realiza una sola solicitud autenticada, sin reintentos automáticos ni ejecución del agente. Si el resultado es incierto, revise las rutinas existentes antes de repetirla. El sondeo usa los workers y cursores persistentes existentes. El comando no crea temas Pub/Sub, webhooks del proveedor ni suscripciones push que caduquen, y no cambia la frecuencia de sondeo. Una conexión OAuth pendiente sigue necesitando el consentimiento del titular.

## Odoo { #odoo }

Conecte Odoo 19+ mediante JSON-2 con el origen HTTPS, la base de datos y la clave API de un usuario de negocio. El operador debe autorizar el host exacto en `ODOO_ALLOWED_HOSTS`; se rechazan rutas, redirecciones y puertos personalizados. Odoo Online requiere un plan Custom para APIs externas. Instale los módulos necesarios y limite los permisos y reglas de registros del usuario. Las claves caducan: rótelas y vuelva a conectar. La escritura es opcional y cada escritura del agente requiere aprobación.

Las capabilities cubren contactos, CRM, ventas, facturas, inventario y proyectos. Ofrecen metadatos de campos, búsqueda/lectura limitada y herramientas separadas para crear/editar donde se admite. Las existencias son de solo lectura; las operaciones de inventario usan transferencias y movimientos. Herramientas y nodos de workflow comparten cuenta y adaptador JSON-2. No se permiten modelos, métodos ni contexto arbitrarios.

Watches y triggers leen registros nuevos/modificados del área seleccionada. Cada modelo tiene su cursor `(write_date, id)`; la primera lectura establece una base silenciosa. Las siguientes consumen hasta 100 registros por modelo y conservan el resto. Las eliminaciones no son eventos. Los timestamps Odoo tienen precisión de segundos; cambios del mismo registro dentro de un segundo pueden agruparse. La sincronización de conocimiento indexa solo los campos seleccionados mediante una cuenta de organización; listas limitadas nunca eliminan documentos no vistos.

La confirmación de ventas, contabilización de facturas y confirmación/reserva/validación de transferencias tienen herramientas con aprobación. Use estas acciones en vez de escribir el estado. Pueden devolver un asistente que debe completarse en Odoo; lea el registro antes de comunicar éxito. Las facturas requieren `move_type` explícito (cliente, proveedor, abono o recibo). Se admiten campos escalares y vincular/reemplazar/vaciar IDs de relaciones. Cree o edite los registros relacionados con sus propias herramientas; se rechazan mutaciones ORM anidadas y valores de objetos JSON.

El cursor Odoo también conserva una instantánea deduplicada de su límite temporal para releer cambios posteriores de registros con un ID menor. Las huellas incluyen el ID, nombre mostrado y fecha de escritura devueltos. Cada instantánea admite hasta 2000 registros por modelo y marca temporal; divida operaciones masivas si se supera el límite.

## Exchange Online { #exchange-online }

Outlook mail y Outlook Calendar conectan Microsoft Exchange Online mediante Microsoft Graph. Use el asistente Microsoft con OAuth delegado o una cuenta de aplicación Entra con permisos aprobados por el administrador y el buzón objetivo. No necesita contraseña IMAP separada ni licencia Work IQ. Esta vía cubre Exchange Online; no añade Exchange local ni EWS.
