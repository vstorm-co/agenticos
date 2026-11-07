---
source_sha: "3e8d1a15aa54"
---

# Integraciones incorporadas { #built-in-integrations }

Conecte una cuenta en **Configuración → Vault → Cuentas conectadas**. Cada producto de Google, Microsoft y Slack es una capability independiente en la **Toolbox** del agente, con selección de cuenta y controles por herramienta. Usan las API directamente: no requieren servidores MCP del proveedor, Google Workspace MCP Preview ni licencia de Microsoft Copilot.

## Configurar una cuenta { #set-up-an-account }

El asistente muestra la URL de callback exacta de la instalación, el enlace a la consola y los permisos solicitados. Seleccione productos primero. La lectura es el valor predeterminado; active escritura expresamente. Un administrador guarda una app OAuth visible para la organización en Vault; los miembros la reutilizan al conectar cuentas personales. Si existen varias credenciales de app, el administrador debe resolver cuál usa la instalación.

Google: cree un proyecto Cloud, active las API indicadas (el asistente proporciona `gcloud services enable`), configure el consentimiento y un cliente OAuth **Web application**. Copie el callback exactamente y guarde `google_oauth_app`. Internal corresponde a la organización Workspace propietaria del proyecto. En External/Testing, los refresh tokens pueden caducar a los siete días. El acceso normal no necesita un cliente AI-powered-agent ni las API MCP alojadas.

Microsoft: registre una app Entra, elija tipos de cuenta y tenant, añada una redirección Web y los permisos delegados Graph indicados, y guarde `microsoft_oauth_app`. Las cuentas personales y empresariales funcionan donde el producto Graph las admite; Teams requiere cuenta empresarial. La política del tenant puede exigir consentimiento del administrador.

Slack: **Crear la app de Slack** abre un manifiesto con el callback y permisos de lectura de usuario. Añada permisos de escritura antes de escribir y reinstale/autorice. Guarde `slack_oauth_app` y complete el consentimiento. Puede reutilizar la app del bot de canales añadiendo el callback y permisos de usuario. Siguen vigentes los límites de apps del workspace y la aprobación del administrador. **Agents → MCP Server** solo es necesario al usar por separado el MCP alojado de Slack.

## Alternativas a OAuth { #alternatives-to-oauth }

Elegir la identidad de una cuenta de aplicación requiere permiso de edición de su credencial en Vault, también para cuentas personales. Ver una credencial compartida no autoriza la suplantación. Las cuentas personales comprueban ese permiso antes de cada intercambio de tokens.

Google admite `gcp_service_account` de Vault con un subject para delegación de dominio Workspace. El administrador Workspace debe autorizar los scopes mostrados. Una cuenta de servicio normal solo accede a recursos compartidos con ella; no se convierte en una cuenta Gmail personal.

Microsoft admite un secreto de cliente `entra_app` y permisos de aplicación con consentimiento administrativo. Configure el buzón para correo/calendario y el ID de objeto de directorio del usuario para Teams: permite reconocer menciones sin acceso a todo el directorio. Excel exige OAuth delegado. Los permisos de aplicación no permiten publicar mensajes normales de Teams; use OAuth delegado. El asistente muestra los permisos correspondientes al método.

Las cuentas de aplicación Microsoft guardan solo los roles Graph devueltos por el tenant para los productos seleccionados. El modo de solo lectura también bloquea escrituras localmente aunque Entra haya concedido un rol más amplio. Cada renovación comprueba que los roles guardados sigan concedidos; vuelva a conectar tras cambiar el consentimiento.

Esta configuración necesita un claim de roles Graph legible en el token devuelto por el endpoint fijo de Microsoft. Los tokens de aplicación opacos o cifrados se rechazan indicando OAuth delegado como alternativa; AgenticOS no solicita permisos de todo el directorio para inspeccionar el consentimiento. El claim es metadato de configuración, no autenticación de un usuario de la plataforma; Microsoft Graph valida el token bearer.

Slack acepta tokens existentes de usuario `xoxp-` o de bot `xoxb-`. Un bot publica como app, pero no puede usar búsqueda exclusiva de usuarios. Se comprueban los scopes realmente concedidos antes de cada operación. Tokens y claves quedan cifrados en Vault, nunca en la especificación del agente.

**IMAP** es una conexión de correo separada y de solo lectura: host, puerto con TLS verificado, usuario, contraseña de app y carpeta fija. El operador debe permitir el host exacto en `MIRAGE_ALLOWED_HOSTS`. Se reutiliza el cliente Mirage instalado. IMAP con autenticación básica de Microsoft 365 no se ofrece como alternativa a OAuth.

## Qué puede hacer un agente { #choose-what-an-agent-can-do }

Google: Gmail (búsqueda, lectura, etiquetas, borradores/envío), Calendar (eventos y disponibilidad), Drive (búsqueda, metadatos, lectura, subida y copia), Docs, Sheets y Slides (lectura/creación/edición). Sheets incluye rangos, añadir filas y actualizar celdas.

Microsoft: correo Outlook, Calendar, archivos OneDrive/SharePoint, Excel, documentos Word y chats/canales Teams. Slack ofrece búsqueda, mis menciones, historial/hilos, canales/usuarios, consultas, publicaciones/respuestas, DM y reacciones. IMAP busca y lee sin marcar mensajes como leídos.

Seleccione **personal** para resolver la cuenta de la persona actual por nombre, etiqueta o dirección exactos. El nombre vacío solo funciona con una coincidencia. Las herramientas personales requieren conversación privada y pertenencia actual a la organización. Para automatizaciones compartidas use **organization** y el ID de conexión. Nunca se toma la cuenta de otro miembro.

Toda escritura en ejecuciones de agentes requiere aprobación humana, incluso con una configuración individual más permisiva. Las herramientas desactivadas desaparecen. Los workflows usan las mismas operaciones como `integration.<product>.<operation>` y las mismas comprobaciones de cuenta y transporte. No se reintentan escrituras automáticamente; ponga un nodo de aprobación antes de las que deban revisarse en un workflow.

Los nodos de archivo reciben base64, nunca rutas locales del servidor. Word crea `.docx` desde título y párrafos. Subidas/descargas tienen límite de 20 MB, JSON de 2 MB y texto extraído de 100 000 caracteres. Una escritura fallida puede haber llegado: compruebe el resultado remoto antes de repetirla.

La publicación de un vínculo con una cuenta de organización comprueba los permisos de cada herramienta habilitada. Si la cuenta solo permite lectura, desactive las herramientas de escritura antes de publicar o vuelva a conectar con permisos de escritura.

## Conocimiento, triggers y watches { #knowledge-triggers-and-watches }

Las fuentes Drive y SharePoint seleccionan la misma conexión de organización en vez de credenciales separadas. OneDrive usa el conector SharePoint con unidad/carpeta elegida. Slack indexa solo canales elegidos y sus hilos. Cada sincronización revalida la autorización; una fuente compartida no utiliza cuentas privadas de miembros.

Los triggers reutilizan la cola transaccional, deduplicación y política de fuentes aprobadas existentes. Filtros Gmail/Outlook, anticipación de eventos y cambios de archivos funcionan con cuentas nativas. Slack añade mensajes, menciones y DM; Teams mensajes/menciones; IMAP correo nuevo. Sheets sigue **filas añadidas al final** de una hoja elegida. La base es la última fila ocupada en las columnas A:ZZ; insertar/eliminar filas y editar filas existentes no son eventos de adición.

Una watch elige una conexión personal y producto, y recibe solo una herramienta fija de cambios de lectura. Active el producto en el agente primero. Elija conversaciones Slack y chats Teams delegados en la capability. Los canales Teams usan `channel/team-id/channel-id`; app-only sin conversaciones lee todos los chats del usuario configurado.

Cada watch mantiene un cursor persistente independiente que avanza tras consumir correctamente la revisión. Los cursores nuevos/restablecidos crean una base silenciosa. Gmail usa history IDs, Outlook/calendarios cursores del proveedor, Slack timestamps por conversación e IMAP UIDVALIDITY/UID. Teams delegado usa `lastModifiedDateTime`; canales y aplicación usan Graph delta. Si una lectura acotada informa demasiados cambios, reduzca la fuente.

Consulte [capabilities](reference/capabilities.md), [triggers](triggers.md), [gobernanza y watches](governance.md#proactive-work) y [MCP](mcp.md).

Asigne una etiqueta como Trabajo al conectar; use la misma etiqueta para la cuenta correspondiente de cada persona.

Los triggers nativos creados mediante API requieren `connection_id`. Las modificaciones de filtros vuelven a comprobar la cuenta, permisos y conversaciones seleccionadas. Cada selección distinta de conversaciones Slack/Teams conserva su propio cursor y solo alimenta sus triggers asociados; una selección admite hasta 20 conversaciones.

## Odoo { #odoo }

Conecte Odoo 19+ mediante JSON-2 con el origen HTTPS, la base de datos y la clave API de un usuario de negocio. El operador debe autorizar el host exacto en `ODOO_ALLOWED_HOSTS`; se rechazan rutas, redirecciones y puertos personalizados. Odoo Online requiere un plan Custom para APIs externas. Instale los módulos necesarios y limite los permisos y reglas de registros del usuario. Las claves caducan: rótelas y vuelva a conectar. La escritura es opcional y cada escritura del agente requiere aprobación.

Las capabilities cubren contactos, CRM, ventas, facturas, inventario y proyectos. Ofrecen metadatos de campos, búsqueda/lectura limitada y herramientas separadas para crear/editar donde se admite. Las existencias son de solo lectura; las operaciones de inventario usan transferencias y movimientos. Herramientas y nodos de workflow comparten cuenta y adaptador JSON-2. No se permiten modelos, métodos ni contexto arbitrarios.

Watches y triggers leen registros nuevos/modificados del área seleccionada. Cada modelo tiene su cursor `(write_date, id)`; la primera lectura establece una base silenciosa. Las siguientes consumen hasta 100 registros por modelo y conservan el resto. Las eliminaciones no son eventos. Los timestamps Odoo tienen precisión de segundos; cambios del mismo registro dentro de un segundo pueden agruparse. La sincronización de conocimiento indexa solo los campos seleccionados mediante una cuenta de organización; listas limitadas nunca eliminan documentos no vistos.

La confirmación de ventas, contabilización de facturas y confirmación/reserva/validación de transferencias tienen herramientas con aprobación. Use estas acciones en vez de escribir el estado. Pueden devolver un asistente que debe completarse en Odoo; lea el registro antes de comunicar éxito. Las facturas requieren `move_type` explícito (cliente, proveedor, abono o recibo). Se admiten campos escalares y vincular/reemplazar/vaciar IDs de relaciones. Cree o edite los registros relacionados con sus propias herramientas; se rechazan mutaciones ORM anidadas y valores de objetos JSON.

El cursor Odoo también conserva una instantánea deduplicada de su límite temporal para releer cambios posteriores de registros con un ID menor. Las huellas incluyen el ID, nombre mostrado y fecha de escritura devueltos. Cada instantánea admite hasta 2000 registros por modelo y marca temporal; divida operaciones masivas si se supera el límite.

## Exchange Online { #exchange-online }

Outlook mail y Outlook Calendar conectan Microsoft Exchange Online mediante Microsoft Graph. Use el asistente Microsoft con OAuth delegado o una cuenta de aplicación Entra con permisos aprobados por el administrador y el buzón objetivo. No necesita contraseña IMAP separada ni licencia Work IQ. Esta vía cubre Exchange Online; no añade Exchange local ni EWS.
