---
source_sha: "1b6fafac402e"
---

# La consola { #the-console }

El dashboard personal lee onboarding y Briefing juntos antes de mostrar su primera fila. Una zona de carga reservada evita cambios entre diseños de marcadores; los demás widgets cargan por separado. Los errores de lectura permiten reintentar. La ampliación del área de trabajo se ofrece en teléfonos; al pasar al escritorio se recupera la navegación y se conservan los campos sin guardar.

Los ajustes de contexto muestran filas compactas con controles de uso por agente. Las descripciones largas ya no estiran los archivos vecinos y el contexto solo inyectado muestra una nota informativa. Availability incluye el logotipo de la plataforma junto al nombre del bot. Al compartir una app aparecen primero el enlace de la página y las personas con acceso; caducidad, versión fija, inserción y contraseña empiezan cerradas en los ajustes del enlace. Las restricciones activas siguen visibles como etiquetas y cerrar las opciones conserva las ediciones.

En teléfonos, el registro de canales usa un selector compacto de plataforma. Cancelar un canal nuevo, una clave nueva de la bóveda o una rotación borra las credenciales introducidas. Los formularios de canales y bóveda bloquean la edición y el cierre durante la escritura; un rechazo conserva los valores para corregirlos y reintentar. La edición de canales y la rotación mantienen sus acciones visibles también en ventanas bajas.

En teléfonos, los archivos de contexto nuevos muestran el editor antes de los detalles opcionales. Details indica el acceso efectivo incluso cerrado; ábrelo para cambiar la descripción o el acceso. Un error en la descripción abre automáticamente la sección para poder corregirlo.

Los formularios de nuevos proyectos, archivos de contexto y datasets preguntan antes de descartar un borrador. Stay lo conserva y Discard lo restablece. Durante la creación se bloquean campos, Cancel, Close y Escape hasta terminar la escritura. Un rechazo conserva los valores y permite volver a editarlos. El código fuente de contexto queda de solo lectura durante la escritura.

Al soltar varios archivos de contexto, cerrar ofrece solo Stay o Discard; usa Create para procesarlos en orden. Los detalles del dataset y los formularios de casos también bloquean campos y cierre al guardar, incluido el cambio formulario/JSON. Guardar sigue accesible en ventanas cortas de teléfono.

Al iniciar sesión MCP, el formulario permanece abierto hasta obtener el destino de consentimiento. Un inicio rechazado conserva los datos para corregirlos y reintentar.

La edición de comandos slash propios pregunta antes de descartar un borrador. Al guardar se bloquean los campos y el cierre hasta recibir respuesta; un rechazo conserva los datos. En teléfonos, las acciones tienen una fila propia y controles táctiles. Un cambio de estado pendiente bloquea acciones incompatibles y la eliminación pide confirmación. Los formularios MCP también bloquean campos y cierre al guardar.

La consola es la aplicación web desde la que se configura todo lo demás de este
sitio. Esta página es el mapa: para qué sirve cada área, y qué página la explica
como es debido.

Al editar los ajustes de un proyecto, el nombre de una organización, el límite de gasto, los valores de voz predeterminados, los periodos de retención, un skill o un archivo de contexto, antes de salir eliges guardar, descartar o quedarte. También se pregunta al cambiar desde un recurso de skill editado a otro archivo. Si se rechaza el guardado, el borrador permanece abierto; **Save file** lo descarta solo cuando el servidor confirma la escritura. El texto añadido mientras se guarda ese recurso sigue sin guardar.

En el teléfono, los documentos de las bases de conocimiento y los miembros de la organización aparecen en filas etiquetadas con acciones visibles. Eliminar un miembro requiere confirmación y un rechazo mantiene el diálogo abierto. Los formularios de creación de KB, procesamiento y proveedor de embeddings bloquean los campos y permanecen abiertos mientras guardan; tras un rechazo pueden editarse y cerrarse de nuevo. Una descarga fallida muestra un error y permite reintentar.

Cambiar la pregunta o el ámbito de la búsqueda de conocimiento borra los resultados anteriores y cancela la solicitud pendiente. Una respuesta tardía no puede reemplazar los resultados de una búsqueda más reciente.

El chat público permite escribir mientras se conecta, pero habilita Send solo cuando se abre el WebSocket actual. Una conversación nueva espera a su propia conexión; un clic anticipado no puede perder la primera pregunta sin indicarlo.

Si buscas una pantalla concreta, el camino más rápido es el **"?"** de la
cabecera de cada página — reproduce el recorrido guiado de esa página, y una
página cuya cabecera no lleva "?" no tiene recorrido que reproducir. El chat no
tiene cabecera: sus consejos están en los ajustes del chat, los deslizadores junto
al micrófono.

Las listas de recursos, incluidas Inbox y Routines, ocupan la altura restante de la página incluso cuando están vacías. Las plantillas de Routines siguen en el formulario de creación, sin un panel de ideas aparte.

El chat usa retratos de agentes más grandes y sin marcos. El control Files permanece en el cuadro de mensaje al abrir y cerrar el panel; la animación respeta la preferencia de movimiento reducido. Los ajustes del chat muestran primero el modelo actual. **Change model** abre el formulario del proveedor y del modelo ya rellenados; el cambio solo se aplica al confirmarlo. Las tarjetas de adjuntos aparecen sobre el cuadro de mensaje sin otro panel con sombra.

Las introducciones de páginas y explicaciones de ajustes están en el icono de información junto al encabezado. Los resúmenes actuales y avisos de acciones destructivas siguen visibles.

En Agentes, Skills, Context y el historial, **Filtros** despliega opciones adicionales en cualquier tamaño de pantalla e indica cuántos filtros están activos.

Las tarjetas de agentes muestran directamente estado, acceso y fecha de edición. Las tarjetas de Skills y Context mantienen visibles la vista previa, el resumen, **Used by** con retratos y **Add to an agent**. Categoría y audiencia están en una fila compacta junto a la acción. No hay un desplegable Detalles. Para borrar un skill o archivo de contexto, abre su editor y el menú de tres puntos junto a **Share**; se sigue pidiendo confirmación y solo quien puede editar tiene acceso a esta acción.

Los nombres, la navegación y los valores de formularios usan texto destacado; los
metadatos siguen en segundo plano. Las acciones principales tienen un relleno neutro
de alto contraste. Glass conserva el material nativo, pero el contenido, las tarjetas
y los menús usan superficies más opacas para leer.

Las pestañas de organización, agentes y proyectos tienen iconos. Las filas de
presupuesto muestran retratos de agentes.

Los retratos generados usan formas seleccionadas de Blobatar 2.7 y tonos más claros; las caras inactivas se animan al pasar el cursor y los agentes trabajando mantienen su animación. Las imágenes subidas se conservan. Los nuevos agentes iniciales usan la misma familia visual; las imágenes almacenadas existentes no se sustituyen automáticamente.

Los ajustes del chat muestran Browser y Work on antes de Permissions. Las
notificaciones de la conversación y las conexiones de cuentas quedan debajo de los
permisos.

Los ajustes del chat tienen un encabezado fijo y un botón de cierre sobre el contenido desplazable. Los iconos de información explican el modelo, Browser, Work on y los modos de permisos cuando se solicitan; la explicación del modo seleccionado permanece visible. En **Knowledge bases → Integrations**, los paneles compactos de integraciones y servicios locales se ajustan al contenido, con explicaciones en los iconos de información.

Los agentes de una conversación se ordenan por su último mensaje o ejecución principal, del más reciente al más antiguo. La barra de chat contraída mantiene los avatares a tamaño completo, superpone hasta tres y oculta a los participantes más antiguos; la lista completa sigue disponible en la ayuda emergente.

Cuando **Approve everything** no está disponible, los ajustes del chat distinguen entre la falta de permiso para decidir aprobaciones y una política de la organización que desactiva el consentimiento permanente. Quien puede decidir aprobaciones recibe un enlace a **Presupuesto y aprobaciones** para cambiar esa política expresamente. El chat nunca modifica la política de la organización automáticamente.

Los diálogos mantienen un margen de 12 px en todos los bordes del teléfono. Los encabezados compactos muestran título y acciones en una línea cuando caben. La descripción de Context se abre desde la barra del editor.

En el teléfono, las acciones principales siguen visibles y los comandos secundarios se despliegan con **Más acciones de la página**. Inbox y el formato de tabla usan selectores. Los ajustes con muchas secciones usan un menú; el cliente MCP se elige en una lista. Los archivos de proyecto o workspace se abren en un visor a pantalla completa; la flecha vuelve a las carpetas. El editor de pasos del workflow muestra un panel elegido: ajustes, entrada o salida. Cambiar de panel conserva las ediciones; en escritorio siguen uno al lado del otro.

Los campos Markdown y los editores de archivos también ofrecen un botón para ampliar sin descartar el borrador actual. La descripción y la categoría de un skill pueden desplegarse encima del editor. El cuadro del chat ocupa menos espacio y limita los borradores largos según la altura disponible. Al abrir la navegación, el foco se sitúa en el panel; Tab sigue permitiendo acceder a sus controles. En el teléfono, el lienzo del workflow ofrece un control flotante de pantalla completa y un minimapa más pequeño.

En teléfonos, los editores de skills y contexto mantienen plegadas la descripción, la categoría y la gestión de archivos mientras se escribe. Un botón alterna entre código y vista previa. Apps ofrece botones flotantes para volver y abrir opciones; estas muestran el título, la versión, el tema y los controles para compartir.

Los encabezados utilizan el espaciado del diseño que los rodea sin duplicarlo. Las tarjetas, las filas de la barra lateral, las pestañas y los estados vacíos tienen un espaciado más compacto en escritorio; los controles conservan áreas táctiles mayores.

Los botones secundarios y los filtros comparten un relleno más visible, etiquetas con contraste y estados claros al pasar el cursor, pulsar o abrir un menú. El selector de modelo del chat utiliza el mismo estilo.

Los ajustes personales mantienen pestañas horizontales en la parte superior, incluidas las páginas exclusivas de escritorio dentro de la aplicación. Los paneles muestran sus descripciones directamente y los formularios se ajustan al contenido. Cuenta reúne el cambio de contraseña y las sesiones activas; la acción de contraseña aparece debajo de los campos.

Los campos del perfil comparten fila cuando hay espacio; **Guardar cambios** solo está disponible tras editar. Cada tarjeta de capacidad tiene una zona para abrir los ajustes y un interruptor independiente para activarla. Los ejemplos aparecen detrás del icono de información en los ajustes, sin repetir la ilustración de la galería.

Los diálogos de categorías de plantillas se ajustan al contenido; elegir un sector de agentes o habilidades abre la biblioteca más amplia. En el teléfono, los estilos se muestran en filas compactas con miniaturas.

Las instrucciones de agentes y proyectos tienen una barra compacta con título, ayuda, código/vista previa y ampliación. El Markdown ampliado conserva el modo seleccionado. Las variables de prompt sin usar empiezan plegadas; las variables propias existentes o una zona horaria personalizada mantienen abierto el panel. Los editores ampliados de texto y archivos conservan márgenes uniformes en el teléfono. Los campos de texto usan allí una letra mayor sin ampliar los campos de escritorio.

En el teléfono, enfocar el mensaje activa una fila compacta de escritura con adjuntos y envío. La selección del agente y la entrada de voz siguen disponibles en **+**. La bienvenida y las sugerencias de conexiones se ocultan al escribir; los menús de autocompletado se ajustan a la altura disponible. El diseño permanece estable al pasar del texto a Enviar.

Cada acción explícita **New chat** vuelve a enfocar el editor, incluso desde un borrador vacío; recibir un identificador de conversación mientras se escribe no solicita el foco.

Al entrar en el chat principal, el campo recibe el foco en cuanto permite escribir, incluso si el botón de navegación lo conservaba durante la conexión. Un control utilizado deliberadamente mientras se conecta mantiene el foco.

En el teléfono, las acciones bajo los mensajes del usuario y del agente empiezan ocultas. El botón **Más** junto al remitente muestra u oculta copiar, responder, valorar y las demás acciones disponibles. En el escritorio, los controles siguen apareciendo al pasar el cursor.

Las importaciones CSS, imágenes y fuentes se resuelven respecto a su hoja de estilo mediante el mismo acceso autorizado. Las vistas previas permiten cuatro niveles anidados, 64 recursos, 8 MiB de entrada y 16 MiB de salida expandida. Los enlaces conservan su conversación o carpeta local original, registrada en la cronología del turno. Cambiar Work on no los redirige. Los turnos antiguos sin origen registrado no reciben enlaces inferidos. Abrir un archivo local sigue requiriendo su permiso nativo vigente.

Los metadatos de enlaces guardan solo un identificador opaco del origen para los turnos locales. La relación con la carpeta permanece en el equipo que inició el turno, limitada a su cuenta y organización; otros participantes y equipos no pueden resolver esos enlaces. Los orígenes antiguos con una ruta local se omiten al leer turnos guardados.

**Visual map** en el editor de agentes ajusta toda la configuración al abrirse y al cambiar el tamaño del área. **Reset view** vuelve a ajustarla tras desplazarla o ampliarla. Los grupos grandes muestran seis elementos y el número restante; selecciona un grupo para consultar la lista completa con desplazamiento. El minimapa de workflows muestra todo el grafo y permite cambiar de zona sin modificar el zoom.

El panel de pruebas del editor puede ocupar todo el espacio de trabajo sin reiniciar la conversación ni el texto sin enviar. Comparar dos versiones abre este espacio automáticamente; el botón de pantalla completa o Escape devuelve al editor. Los selectores de versión tienen su propia fila para mantener accesibles los controles en paneles estrechos. En el teléfono, los botones de versión alternan entre los chats comparados; ambas conversaciones siguen funcionando y conservan sus borradores. El prompt compartido sigue llegando a ambas a la vez.

La navegación conserva los layouts compartidos al cambiar de sección y usa una transición breve en lugar de reiniciar el marco. El movimiento reducido desactiva la transición. Las tarjetas del dashboard esperan la disposición guardada, las páginas con permisos esperan su lectura y la lista administrativa de usuarios comienza cargando, sin afirmar que está vacía. Los filtros de grupos y autores de Apps reservan espacio durante la carga. Las fuentes del Inbox esperan los metadatos del catálogo; los enlaces a conversaciones de trabajo usan la misma ruta que la barra lateral.

En el móvil, los mensajes enviados se detienen debajo de los botones flotantes del chat para mantener visible el avatar del usuario. El inicio de la conversación y el espacio reservado para la respuesta usan la misma separación; los chats de escritorio e integrados conservan un margen menor.

Los agentes predeterminados terminan una solicitud puntual sin mantener abierta la respuesta con una pregunta sobre automatización opcional. Las preguntas resuelven decisiones necesarias para la tarea actual o una automatización solicitada o aceptada. Las tarjetas opcionales de configuración siguen siendo propuestas que no bloquean la finalización.

El botón compacto bajo una respuesta abre Sources junto a la conversación y ocupa todo el ancho en el móvil. Files y Sources comparten el área lateral: abrir uno sustituye al otro. Las fuentes web muestran el favicon del sitio, solicitado sin Referer, o un logotipo conocido; aparece un globo si el icono no está disponible. Las fuentes de conocimiento conservan sus iconos de archivo y el visor del documento original.

Los enlaces web de las respuestas usan la misma política de favicon, sin depender de conexiones MCP. Los iconos de sitios desconocidos pasan por el proxy del mismo origen de la consola y el servicio fijo de iconos de DuckDuckGo. Este solo recibe el nombre de host, nunca las cookies o la dirección IP del lector, la ruta ni los parámetros de URL. El proxy rechaza redirecciones, contenido no rasterizado e iconos de más de 64 KiB; el tiempo límite es de tres segundos. Si falta el icono o no está disponible, aparece un globo. Las vistas inertes de transcripciones no cargan imágenes remotas ni iconos de sitios desconocidos.

Una ejecución fallida muestra el error separado de la respuesta y fuera de las herramientas plegadas, incluso después de recargar la conversación. El filtro de contenido del proveedor tiene una explicación explícita; las respuestas originales del proveedor y los errores históricos desconocidos no se copian a transcripciones compartidas. El trabajo parcial sigue disponible y no se presenta como terminado.

## El dashboard { #the-dashboard }

La página de inicio es una **cuadrícula de widgets que tú ordenas**, y es la
respuesta a "qué está pasando" sin abrir cinco páginas.

Existen cincuenta y siete tarjetas. No las verás todas: **cada tarjeta está
protegida por el permiso que necesitan sus datos**, así que un widget que no
puedes leer nunca se monta y sus consultas nunca se lanzan — excepto tus
propias notificaciones, más abajo, que solo necesitan que hayas iniciado
sesión. Una banda vacía desaparece junto con su título en lugar de quedarse ahí
vacía.

Un selector arriba dice de quién es el dashboard, y ofrece solo las vistas que
puedes abrir. Todos empiezan en **Me**:

| Vista | Responde a |
| --- | --- |
| **Me** | Un saludo, tu periodo y todo lo que te espera, en dos frases - llamadas, respuestas por revisar, suites que fallan, sugerencias del asistente; tus runs, cuántos terminaron, lo que te espera (contado igual) y lo que costó; después las llamadas que te esperan, tus conversaciones, los agents que necesitan atención, las mejoras que te esperan, tus agents, lo que han compartido contigo, tus [datasets](datasets.md) con aquello contra lo que prueban sus casos, los eval runs y suites más recientes, las sugerencias del asistente por agent, skill y archivo, y las lagunas de conocimiento |
| **Me** | Un saludo y tu periodo en una frase; tus runs, cuántos terminaron, lo que te espera y lo que costó; después las llamadas que te esperan, tus conversaciones, tus agents y lo que han compartido contigo |
| **Organization** | La página que se ordena, descrita abajo |
| **Group** | Los miembros de un [grupo](departments.md) - sus runs, gasto, modelos, cuándo trabajan y quién lo usa más. El grupo se elige junto al selector. Un grupo cuyos miembros no ejecutaron nada en el periodo lo dice una vez, con un enlace al grupo, en lugar de una página de tarjetas vacías |
| **Deployment** | Solo para un [administrador del despliegue](permissions.md) — totales de la plataforma, salud, inquilinos más activos, valoraciones |

En **Me**, **Agents that need attention** lista los agents que puedes ver con
respuestas valoradas negativamente, runs fallidos o una suite de evals que falla
en el periodo - solo cifras, nunca lo que se dijo - con **Improve** en los que
puedes editar. La galería de agents marca los mismos agents de los últimos
treinta días con la insignia **Needs attention**, que al pasar el cursor dice
por qué. Las respuestas y los runs solo cuentan para la versión que el agent
sirve ahora en su entorno predeterminado: publicar una corrección borra la señal
hasta que la nueva versión acumule las suyas. Ambos requieren `runs:view`.

Debajo, **Improvements waiting for you** lista las sesiones de
[Improve](authoring.md#the-improve-wizard) detenidas a la espera de tu siguiente
paso o decisión, cada una abierta en su parada, y las
[comprobaciones de un cambio de skill](skills.md#when-an-agent-got-worse) que
puedes decidir y que siguen en curso o esperan una decisión. Después vienen los
cambios de skills que propusieron los agents, luego los agents fijados y los forks
que main [ha dejado atrás](skills.md#which-version-an-agent-reads). Un
fork se pone al día desde ahí, y un agent fijado se mueve en la página de su skill.

La vista de la organización muestra las tarjetas que responden con datos,
agrupadas en bandas. El resto - integraciones, canales, rutinas, sincronización
de conocimiento, departamentos, miembros, sandboxes - espera en el catálogo, a un
clic bajo **Customize**:

| Banda | Responde a |
| --- | --- |
| _(sin título, arriba del todo)_ | El resumen, los runs en el tiempo y cómo terminaron |
| **Needs attention** | Lo que está esperando: [aprobaciones](governance.md#approvals), fallos recientes, margen de budget, tus [notificaciones](#the-bell) más recientes |
| **Usage & cost** | Qué agents se usan, gasto, [minutos de voz](#voice-calls), cuándo ocurre el trabajo, de dónde vienen los runs, mezcla de modelos, latencia, calidad de respuesta, quién lo usa |

La tarjeta **Approval outcomes** espera en el catálogo, para quien pueda ver workflows.
Muestra cómo decidieron las personas los [pasos de aprobación](workflows.md#running-a-workflow)
que los workflows plantearon en el periodo. Muestra la proporción aprobada como se
propuso, las ediciones y su mediana de cambio, el tiempo hasta decidir y los cinco
workflows con más solicitudes. Está vacía cuando ninguna solicitud cae en el periodo
del dashboard.

La tarjeta **Workflow logs** también espera en el catálogo, para quien pueda ver
workflows. Muestra las líneas más recientes que los [Quick Logs](workflows.md#the-logs-page) de los
workflows que puedes ver escribieron en runs reales, y cuántas líneas añadieron las
últimas 24 horas, con los errores entre ellas. Una línea enlaza con su run y el nombre
del workflow con su página Logs. Está vacía hasta que se ejecuta un paso con Quick Log, y
no atiende al periodo del dashboard.

El dashboard se abre con **Get started** hasta completar cada paso: contarles a
los agents sobre ti, empezar una conversación, conectar un servicio con tu
propia cuenta, configurar una rutina y crear un agent - este último es una
pregunta al Architect, que lo crea contigo.

Quien construye agents tiene después los pasos de la organización: publicar un
agent, darle una base de conocimiento, añadir departamentos, invitar a alguien
del equipo y - quien pueda - poner un agent en una app de chat. Cada paso se
marca a partir de lo que existe, se haya hecho donde se haya hecho, no de un
clic en la tarjeta; cerrar la tarjeta la oculta en ese navegador.

Tu propia vista muestra además **Discover AgenticOS**: una tarjeta por cada cosa
fácil de pasar por alto - el servidor MCP propio de este despliegue para Claude
Code, Codex o Cursor, subagents, sandboxes, apps, routines, apps de chat, el
navegador web, bases de conocimiento y skills -, cada una lleva a donde se activa,
y solo las que puedes usar. Cierra una tarjeta o todas; también se guarda en el
navegador.

Los gráficos en el tiempo eligen su propio paso. El tramo desde el primer run del
periodo hasta ahora se dibuja en 48 puntos como mucho, con el paso más fino que
cabe - un minuto, cinco, quince, una hora, tres o seis horas, un día, una
semana -, así que una tarde se lee en minutos y un trimestre en semanas en lugar
de como un pico en el borde derecho.

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

## Rutinas y seguimientos { #routines-and-watches }

Los nombres de las rutinas se ajustan en teléfonos. Sin resultados aparece **Clear search**; **Retry** vuelve a cargar tareas y observaciones tras un error de lectura. Los horarios y disparadores se editan entre cabecera y pie de acciones fijos. La escritura bloquea campos y cierre; un rechazo conserva el borrador.

Routines tiene dos pestañas. **Tareas de agentes** ejecuta un agente elegido por
horario o evento con sus herramientas; las ejecuciones aparecen en Activity.
**Mis seguimientos** solo consulta cuentas personales conectadas y envía hallazgos
a la bandeja privada. Cada pestaña tiene sus acciones de creación.
`/routines?tab=watches` abre los seguimientos. Cada comprobación hace como máximo
30 solicitudes al modelo y recorta los resultados largos, así que seguir un
workspace grande sigue siendo barato.

Organización → Proactividad separa sugerencias, seguimiento, límites compartidos, horarios de entrega y mensajes de bienvenida. Los cambios sin guardar se pueden descartar. Los servicios en segundo plano muestran estado y consumo; los ajustes de modelo y presupuesto se despliegan por servicio.

Las rutinas programadas, por eventos y de seguimiento usan el mismo marco de diálogo, con encabezado y navegación fijos y un formulario desplazable. Crear un seguimiento recorre Configuración, Mensaje y Frecuencia; Atrás conserva el borrador. El selector de agentes muestra los mismos avatares que el chat. Las opciones de ejecución y entrega del seguimiento están reunidas en un solo panel de opciones avanzadas.

Discover comienza con capacidades ilustradas en el dashboard. Al pasar el puntero
por una curva de _Your period_ aparecen el intervalo y el valor; los costes se
muestran como importes. Los proyectos muestran descripciones y los agentes usan
los mismos avatares que en el chat.

Las tarjetas del panel usan filas compactas coherentes, símbolos de servicios y etiquetas de estado. Las cifras y los gráficos se adaptan al ancho de la tarjeta, también en diseños personalizados. Los indicadores de carga reflejan el tipo de contenido; un resumen no disponible permite reintentar en vez de afirmar que no hay propuestas.

El chat vacío saluda según la hora local y muestra primero el campo de mensaje, seguido de hasta cuatro sugerencias. Tienen prioridad los mensajes publicados del agente; AgenticOS puede usar sugerencias personales, guardadas durante cinco minutos en la caché de la sesión actual de la cuenta. Los marcadores reservan espacio hasta conocer la fuente. La bienvenida no muestra vistas previas de la bandeja, trabajo en segundo plano ni atajos de teclado; abre Inbox o Background work desde la navegación.

Los chats guardados muestran directamente marcadores del historial, sin destellos de bienvenida; la barra lateral y el historial cargan de forma independiente. Los envíos manuales desplazan suavemente el mensaje hacia arriba; la cola no mueve al lector. El desplazamiento, el tacto y el teclado cancelan el movimiento. Los menús y diálogos compartidos usan transiciones pequeñas y suaves; la preferencia Motion desactiva el movimiento.

## La bandeja { #the-inbox }

La **bandeja** (Inbox), bajo Chat en la barra lateral, es lo que la plataforma
te trajo por iniciativa propia: lo que tus
[vigilancias](governance.md#proactive-work) encontraron en tus conexiones y lo
que propuso la revisión nocturna. El número a su lado dice cuánto espera. Se lee
como un buzón: una fila por elemento, lo urgente primero, de dónde vino y
cuándo, y las respuestas en la fila.

Filtra por su origen, o abre **Hecho** para ver lo que ya aceptaste o
descartaste y recuperar algo descartado. **What they found** en la tarjeta de
vigilancias de Rutinas la abre filtrada a las vigilancias. Filas más cortas
encabezan tu dashboard como **Briefing**, y el chat vacío con el agente inicial
muestra el primero como tarjeta, con un enlace al resto.

Lo que una vigilancia encuentra y no hace falta avisar al momento espera a tu
mañana: a la hora que mantiene la proactividad de la organización, una
notificación y un mensaje directo de cada uno de sus bots de Slack, Teams y
Mattermost que te conoce enumeran lo nuevo. Cada hallazgo entra en un solo
briefing.

El selector de organización está debajo del logotipo, en la parte superior de la
barra lateral, y muestra el nombre y el avatar de la organización activa. Ábrelo
para cambiar de organización, gestionar organizaciones o crear una nueva. En la
barra lateral contraída, el avatar sigue siendo el selector; el menú del teléfono
ofrece el mismo control. Los ajustes de cuenta permanecen en el menú de cuenta
de la parte inferior.

La búsqueda está encima de los destinos de navegación, con su atajo de teclado
visible en el ordenador. Las notificaciones y el menú de cuenta permanecen debajo
de la lista desplazable. En dispositivos táctiles, los botones, campos, pestañas
y opciones de menú compartidos tienen áreas de toque mayores. Los diálogos usan
la altura visible sobre el teclado en pantalla; los paneles laterales mantienen
el foco dentro y lo devuelven al control que los abrió al cerrarse. En la búsqueda
de una lista, Escape borra primero la consulta y la siguiente pulsación cierra el
diálogo.

## La campana { #the-bell }

Al pie de la barra lateral: un contador en marcha de lo que aún no
has leído, y un clic abre la lista misma. A diferencia del widget de arriba,
abrirla trae la página completa que estás mirando, no una vista previa de
cinco tarjetas — **Load more** sigue paginando hacia atrás por la organización
en la que estás ahora, más lo dirigido al deployment entero, hasta llegar a lo
que ya ha caducado.

Cada fila empieza por aquello de lo que trata: la cara del agente, con una
insignia de cómo fue su run, o un icono del tipo de evento — verde para un run
terminado o un servidor MCP que vuelve a funcionar, rojo para un fallo o un
budget agotado, ámbar para una aprobación o un aviso de budget.

Cambia de organización y la campana es la de esa: una
notificación de la organización que dejaste no ha desaparecido, está detrás del
selector. El administrador del deployment es la única excepción — su campana no
la estrecha la organización en la que esté actuando, porque una audiencia
«admins» lo alcanza sin una membresía por la que acotar.

Una fila con un destino es un enlace; una sin él — el anuncio propio de un
admin, la mayoría de las veces — solo se puede marcar como leída. Marcar una
como leída, o todas a la vez, actualiza el contador al instante; nada aquí
espera a que se recargue la página. **Mark all read** barre por lotes hasta
cinco mil filas no leídas y luego vuelve a pedir el contador — así que con un
atraso mayor la insignia sigue mostrando lo que queda por leer y un clic más
termina el resto, en lugar de anunciar una bandeja que solo trabajó en parte.

Cada clic avanza siempre, incluso cuando todo el lote eran filas que quien lee
ya no puede ver. Nunca las marca: la comprobación es sobre los permisos
_actuales_, así que a quien estuviera degradado una semana y luego restituido le
aparecerían ya leídos los avisos de seguridad de esa semana. En su lugar, un
barrido truncado dice dónde se paró y el siguiente clic arranca desde ahí.

Tanto el contador como el barrido dicen cuándo se han parado en ese límite y no
al final de la bandeja — `approximate` en `GET /notifications/unread-count` y
`remaining` en `POST /notifications/mark-all-read` —, porque si no un contador
justo en el límite y un contador real del mismo tamaño son el mismo número.

Leída no es lo mismo que fuera, y se ofrecen las dos cosas. Pasar el cursor por
una fila revela una cruz que la saca de la lista; **Clear** en la cabecera saca
todo lo que está listado ahora mismo, leído y no leído por igual. Limpiar algo
no leído lo marca además como leído, porque una fila que nada en pantalla puede
alcanzar no debe seguir contando para la insignia. Como «Mark all read», una
limpieza está acotada — mil filas — y un atraso más largo pide un segundo clic.

Lo que una fila limpiada _no_ hace es volver. La notificación se conserva y deja
de listarse, en lugar de borrarse, y eso es lo que lo hace cierto: la bandeja
reconoce una repetición por el hecho que describe, así que una fila borrada
sería una que la siguiente comprobación de budget o el siguiente reintento
volverían a escribir. Descartar un aviso del que ya te has ocupado es, por
tanto, definitivo — para esa ocurrencia; uno _nuevo_, sobre un hecho nuevo,
sigue llegando. Las filas también caen solas: noventa días después de
escribirse si fueron leídas, y un año pase lo que pase.

Qué llega aquí y qué se puede desactivar le toca explicarlo a
[Governance](governance.md#alerts) — esta página es solo los dos sitios donde
lo lees: la campana para lo que acaba de pasar, la tarjeta del dashboard para
un puñado de las más recientes, la próxima vez que abras la página.

## El asistente { #the-assistant }

El **Architect** aparece junto a las notificaciones en la cabecera del móvil
y en la esquina inferior derecha del escritorio: un agent que
toda organización recibe sin instalar nada, compartido con todos los que pueden
ejecutar agents (`agents:run`). Está vinculado al
[servidor MCP de la propia plataforma](mcp.md#agenticos-as-an-mcp-server).
Pregúntale qué agents responden dudas de reembolsos, por qué falló el run de anoche
o qué hay en una base de conocimiento.

Dile qué debe hacer un agent y lo construye contigo, una pregunta cada vez, cada
una con respuestas propuestas: elige las capabilities, la base de conocimiento y el
modelo, dice por qué en una línea, esboza el agent, lo prueba con tus propias
preguntas como borrador sin publicar, corrige lo que estaba mal y lo publica cuando
lo apruebas. Una rutina la configura igual.

Antes de que cambie nada, te muestra lo que apruebas: el borrador de un agent
como el propio borrador - dónde se crea, su nombre, qué puede hacer y sus
instrucciones - y todo lo demás como la llamada exacta. Actúa con tus permisos,
así que encuentra y hace lo que tú podrías, y nada más. Su coste cuenta como el
de cualquier agent.

Un bocadillo sobre él habla de lo que te espera — aprobaciones, una organización
sin ningún agent — o de la página en la que estás, y de vez en cuando ofrece un
consejo. Haz clic en el bocadillo para preguntarle; × silencia esa página, y la
campana de su ventana apaga los bocadillos. Un bocadillo sin respuesta desaparece
a los pocos segundos. Si nadie lo toca durante menos de un minuto, el botón se
esconde en el borde derecho de la pantalla y deja una franja para sacarlo - con
un punto cuando algo espera - y se queda allí de página en página hasta que se
abre.

En un teléfono no hay bocadillo - taparía la página de la que habla - y el botón
lleva el punto en su lugar. Las aprobaciones que ya mencionó siguen mencionadas
durante el resto de la pestaña, aunque un enlace recargue la consola.

Su ventana es el propio chat de la consola, no una página dentro de la página, y
se abre con cuatro mosaicos, para que el primer mensaje sea un clic; guarda su
propio historial de conversaciones. En un teléfono ocupa toda la pantalla.

Cuando nombra una página, el enlace la abre en la consola detrás de la ventana y
señala el control al que se refiere — el botón que crea un agent, la pestaña de
aprobaciones. La cámara de su cabecera le muestra la página en la que estás: el
navegador pregunta qué pestaña compartir y una imagen se adjunta a tu próximo
mensaje.

Planifica los trabajos largos como una lista que puedes seguir, guarda
notas sobre ti entre conversaciones, te dice cuánto cuestan tus agents y solo
borra un borrador de agent que creó por error y una rutina que le pidas quitar.
Además de las
aprobaciones y de una organización vacía, su bocadillo avisa cuando un run tuyo
acaba de fallar y cuando un formulario lleva un minuto abierto sin terminar.

Antes de conectar un modelo, el Architect abre el mismo chat con una tarjeta visual de configuración, una lista breve de pasos y el enlace a los ajustes del modelo. Un mensaje en el widget o en el chat con el borrador del Architect recibe una respuesta de configuración y una tarjeta guardadas, sin llamar al modelo ni registrar un run de IA. La respuesta usa el nombre del agente elegido. Las acciones respetan los permisos; los demás miembros reciben indicaciones para contactar al administrador. Tras publicarlo, el widget permanece abierto para conversar normalmente.

El Architect es un agente como cualquier otro, así que su nombre, su modelo, su
conocimiento y el resto de su spec se editan en el Agent Builder - lo hace quien
puede cambiar los ajustes de la organización, porque todos en la organización lo
usan. La página de la organización tiene una tarjeta que lo apaga para todos y
fija su saludo. **Settings → Assistant** guarda solo tus propios consejos.

## Agentes incluidos { #shipped-agent-defaults }

AgenticOS, Architect y la configuración predeterminada de nuevos agentes no incluyen herramientas para planes de trabajo provisionales. Los agentes informan del progreso en el chat y usan Tasks administradas mediante AgenticOS MCP para el trabajo que debe persistir.

Ambos agentes iniciales y los nuevos agentes de consola incluyen Watch a command, Background topics, Work while tools run, búsqueda limitada de conversaciones anteriores y búsqueda local BM25 de herramientas con cinco resultados. Reciben especialistas research, explore y review, especialistas dinámicos y delegación sync/async automática. Los monitores necesitan una shell persistente y terminan con el turno; los temas en segundo plano sobreviven. Las conversaciones se buscan solo cuando hacen falta: primero fragmentos y después ventanas limitadas. Los grupos y las ejecuciones desatendidas no buscan historial privado.

Solo el AgenticOS incluido tiene Computer use, navegador web y Coding agent. El control del equipo y la programación usan por defecto el escritorio autorizado; la programación en sandbox necesita credenciales configuradas. El navegador incluido también usa el escritorio vinculado; un administrador puede configurar en su lugar un endpoint de navegador del despliegue. Los agentes nuevos heredan la configuración común sin estas tres herramientas. AgenticOS responde directamente a preguntas de la plataforma con su guía y AgenticOS MCP. Los valores incluidos ya no fijan Architect; la actualización elimina la fijación original sin modificar y conserva los delegados personalizados.

Cada organización recibe **AgenticOS**, para trabajo general, y **Architect**,
para configurar la plataforma. Ambos incluyen memoria. Los agentes creados en
la consola parten de la plantilla actual de AgenticOS; después se pueden adaptar
el prompt y las herramientas. AgenticOS puede consultar al Architect publicado
mediante AgenticOS MCP, respetando permisos, presupuestos y aprobaciones.

Al abrir la consola se comprueban los valores incluidos. Las instrucciones,
capabilities, vinculaciones MCP, skills y mensajes iniciales sin modificar reciben
actualizaciones. Cambiar solo el modelo o el presupuesto no impide actualizarlos;
las elecciones se conservan. Los prompts y herramientas personalizados quedan
protegidos. Los cambios sin publicar siguen como borradores y no se publican al
actualizar el agente activo. Los agentes archivados permanecen archivados. Las
instalaciones antiguas se reconocen por su origen o por valores históricos
conocidos, no solamente por el nombre.

El chat muestra guardados y correcciones confirmados de memoria con un enlace
a **Your memory**. Los rechazos y datos en disputa no se presentan como guardados
correctos. Las propuestas de rutinas y observaciones aparecen como tarjetas para
revisar antes de activarlas. Los formularios agrupan las opciones de ejecución y
entrega en opciones avanzadas, manteniendo sus valores predeterminados.

## Cambios hechos en otro lugar { #changes-made-elsewhere }

Una página abierta se mantiene al día con los cambios hechos en otro lugar: la
consola de un compañero, un script con una [clave de API](api.md), Claude Code a
través del [servidor MCP de la plataforma](mcp.md#agenticos-as-an-mcp-server) o el
Architect. Cada escritura correcta se anuncia a las consolas abiertas de la
organización en cuanto se confirma, también las que solo hace la consola —
compartir, rutinas, bots de canal, comparticiones de grupo, ajustes de
notificaciones—, y una lista o una página de detalle sin nada sin guardar vuelve a
pedir los datos en su sitio.

Un agent creado con una clave aparece en la página Agents sin recargar, y un agent
compartido en una pestaña muestra su nueva audiencia en otra.

También se anuncian los runs, cuando empiezan, se detienen en una aprobación o una
pregunta y terminan: un run que lanza una programación aparece en una página
Activity abierta y cambia de estado allí, sin que haya ninguna petición tuya
detrás.

También los datasets: un caso añadido o quitado, un cambio en la calificación,
una puntuación o una decisión de revisión, y los borradores que el
[generador de casos](datasets.md#generating-cases) termina en segundo plano, que
aparecen en la pestaña Generated de un dataset abierto sin recargar.

Las lagunas de conocimiento se anuncian igual: un tema descartado o redactado en
una pestaña, y las preguntas que un pase de agrupación coloca cada 15 minutos,
aparecen en una pestaña Lagunas de conocimiento abierta sin recargar.

La excepción es el Builder, porque guarda tu borrador mientras escribes. Cuando el
agent que editas cambia en otro lugar, deja de guardar y obtiene la nueva versión.
Si no hay nada sin guardar, simplemente la adopta; si hay cambios sin guardar, te
dice quién lo cambió y por dónde, y espera a que elijas **Recargar** (su versión)
o **Conservar mis cambios** (la tuya, guardada encima de la suya).

Solo te enteras de lo que podrías leer: un cambio en un agent, un skill, una base
de conocimiento, un archivo de contexto, una página, una clave, un servidor MCP
o un dataset que no ves nunca llega a tu consola, y una eliminación solo llega a los roles que
ven todas las filas de ese tipo. Los runs llegan a los roles que leen el historial
de runs o deciden aprobaciones, las lagunas de conocimiento a los roles que leen
todos los runs, los bots de canal a los roles que los gestionan, y
tus notificaciones solo a ti. Si la conexión se corta, la consola funciona como antes y se reconecta sola.

## Chat { #chat }

Donde hablas con un agent publicado. El selector elige qué agent responde, y el
run se comporta exactamente igual que en Slack o detrás de la API — mismo budget,
misma puerta de aprobación, mismo rastro de auditoría, porque
[todas las superficies pasan por un único runner](channels.md).

**La lista de conversaciones** dice con quién es cada hilo y cuándo se movió por
última vez. Uno cuyo run sigue trabajando muestra un indicador giratorio y cuánto
lleva; uno con una respuesta que no has visto desde la última vez que lo abriste
lleva un punto, que abrirlo borra - solo para ti, porque cada lector de un hilo
compartido lo lee por separado.

Las conversaciones que otras personas compartieron contigo están en **Compartidas
contigo**, debajo de tus favoritas. Renombrarlas, compartirlas, archivarlas o
borrarlas corresponde a sus propietarios. Su menú permite añadirlas a favoritas o quitarlas, o elegir **Quitar de mis chats**, que termina tu acceso y deja la conversación igual para los demás. Una
compartida contigo para leer no tiene cuadro de mensaje. Cuando alguien comparte
una conversación contigo, recibes una notificación que la abre. Las conversaciones compartidas no leídas y favoritas aparecen en sus secciones habituales.

En **Compartir**, cada persona con quien está compartida la conversación tiene
junto a su nombre un selector **Ver** o **Editar**, para cambiar lo que puede
hacer sin revocar y volver a compartir. Un enlace compartido sigue siendo de
solo lectura.

Las comparticiones directas se limitan por minuto a 100 intentos por organización, 20 por remitente, 20 por destinatario y cinco por pareja remitente–destinatario dentro de la organización. Una conversación nueva no reinicia los límites. Un rechazo devuelve `429` con el tiempo de espera y no crea ni la compartición ni su notificación. Las listas compartidas y el acceso efectivo se actualizan cada 15 segundos mientras la página está activa.

Tres cosas del compositor que conviene saber.

**Tus propias cuentas.** Un agent ligado a
[la cuenta de cada persona](mcp.md#whose-account-a-binding-speaks-through) en un
servicio le habla como tú. Los controles del chat enumeran qué servicios del
agent necesitan una cuenta tuya y si cada uno está listo, con un botón de conexión
que abre el consentimiento del provider en una pestaña nueva. Si preguntas antes
de conectar, no aparece nada hasta que el agent necesita de verdad el servicio:
entonces la respuesta se detiene en una tarjeta con ese botón y, en cuanto la
cuenta está conectada, la misma respuesta sigue con él. **Skip** deja que siga
sin él.

**Los adjuntos** se parsean y se entregan solo a esa conversación; no se añaden a
una [colección de conocimiento](file-processing.md). Consulta
[Procesamiento de archivos](file-processing.md#chat-file-uploads).

**Los comandos de barra** se expanden a un prompt antes de enviar el mensaje. Los
de serie vienen con el producto; puedes escribir los tuyos en
**Settings → Slash commands**, y ocultar cualquiera de los de serie que no uses.
Son tuyos, no de la organización.

**`@` señala al agent qué usar.** Escribe `@` y un menú ofrece lo que el agent
puede usar, en este orden: sus servidores MCP, los agents a los que pasa trabajo
(con la capability de delegación activada), sus capabilities - **Sandbox**, **Web
research** -, sus skills y después sus bases de conocimiento y archivos de
contexto. Lo elegido se queda en tu texto como `@Nombre`, marcado con su logo, y
al agent se le indica que lo use - las herramientas de un servidor o de una
capability, la búsqueda de una base de conocimiento, un skill - sin pegar su
contenido. Nombrar un agent le pasa el trabajo; nunca cambia quién responde.
Borra el `@Nombre` y lo elegido desaparece. Un enlace pegado muestra el icono de
su sitio encima del cuadro y en el mensaje enviado. Una mención nunca amplía lo
que el agent puede alcanzar: el servidor comprueba cada una de nuevo como tú,
frente a lo que el agent ya tiene. En el panel de pruebas del Builder el menú lee
el borrador que estás probando. Mientras una conversación está vacía, el cuadro muestra uno
tras otro ejemplos hechos con lo que el agent puede usar - su servidor, una
capability, un delegado, un skill - y `/`; desaparecen en cuanto haces clic en él.
Encima, las tarjetas son los **primeros mensajes** propios del agent, definidos en
el Builder bajo sus instrucciones; un agent sin ellos ofrece los cuatro del chat,
entre ellos uno para preguntar qué puede hacer y otro para configurar una rutina.

Las listas de conversaciones conservan el agente principal y también muestran Claude Code o Codex cuando los informes de tareas guardados confirman su participación. La barra lateral, los chats de proyecto, el dashboard y el historial de Quick Ask comparten los mismos iconos y etiquetas. Cada coding harness aparece una vez, permanece tras actualizar y no depende de los ajustes actuales del chat. Seleccionarlo sin ejecutarlo no lo añade al historial.

El panel Files agrupa los archivos por carpetas y distingue nombres iguales en distintos directorios. Las vistas previas HTML cargan las hojas de estilo locales y sus recursos anidados mediante el mismo acceso que la página. La vista previa y el código fuente permanecen separados; los scripts siguen desactivados. Si no se puede leer una hoja de estilo, se indica cuál ha fallado. Debajo de cada respuesta aparecen enlaces a los archivos modificados en ese turno, según las rutas comunicadas por herramientas de escritura/edición exitosas o por el coding harness. Los enlaces abren los archivos actuales del workspace, no una copia versionada.

Mientras trabaja el agente, los mensajes de progreso y las llamadas a herramientas que les siguen aparecen en orden de llegada dentro de un historial desplegado. Al terminar la ejecución, todo ese historial se contrae bajo un único control «Worked for…» o «Thought for…», dejando debajo solo la respuesta final. Al abrirlo se recupera el mismo orden de mensajes y grupos de herramientas. El razonamiento conserva su desplegable opcional; sus encabezados no generan fases. Las preguntas y aprobaciones mantienen el estado de espera hasta resolverse, también al delegar. Las tarjetas de aprobación activas y los resultados visuales permanecen fuera del historial terminado.

Las herramientas consecutivas entre mensajes forman un grupo contraído; ábrelo para ver las llamadas individuales.

Las aprobaciones del chat siguen siendo una tarjeta compacta junto al editor: operación, icono y título de la tarea u objeto, con argumentos adicionales bajo Details. Approve y Reject están al lado de la solicitud o debajo en pantallas estrechas. La actividad terminada muestra una marca discreta, los pasos en espera un estado propio y los pasos activos conservan su icono en lugar de una esfera animada por llamada.

Al volver a abrir un chat también se restauran las aprobaciones y preguntas de herramientas delegadas ausentes de la cronología del agente principal. Un subagente pausado se muestra trabajando durante su continuación HTTP aprobada. Un subagente publicado que ha terminado conserva su propio resultado cuando el agente principal se detiene ante otra decisión.

El texto recibido sigue siendo legible mientras carga el módulo de formato Markdown. El editor tiene una superficie opaca y un foco discreto, sin borde animado ni desenfoque del fondo.

El historial en vivo sigue el flujo de la página; el historial terminado y desplegado tiene altura limitada y desplazamiento propio. Los segmentos consecutivos de una misma ejecución y agente comparten resumen y hora de inicio, incluidos los mensajes entre herramientas y las continuaciones tras una aprobación. Otro agente o un mensaje del usuario intermedio inicia un turno separado. Los intercambios terminados y anidados siguen disponibles, incluidos los informes de agentes de programación; abre un intercambio para consultar instrucciones, respuesta y razonamiento contraído.

Las escrituras MCP confirmadas muestran tarjetas enlazadas de proyectos, tablas, tareas, registros, agentes, workflows, skills y Context. Los errores no generan tarjetas de éxito. Los mensajes enviados aparecen cerca del borde superior con espacio para la respuesta; el desplazamiento manual conserva tu posición. Las listas Person y Agent se desplazan dentro del diálogo del registro. Las preguntas siguen funcionando tras las continuaciones HTTP aprobadas.

Los avisos de resultados también están junto al editor. Mientras hay un panel de decisión visible o el chat está trabajando, se ocultan los avisos de aprobación incluso de ejecuciones anteriores. En los demás casos, enlazan a la cola de aprobaciones. Nunca ofrecen Visto, Hecho ni No volver a preguntar: solo aprobar o rechazar la solicitud real decide la operación. Inbox y la campana conservan sus notificaciones.

**Debajo de una respuesta.** Un agent con
[Follow-ups](reference/capabilities.md#follow-ups) ofrece debajo de su respuesta
más reciente hasta tres pasos siguientes como botones, y un clic envía uno. Una
línea dice qué anotó sobre ti, u olvidó, con **Manage** para
[las notas mismas](reference/capabilities.md#memory-files) - pídele que olvide
algo y lo hará. Cuando una petición necesita una capability que el agent no
tiene, una tarjeta propone activarla o pedírselo a su propietario
([cómo](reference/capabilities.md)).

**Guardar una petición que funcionó.** Pasa el cursor por tu propio mensaje: el
calendario lo convierte en una rutina - el mismo prompt, semanal por defecto, en
el agent que respondió - y el robot le pide al Architect que cree un agent que lo
haga. Pasa el cursor por la respuesta y el marcador le pide al Architect que haga
un [skill](skills.md) de cómo se hizo, para que cualquier agent lo haga igual la
próxima vez; recibe tu petición y la respuesta, y se ofrece a quien puede escribir
skills.

**Enlaces que señalan.** Un enlace de la consola que un agent escribe en su
respuesta - «aquí está el botón que conecta tu Gmail» - abre esa página sin
recargar la consola, y un `?highlight=` en él señala el control que nombra, como
hacen los enlaces del Architect.

**El agent AgenticOS te conoce.** Mientras tu cuenta no dice nada de tu rol ni de
tu trabajo, un saludo empieza una entrevista corta: a qué te dedicas, qué llena tu
semana, con qué herramientas trabajas - una pregunta cada vez, cada una con
respuestas para elegir. Lo que dices se guarda en tu perfil, así que desde
entonces lo sabe cada agent, y la entrevista termina con hasta tres tarjetas que
configurar - una rutina, un servicio que conectar, un agent propio - cada una con
un clic. Sáltate una pregunta, o pide algo real, y hará el trabajo en su lugar.

**Lo que notó durante la noche.** Donde tu organización lo activó, una vez al
día, temprano en tu mañana, la plataforma lee tus conversaciones recientes en una
tarea en segundo plano: una
petición que repites se convierte en una rutina propuesta, lo que un agent supo
de tu rol en un perfil propuesto, y tu chat vacío de AgenticOS recibe primeros
mensajes escritos para tu trabajo. Las propuestas esperan como tarjetas en ese
chat vacío, en tu dashboard y en la campana, y **Ajustes → Asistente** las lista
todas - ahí recuperas una descartada o te excluyes; acepta una y queda configurada, descártala y la misma
propuesta no se vuelve a hacer. Nada se ejecuta cuando no pasó nada nuevo, y lo
que esto puede gastar tiene un [límite por persona](governance.md#proactive-work).
Un enlace de chat con `?agent=<slug>` abre el chat en ese agent.

**El horario laboral** en **Settings → Profile** dice a los agents cuándo
trabajas, para que una rutina que propongan caiga dentro de tu día. Nada espera
por él: es conocimiento para el agent, no un calendario.

Al volver a abrir una conversación, ves los mensajes más recientes. Usa **Load earlier messages** encima del historial para leer turnos más antiguos. Las respuestas en curso y los resultados sin guardar siguen visibles mientras se actualiza el historial guardado.

Si no se puede guardar una respuesta del asistente, el chat te pide que copies el texto que necesites antes de salir de la conversación. Esto también se aplica a las respuestas parciales de ejecuciones interrumpidas. El texto transmitido sigue visible, pero puede faltar al volver a abrir la conversación.

**Mientras el agent trabaja**, lo que envías espera su respuesta, como en
cualquier chat: queda en una cola encima del cuadro de texto y sale cuando termina
el run. Arrastra un mensaje de la cola, o usa sus flechas, para cambiar el orden.
**Send now** lo envía en cambio a la tarea en curso - el agent lo lee en su
siguiente paso y corrige el rumbo sin empezar de nuevo, y aparece en la
conversación donde llegó. Un mensaje con archivos siempre espera la respuesta.
Slack, Telegram y Mattermost mantienen su propio comportamiento, descrito en
[Canales](channels.md).

**Irte mientras responde.** No tienes que esperar. Cierra la pestaña, sal de la
app o abre otra conversación, y el agente termina la respuesta solo: llega a la
conversación, y la campana - y un correo, si los mantienes para los runs que
terminan o fallan - te avisa de que está ahí, con un enlace a ella. Un turno que
sigue en marcha tras una hora sin nadie mirando se detiene, y se te avisa de eso
([`CHAT_DETACHED_TURN_MINUTES`](configuration.md#a-chat-turn-left-running)). Uno
que espera una aprobación o tu respuesta a una pregunta te avisa por esa vía.
Si vuelves mientras aún responde - a la conversación, desde otra pestaña, tras
recargar -, el chat retoma la respuesta donde está, con todo lo que el agente ha
hecho hasta entonces, y la sigue dibujando a medida que llega.

**En el teléfono** el chat se comporta como una app de mensajería: el campo de
escritura queda sobre el teclado y la conversación en su último mensaje mientras
se abre, Enter empieza una
línea nueva, y adjuntar un archivo o dictar están detrás de un único **+**. Los
campos nunca son tan pequeños como para que iOS haga zoom en ellos.

**Dibujos.** Un agente con [Visuals](reference/capabilities.md#visuals) dibuja bajo
su mensaje - un diagrama, una explicación con controles deslizantes, una escena 3D - y
usted lo ve aparecer mientras se escribe; sus scripts arrancan cuando está completo. El
panel muestra el dibujo entero, ajustado a la conversación, con botones para abrirlo a
pantalla completa, mostrar su código, descargarlo, copiar un SVG como imagen, ampliarlo
y guardarlo como [aplicación](artifacts.md#visuals) con un enlace para
compartir. Cuando un dibujo informa de un error, el agente ya lo sabe; **Corregir**
vuelve a pedírselo. En un teléfono, un toque lo abre a pantalla completa.
La tarjeta **Recent visuals** del panel muestra los últimos dibujados para usted, y
cada uno abre la conversación en la que se dibujó.

**Borradores.** Un agente con [Borradores](reference/capabilities.md#drafts) muestra
el texto que enviarás o pegarás en otro sitio - un correo, una respuesta, una
publicación - como una tarjeta en su respuesta. Cada parte tiene su propio icono de
copiar, que copia texto plano; varias variantes de un borrador son pestañas en la
misma tarjeta. El **Copiar** propio de un mensaje incluye también sus borradores.

**Ver un recorrido.** El [navegador web](reference/capabilities.md#browser-automation)
se abre automáticamente en un panel lateral a toda altura junto al chat.
En pantallas estrechas ocupa toda la pantalla. Al cerrar el panel queda
un enlace compacto en la conversación para volver a abrirlo. Las tarjetas de
páginas visitadas muestran el icono del sitio, el dominio y el título, también
al volver a abrir la conversación. Cada respuesta conserva una tarjeta por pestaña
del navegador; los clics, las nuevas lecturas y volver atrás actualizan esa tarjeta.
La barra de pestañas del panel cambia de página. Al terminar queda la última imagen. **Reanudar sesión** pide al
agente restaurar la sesión privada, disponible durante una hora como máximo. Las páginas
remotas se cierran tras cada ejecución. Reanudar carga las URL, cookies y local storage,
pero no formularios sin guardar ni memoria JavaScript. El agente lee nuevos números de elementos.

**Tomar el control de un recorrido.** Mientras un recorrido está en curso, **Take over**
en la barra del navegador detiene al agent tras su paso actual y te da la página, en la
misma ventana: clic, escribir, desplazarse, pegar. **Hand it back** y el agent sigue
desde donde lo dejaste. Cuando el agent no puede pasar solo de una página - un inicio de
sesión, un captcha -, el navegador dice _The agent needs you_ y para qué.
Quien puede ver runs pero no editar el agent puede mirar, no manejar. La misma ventana
se abre en una página propia desde el enlace de un canal. Consulta el
[navegador web](reference/capabilities.md#browser-automation).

**Señalar en la página.** El botón del bocadillo en la barra del navegador te deja
hacer clic en un punto de la página y escribir una nota sobre él - _este botón, no
aquel_. **Add to message** pone la página en tu mensaje como una imagen con el punto
marcado, con tu nota y la dirección de la página, para enviarlo o seguir escribiendo.
Funciona también en un browse terminado, sobre su última imagen.

**Seguir con la sesión iniciada.** Cuando el browse actúa por ti - tu propio chat, tu
mensaje directo, tu propia programación -, **Devolver** ofrece _Mantener mi sesión en_
el sitio en el que estás. Márcalo después de iniciar sesión y los browses posteriores
que actúen por ti empiezan con la sesión iniciada allí: las cookies y el almacenamiento
del sitio quedan sellados en el vault solo para ti, nunca se muestran y nunca se usan
para un visitante del widget, una sala compartida, una clave de API ni un disparador de
eventos. **Ajustes → Inicios de sesión** lista los sitios que guardaste, y **Olvidar**
hace que el siguiente browse empiece sin sesión. **Iniciar sesión en un sitio** abre ahí
un navegador en cualquier sitio solo para ti, antes de que un agent lo necesite: inicia
sesión, devuélvelo con la casilla marcada y la sesión se guarda igual. Necesita el
navegador de inicio de sesión del despliegue
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

**Detener una ejecución en espera.** El botón **Stop** sigue disponible mientras el
agente espera una respuesta, una aprobación o la conexión de una cuenta. También
funciona al recargar una pregunta o aprobación pendiente. Detenerla cierra las llamadas
pendientes sin reanudar el modelo y conserva el coste registrado. Puedes detener tus
propias ejecuciones; quienes pueden aprobar también pueden detener una ejecución
pendiente de aprobación. Si un error temporal impide detenerla, la tarjeta sigue
disponible para volver a intentarlo.

### Dictado { #dictation }

El micrófono está junto a Enviar en cada agent, y en el menú `+`. Convierte la
voz en texto dentro del cuadro y nunca lo envía: lo que dijiste aparece donde
estaba el cursor cuando pulsaste el micrófono, listo para editar, y no va a
ninguna parte hasta que pulses Enviar. Cómo se transcribe lo decide el agent, en
la pestaña Dictado de [su tarjeta Voice](#an-agents-voice-card):

- **Transcribe with a provider** encendido — el navegador graba y este
  despliegue envía la grabación al provider del agent o al predeterminado de la
  organización. Funciona en cualquier navegador que pueda grabar. El endpoint,
  sus límites y lo que se registra están en
  [Dictado en el chat](ml-services.md#dictation-in-chat).
- Apagado, o sin clave con la que enviarla — el reconocimiento de voz del propio
  navegador, así que el audio va al fabricante del navegador (Google, Apple) y no
  cuesta nada. Firefox no tiene: su micrófono lo dice al pulsarlo. Mientras
  escucha, una nota sobre el compositor dice que el Dictado del agent está
  apagado, y enlaza a su pestaña Dictado para quien puede editar el agent.

Con un provider, al pulsar el micrófono flota sobre el compositor, que no
cambia, una **píldora de grabación**: Cancel, el nivel, un temporizador y Stop.
**Enter** detiene y transcribe, **Escape** cancela, y nada de lo que se escriba
o pulse mientras una grabación está en curso o transcribiéndose se envía. La
grabación se detiene sola en el dictado más largo de la organización y se
transcribe, y un micrófono desconectado a mitad la termina igual, en vez de
descartarla. Si la subida tarda más de un segundo, la píldora muestra cuánto se
ha subido; después dice **Transcribing** hasta que llega el texto. El
reconocimiento del navegador tiene su propia píldora, con **Done dictating**.

Todo lo que el dictado tiene que decir aparece en una franja sobre el
compositor, junto a la píldora: la petición de permiso, un micrófono bloqueado o
ausente, los últimos 30 segundos, cinco segundos sin sonido, una grabación de
menos de un segundo (no se envía), una grabación detenida en el límite y cada
fallo. Cuántas palabras se insertaron se anuncia al lector de pantalla en lugar
de mostrarse, porque las palabras están en el cuadro. Una grabación que no se
pudo transcribir se guarda hasta que pulses **Retry** o **Discard**.

El brillo alrededor del cuadro de una página alojada mientras hablas sigue a **Voice glow** en
**Settings → Profile → Appearance**, junto al tema y a **Motion**: **Vivid**,
**Subtle** (por defecto) u **Off**. Se recuerda por navegador. **Motion** decide
cuánto se mueve toda la consola: **System** (por defecto) sigue el ajuste de
movimiento reducido del sistema operativo, **Reduce** reduce el movimiento sin
él y **Full** lo mantiene diga lo que diga el sistema operativo. Mientras el
movimiento está reducido no hay brillo alguno, la franja aparece sin deslizarse
y el nivel es un indicador de cinco pasos.

**Workflow steps** en la misma tarjeta elige cómo dibuja un paso el lienzo del
workflow: **In colour** (por defecto) dibuja cada paso en su familia,
**Simple** deja las fichas neutras y el minimapa gris. Se recuerda por navegador; la
barra de herramientas del lienzo tiene el mismo interruptor. Véase
[Cómo se dibuja un paso](workflows.md#how-a-step-is-drawn).

### La tarjeta Voice { #the-voice-card }

En la página **Members** de la organización, para alguien con `org:settings`.
Contiene el speech-to-text **predeterminado** que heredan los agents y los bots
de canal, y cuánto puede durar un dictado; si un agent dicta con un provider, o
atiende llamadas, se activa en la propia tarjeta Voice de ese agent. **Max
recording length** va de 10 segundos a 10 minutos. **Default provider** es el
provider y el modelo del catálogo de speech-to-text y un idioma (detección
automática, o un idioma fijo, que es más preciso). También es a donde los
[bots de canal](channels.md#what-every-channel-shares) configurados para heredar
envían sus mensajes de voz; **None** lo borra.

**Key**, junto al provider, es la clave del vault con la que se envía el
predeterminado. Lista las claves de API cuyo propósito es ese provider y que
toda la organización puede ver - la plataforma gasta esta clave en el dictado de
cada miembro y en cada bot que hereda, así que la clave privada de un miembro no
se ofrece y se rechaza si se envía. Con exactamente una clave así, se elige por
ti, y en cualquier caso se guarda por nombre; nada elige una clave en tiempo de
ejecución. Un provider sin clave aparece marcado como **no key for this
provider** y el selector enlaza al vault para añadir una. Cuando el
predeterminado no puede funcionar - el modelo se retiró del catálogo, o la clave
se borró o se hizo privada - la tarjeta lo dice, y pide **choose a key** cuando
es eso lo que falta.

Para alguien que además tiene `runs:view`, la tarjeta empieza con una línea
sobre lo que la organización transcribió en los últimos 30 días — "42 min · 118
recordings (30 without a length)" — entre dictado, mensajes de voz de canales y
la API. **Show breakdown** lo desglosa por agent y por bot de canal. Los minutos
solo cuentan las grabaciones cuya duración se informó, así que la línea dice
cuántas no; está oculta mientras no se ha transcrito nada. Las cifras vienen de
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### La tarjeta Voice de un agent { #an-agents-voice-card }

La pestaña **Build** de un agent tiene una tarjeta **Voice** después de los
ajustes del modelo, con dos pestañas: **Voice calls** y **Dictation**.

**Dictation** contiene **Transcribe with a provider**. Encendido, el micrófono
del chat envía la grabación a un provider: **This agent's own** (el
predeterminado) elige un par del catálogo y la clave con la que enviarlo - una
clave de API de ese provider que puedas ver, porque publicar se la presta a todo
el que pueda ejecutar el agent - y, hasta que elijas una, se usa el
predeterminado de la organización, nombrado. **Organization's** mantiene el
provider, el modelo y la clave de la organización. Apagado, o sin clave con la
que enviarla, transcribe el navegador, lo que no cuesta nada.

El idioma se elige aparte: heredar el de la organización o fijar uno - así un
agent en polaco puede conservar el provider y la clave de la organización. La
tarjeta forma parte de la spec, se guarda con el borrador y está activa en cuanto
se publica el agent, y se aplica al [dictado](#dictation) hacia este agent y a
los mensajes de voz que heredan sus bots de canal.
[El orden](ml-services.md#which-engine-a-recording-reaches) cuenta el resto.

### Llamadas de voz { #voice-calls }

Una [llamada de voz](voice.md) es una conversación hablada con un agent
publicado: hablas, responde en voz alta y puedes interrumpirlo. Las llamadas se
activan en el agent; la organización no tiene ajustes de llamadas.

- **La tarjeta Voice del agent**, en su pestaña **Voice calls**: el provider y
  el modelo de la llamada (para Azure, el nombre del deployment y su modelo
  base), la clave, la voz con un botón de **reproducir** para oírla, el idioma
  hablado (o **Follow the caller**), la **Longest call** (10 minutos si no se
  fija, 50 como máximo) y las **Instructions for calls**. La tarjeta lista lo que
  el agent [pasa a su modelo de texto](voice.md#handing-work-off) en las
  llamadas, dice que los guardrails no pueden filtrar las palabras habladas antes
  de que se oigan y que las llamadas se registran como texto sin guardar audio.
  Entra en vigor cuando se publica el agent.
- **El interruptor Voice calls de un embed**, en los formularios del widget y de
  la página alojada - mira [Canales](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Antes de ofrecer una llamada, la consola pregunta si este agent puede atenderla
(`GET /agents/{id}/voice`), para que nadie conceda el micrófono solo para ser
rechazado. La respuesta dice qué falta: ninguna voz configurada en el agent, el
modelo ya no se ofrece, o no hay clave.

El **botón de llamada** ocupa en el compositor del chat el lugar de Enviar
mientras el cuadro está vacío - al escribir algo vuelve Enviar -, en cada agent. Cuando este agent no puede atender una llamada aparece tachado, y al
pasar por encima, enfocarlo o pulsarlo dice por qué. Quien puede editar el agent
recibe **Open in the Agent Builder**, que abre su tarjeta Voice en la pestaña de
llamadas; a cualquier otra persona se le dice que pregunte a quien pueda.

Durante una llamada flota una **píldora** sobre el compositor, que se queda como
estaba, borrador y adjuntos incluidos: lo que hace la llamada, su tiempo, una
forma de onda de ambas voces, pulsar para hablar, silenciar y **End call**. Solo
End call termina una llamada; abrir otra conversación o un chat nuevo la cuelga.
Por defecto se habla sin manos; **pulsar para hablar** (mantener el botón o la
barra espaciadora) es una elección que recuerda tu navegador. Con movimiento
reducido, un medidor de nivel escalonado sustituye a la forma de onda.

Una llamada pasa por estados que la píldora nombra: conectando, escuchando,
hablas tú, pensando, habla el agent, interrumpido, trabajando con una
herramienta, esperando tu aprobación, una aprobación que no puedes dar, casi sin
tiempo y terminada - por ti, por un límite, una conexión caída o un fallo.

La llamada ocurre en la conversación: cada turno se dibuja como el mensaje en
que se convertirá, creciendo palabra a palabra mientras se habla, un lector de
pantalla oye cada línea cuando es definitiva, y el mensaje guardado ocupa su
lugar sin que nada se mueva, así que la llamada queda en tu historial y puedes
seguir escribiendo. Mientras el agent piensa o ejecuta una herramienta, la
conversación lo dice donde aparecerá su respuesta.

Las **aprobaciones** se deciden en la llamada: una tarjeta en la conversación
muestra la herramienta, sus argumentos exactos y lo que se te oyó decir, con una
cuenta atrás de 60 segundos. Solo sus botones deciden; decir "sí" no aprueba
nada. Sin `approvals:decide`, la tarjeta dice que la herramienta necesita una
aprobación que no puedes dar por voz y ofrece terminar la llamada y seguir por
texto.

Las **preguntas** que hace el agent aparecen como la tarjeta de pregunta
del chat, también leídas en voz alta: toca una respuesta o simplemente dila. El
trabajo que el agent [pasa a su modelo de texto](voice.md#handing-work-off)
muestra cada paso mientras se ejecuta, y los pasos quedan después en el turno.
Los **límites** se dicen en voz alta: un minuto antes de que acabe la llamada más
larga se te avisa, y cuando se agota el tiempo o el budget el agent dice una
frase y la llamada termina.

Una **franja sobre el compositor** señala lo que te necesita: la petición del
micrófono, una aprobación pendiente (con **Show card**), el último minuto, un
límite que termina la llamada, una reconexión o cómo funciona pulsar para
hablar. Cuando la llamada termina, una tarjeta en la conversación dice cuánto
duró y cuántos turnos se guardaron, o qué límite la terminó, con **Call again**.
Una llamada que no llegó a empezar dice por qué sobre el compositor, con **Try
again**.

En **Activity**, una llamada es una fila con una insignia de micrófono, y el
filtro de tipo (**Text** o **Voice calls**) se limita a las llamadas; una llamada
que se reconectó sigue siendo una fila, con el tiempo y el coste de todas sus
conexiones sumados. La tarjeta de panel **Voice minutes**, en la banda de Uso
para quien tenga `runs:view`, muestra los minutos de llamada y las llamadas del
periodo y los tres agents principales.

### Bifurcar una conversación { #forking }

Para probar otro enfoque, o para llevar una pregunta lateral a un sitio donde no sature el hilo principal, elija **Bifurcar en una nueva conversación** bajo una de las respuestas del agent. Obtiene una conversación nueva y propia, en el mismo proyecto, con todo hasta esa respuesta incluida. El siguiente mensaje continúa desde ahí con el mismo historial; el original no cambia.

Solo el propietario de la conversación puede bifurcarla: quien la tiene compartida, para ver o para editar, no ve la acción. Una bifurcación copia los mensajes y las llamadas a herramientas, no los archivos de los adjuntos, los archivos que el agent escribió en su workspace, las imágenes que generaron los agents, el coste ni los registros de runs. El agent sigue teniendo el texto de un adjunto, pero la bifurcación no muestra su tarjeta; una imagen generada por un agent es la del original y deja de cargarse cuando el original se borra. Mientras un run de ese historial siga escribiendo, o espere una aprobación o una pregunta, la conversación no se puede bifurcar.

Arriba de una bifurcación aparece **Bifurcada de** con un enlace al original. Esa línea solo la ve usted: si comparte la bifurcación, la otra persona ve una conversación normal.

Cada bifurcación admite hasta 2000 mensajes, 10 000 llamadas a herramientas y 20 MiB de texto y datos estructurados copiados, con un máximo de diez solicitudes por minuto por miembro y organización. Una conversación que se está actualizando puede rechazar temporalmente la bifurcación; vuelve a intentarlo cuando termine la actualización. Los historiales que superen los límites deben acortarse antes de copiarlos.

Las bifurcaciones conservadas tienen una cuota separada de 100 MiB por miembro dentro de una organización y 1 GiB para toda la organización. Cada copia reserva sus datos más 4 KiB por conversación y 1 KiB por mensaje o llamada a herramienta. PostgreSQL serializa la admisión para impedir que solicitudes simultáneas superen la cuota. Solo eliminar la copia libera su reserva; archivar o eliminar el original no la libera. Actualmente no se pueden bifurcar dibujos con archivos de imagen guardados. Elige una respuesta anterior; la solicitud se rechaza antes de crear una copia dañada.

El texto y los medios externalizados de un resumen válido se restauran dentro de la copia, por lo que eliminar el original no elimina ese contexto. El contenido restaurado cuenta para el límite de 20 MiB. La restauración admite hasta 100 referencias externas y diez segundos. Si falta contenido o se supera un límite, se rechaza la operación sin crear una copia parcial.

Una conversación con una lista de tareas guardada solo puede bifurcarse en su último mensaje, que debe ser una respuesta del asistente. La copia conserva esa lista, incluidos los identificadores de tareas y las dependencias. No se guardan versiones anteriores de la lista, por lo que se rechaza una bifurcación anterior para evitar copiar tareas posteriores en un historial más antiguo.

### Temas en segundo plano { #background-topics }

Activa **Temas en segundo plano** en un agente publicado y pide, por ejemplo: «Investiga el error de exportación en otro tema mientras seguimos planificando la versión» o «Que el agente financiero revise estas cifras mientras comentamos la propuesta». Puede usar su propia versión fijada o un delegado publicado fijado en su especificación. Empieza desde una conversación propia; el tema nuevo pertenece al mismo proyecto e incluye el encargo del agente y un enlace al origen, sin copiar la transcripción original.

La barra **Temas en segundo plano**, encima del cuadro de mensaje, muestra tareas en cola, en marcha y pendientes. Abre el tema independiente para revisar el trabajo o responder a una aprobación o pregunta habitual. **Detener** cancela el trabajo posterior; no revierte cambios de archivos ni acciones externas ya realizadas. El panel muestra las mismas tareas. Cada persona puede tener cuatro tareas activas; una tarea y su respuesta de resultado no pueden crear más temas en segundo plano.

Al terminar, el agente original responde con el historial actual de la conversación. Espera a que terminen las respuestas en curso y resume sin herramientas: el resultado de una tarea no concede permiso para otra acción.

Conserva el modelo principal y el nivel de razonamiento seleccionados; la inferencia local sigue siendo local. El trabajo local de programación permanece en el ordenador emparejado concreto y en la carpeta autorizada. Se mantienen los presupuestos y aprobaciones del hijo. Cerrar el chat no cancela la tarea. Se informa de una interrupción del worker y no se repiten automáticamente las acciones externas. Las aprobaciones reanudan las tareas pausadas; perder la pertenencia o el acceso al proyecto detiene el trabajo nuevo y la entrega del resultado.

Es delegación explícita, separada de memoria, observaciones y rutinas. Los modos asíncronos existentes de subagentes y herramientas siguen ligados a una ejecución; usa **Temas en segundo plano** para trabajo que dure más que la respuesta de origen.

### Referirse a otra conversación { #conversation-references }

Un agente con **Conversaciones anteriores** ofrece las treinta conversaciones accesibles más recientes en el menú `@`. Elige una y plantea una pregunta concreta. La mención identifica el tema, sin copiar su transcripción ni cambiar al agente que responde. El agente lee el fragmento pertinente mediante la herramienta existente, con las mismas comprobaciones de acceso y audiencia. Siguen aplicándose las restricciones de los chats grupales. Para un tema anterior, pega su enlace o identificador y pide al agente que lo lea.

## Activity { #activity }

**Activity** muestra a quien tiene `runs:view` cada run de la organización: las
conversaciones, los agents de la organización respondiendo casos de eval y los
agents propios de la plataforma trabajando. Quién puede leer un run y su
transcripción no depende del tipo de run.

El run de un agent de la plataforma muestra su nombre en la columna Agent y una
etiqueta junto a su superficie: **Improve** para el asistente, **Grader** para el
juez, **Knowledge gaps** para el clasificador y el redactor, y **Test
questions** para el generador de casos. Un agent que responde un caso de eval
lleva **Eval**. Junto a la etiqueta hay un enlace a donde se lee ese trabajo: la
sesión de Improve, el eval run, el tema de la carencia o el dataset.

El filtro **Source** reduce la lista a **Conversations**, **Improve and evals**
o **System agents**. Empieza en todas las fuentes, así que un enlace desde un
borrador o una sesión a su run llega a una fila que la lista muestra.

## Para qué sirve cada área { #what-each-area-is-for }

**Overview** (Dashboard), **Chat** e **Inbox** encabezan la barra lateral.
**Build & manage** muestra Agents, Workflows, Routines y Apps sin desplegar;
después aparecen los Projects.

**Knowledge** está abierto por defecto e incluye Knowledge bases, Tables, Skills,
Context y Documents. Se recuerda la elección manual de abrirlo o cerrarlo.
**Monitoring** reúne Activity y Background work y comienza plegado.

**Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) y
**Organization** (Organizations, Groups) siguen siendo plegables y recuerdan la
elección. Un grupo que contiene la página actual siempre se abre para mantenerla visible.

| Área | Contiene | Lee |
| --- | --- | --- |
| **Agents** | El catálogo, el Builder, las versiones, el uso compartido, las pruebas, la actividad | [Tu primer agent](first-agent.md) |
| **Chat** | Hablar con un agent publicado | [Superficies](channels.md) |
| **Knowledge** | Colecciones, documentos, fuentes de sincronización, ajustes de ingesta | [Procesamiento de archivos](file-processing.md) |
| **Skills** | Procedimientos escritos que un agent carga cuando hacen falta | [Skills](skills.md) |
| **Context** | Conocimiento permanente ligado a muchos agents | [Archivos de contexto](context.md) |
| **Tables** | Registros tipados y sus columnas, vistos como tabla, tablero kanban o lista | [Virtual Tables](virtual-tables.md) |
| **Workflows** | Automatizaciones de varios pasos que ejecutan tus agents, construidas en un lienzo | [Workflows](workflows.md) |
| **Datasets** | Casos de prueba versionados, importados, exportados o añadidos desde una respuesta valorada | [Datasets](datasets.md) |
| **Routines** | Horarios y disparadores por evento | [Disparadores](triggers.md) |
| **Runs** | Qué se ejecutó, cuánto costó, qué tocó, si falló | [Governance](governance.md#audit) |
| **Documents** | Todos los archivos que los agents guardan para ti: lo que adjuntaste y lo que escribieron | [La sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Dónde ejecutan código los agents: hosts, sesiones en curso, política | [La sandbox](sandbox.md) |
| **MCP servers** | Conexiones a herramientas externas, personales y de toda la organización | [MCP](mcp.md) |
| **Channels** | Bots de Slack, Teams, Telegram y Mattermost, widgets, páginas alojadas | [Superficies](channels.md) |
| **Remote agents** | Agents de otros proveedores, registrados por su agent card de A2A, en los que delegan los agents | [Capabilities](reference/capabilities.md#remote-agents) |
| **Vault** | Credenciales, selladas por organización | [Secretos](secrets.md) |
| **Organizations** | Miembros, roles, invitaciones | [Permisos](permissions.md) |
| **Settings** | Providers, valores de ingesta por defecto, notificaciones, tu propio perfil | [Configuración](configuration.md) |
| **Admin** | El despliegue en sí: usuarios, inquilinos, sistema, jobs en segundo plano, ajustes del despliegue | [El despliegue](deployment.md) |

El catálogo de **Agents** se puede filtrar por **category** y **tag** — las
etiquetas editables y locales a la organización que se muestran en la tarjeta de
cada agent. Cada filtro es un menú de las etiquetas de los agents que puedes ver;
marca varias para ampliarlo. Las categories y los tags de un agent los mantienes desde su página
de detalle, junto a los controles del avatar, y el cambio surte efecto al
momento, sin publicar una nueva versión.

La pestaña **History** de un agente reúne sus versiones publicadas y sus entornos
con nombre y, para quien puede leer sus runs, su **Improvement history**: cada
sesión de Improve, qué midió, qué se decidió y cuánto costó. Una sesión terminada
abre su asistente solo para leer, con lo decidido en su último paso; consulte el
[historial de mejoras](authoring.md#improvement-history).

Los detalles de la organización tienen cinco pestañas: **Members** para personas e invitaciones; **Workspace** para perfil y ajustes de voz predeterminados; **Budget and approvals** para gastos y acceso; **Proactivity** para sugerencias, supervisión y entrega; y **AI & services** para Architect y servicios del sistema. Cada formulario mantiene sus permisos. Quienes gestionan presupuestos acceden a AI & services incluso sin poder configurar Architect. La selección se guarda en la URL, cambiar de pestaña conserva los borradores y los enlaces antiguos `?tab=voice` abren Workspace.

Al iniciar sesión, las invitaciones dirigidas al correo de la cuenta también aparecen en la consola y el onboarding, sin abrir el enlace del mensaje. La persona elige una organización y acepta explícitamente; Más tarde mantiene disponible el acceso a Invitaciones. Solo aparecen invitaciones vigentes al correo actual, sin enlaces compartidos ni organizaciones de las que ya se es miembro. Aceptar cambia a la organización elegida y abre su bienvenida. El servidor no devuelve el token de invitación en esta bandeja.

La bandeja exige demostrar el acceso al correo en la sesión actual: un nuevo acceso por OAuth con correo verificado o un enlace de acceso vinculado a esa dirección. Las sesiones con contraseña y las antiguas no muestran avisos para verificar el correo ni configurar su envío. La invitación se puede aceptar mediante su enlace original, incluso en instalaciones sin proveedor de correo. La prueba no se transfiere a otra sesión ni a una dirección cambiada. **Mostrar más invitaciones** carga otras páginas; el acceso al logotipo comprueba la invitación concreta independientemente de su página.

Los puntos ámbar señalan pestañas de organización y tarjetas de voz, sugerencias nocturnas, mantenimiento de memoria y Architect cuando falta configuración o las sugerencias están desactivadas. Al pasar el cursor o enfocar el punto aparece una explicación; pulsarlo la mantiene abierta. Los indicadores usan valores guardados, desaparecen al completar la configuración y respetan los permisos de edición. Las sugerencias desactivadas se presentan como una opción, no como un error. La tarjeta de notificaciones iPhone también señala la falta de una clave Apple. La preferencia de movimiento reducido desactiva la animación.

Los accesos guardados del navegador usan un panel compacto de ancho completo, sin estirar una sola entrada hasta ocupar toda la página. Los servicios conocidos muestran su marca integrada; los demás sitios usan su propio favicon sin enviar el referente y un globo si la imagen no está disponible.

## Idiomas { #languages }

La consola habla inglés, polaco, alemán y turco. La primera tarjeta del recorrido
ofrece los cuatro, y
el menú de la cuenta cambia el idioma en cualquier momento; la elección se guarda
en tu cuenta, así que la consola se abre en él en cada dispositivo en el que
inicias sesión. También puedes pedírselo a un agent - "cambia a inglés" - y la
página cambia mientras responde, sin recargar. Todos los agents responden en él
salvo que escribas en otro idioma.

Las palabras del producto - agent, skill, run, budget, MCP y el
resto de la lista de [traducir](howto/translate.md) - siguen en inglés en todos
los idiomas.

La misma tarjeta pregunta a qué te dedicas, y **Settings → Profile** guarda el
resto de lo que los agents saben de ti: tu rol, en qué trabajas y tu zona horaria.
Cada agent los lee al empezar un run, así que nunca los repites en un chat; «cada
lunes a las 9» son tus 9. La zona horaria se toma de tu navegador la primera vez
que inicias sesión, hasta que eliges una.

Los ajustes de perfil reúnen el retrato, el nombre y el correo en un formulario,
con los colores alternativos bajo una opción desplegable. Guardar está debajo
de los campos; Intro envía el formulario del nombre o del rol. Durante una
escritura del perfil, se bloquean los campos de identidad y contexto; un rechazo
conserva el borrador. Los días tienen áreas táctiles mayores y el inicio y el fin
son campos separados también en el móvil.

**Settings → Notifications** busca nombres y descripciones de eventos y muestra
seis por página. El selector de chat cambia el canal adicional sin alterar las
demás preferencias. Los destinos privados conectados aparecen primero; otras
plataformas están plegadas. Si falla la lectura de preferencias, destinos o
cuentas vinculadas, se ofrece reintentar sin inventar valores predeterminados
ni mostrar una lista de cuentas aparentemente vacía.

## El siguiente paso { #the-next-step }

Una página vacía porque aún no existe nada ofrece el camino para crear lo
primero: un agent, una rutina, algo compartido con un departamento. Crear un
skill, un archivo de contexto o una base de conocimiento termina con un aviso que
ofrece **Add to an agent** a quien pueda editar agents, para que lo creado llegue
a un agent sin pasar por el Builder.

## Cuando una página parece vacía { #when-a-page-looks-empty }

**Un estado vacío y una petición fallida se ven igual.** Todas las páginas de aquí
se abren en varias consultas y muestran "todavía nada" cuando una de ellas falla.

Así que antes de concluir que una colección está vacía o que un agent no tiene
runs, mira la pestaña de red. Esta es, con diferencia, la forma más habitual de
que un problema real se lea como algo tranquilo.

## Recapitulación { #recap }

- El dashboard son **cincuenta y siete widgets** que ordenas tú, guardados por
  persona y por organización — todos menos tus propias notificaciones
  protegidos por el permiso que necesitan sus datos.
- Una disposición guardada **puede ocultar y reordenar, pero nunca revelar** — la
  comprobación de permisos corre la última.
- **La campana** es un contador de no leídas en marcha con la lista completa a
  un clic, sin importar en qué página estés.
- **Chat, Slack y la API son el mismo runner**, así que lo que ves en la consola
  es lo que recibe un cliente.
- **Los cambios hechos en otro lugar llegan solos** — por la API, MCP o el
  asistente — y el Builder pregunta antes de reemplazar cambios sin guardar.
- **Los comandos de barra son tuyos**, incluidos los de serie, y puedes ocultar
  los que no uses.
- Una página que muestra "todavía nada" puede ser **una petición fallida**, no un
  recurso vacío.

El pie de la barra lateral muestra la versión de compilación de la consola junto a la búsqueda y las notificaciones, también en la barra contraída y el menú móvil. Procede de la versión del paquete frontend incluida en la compilación y no requiere solicitudes de red. El texto emergente la identifica como versión de la consola; un proceso API actualizado por separado puede ejecutar otra versión.

Una versión estable más reciente de AgenticOS resalta el número con un punto verde. Al pulsarlo se ven las versiones en uso y disponible y un enlace al lanzamiento oficial. La comprobación en segundo plano se ejecuta al abrir la consola, cada 30 minutos durante el uso y, si los datos están obsoletos, al recuperar el foco o la conexión. El servidor comparte los resultados públicos durante cinco minutos y no envía a GitHub datos de la cuenta, organización o despliegue. Los fallos de red mantienen visible la versión en uso sin afirmar que sea la última. El aviso no recarga la página ni instala actualizaciones automáticamente.

Tras iniciar sesión, **Novedades** muestra las notas públicas de GitHub de la versión instalada una vez por cuenta en este dispositivo. Espera a que se cierre el onboarding. Cerrarlo marca la versión como leída; la ausencia de notas o un error de red no interrumpen la sesión. Las funciones de una versión más reciente aún no instalada solo aparecen desde el aviso de actualización.

Chat controls recuerda el modelo, el modo de aprobación y las herramientas locales por cuenta y organización entre chats. Los ajustes de archivos del proyecto tienen prioridad. El consentimiento para todo el ordenador pertenece a una conversación, o a un agente cuando ese agente trabaja en tu equipo. Omitir aprobaciones requiere el permiso actual y la política de la organización. Agent setting (o Cloud para archivos) se desactiva si el agente publicado no tiene esa capacidad; ninguna alternativa local se activa automáticamente. Pulsar la opción local seleccionada la desactiva.

Silenciar notificaciones tiene un icono de campana; el compositor ya no repite la insignia de carpeta y acceso. Los avatares se superponen a tamaño completo y se separan ligeramente al pasar el cursor en la lista de chats expandida.

Los pies de lista permanecen en el borde inferior del panel, con espaciado uniforme y fondo opaco. Las tablas de administración paginadas desplazan sus filas de forma independiente, manteniendo visibles las cabeceras y la paginación. Los resultados vacíos y los errores permanecen en la misma zona de desplazamiento.

El directorio de organizaciones de administración muestra la imagen cargada o las iniciales en el color elegido si no hay imagen. El acceso a las imágenes en esta vista se limita a administradores del despliegue; el endpoint normal de avatares sigue requiriendo pertenencia a la organización.

**Chat controls → Tools & files** muestra la cuenta de coding que necesita un agente cuando su Coding agent se ejecuta como **Private cloud task with my account**: solo ese harness, con su logotipo y el estado del consentimiento. Conéctala o gestiónala sin salir del chat; todas las cuentas aparecen en **Settings → Profile**. Conectar no cambia el modo de ejecución del agente: las tareas privadas en la nube siguen necesitando **Private cloud task with my account**, mientras que el coding de escritorio utiliza su propio inicio de sesión local.

## Tu primera tarea { #your-first-task }

En un workspace nuevo se selecciona el **AgenticOS** incluido incluso antes de publicarlo, salvo que hayas elegido otro agente predeterminado. Ante el primer mensaje puede explicar la configuración del modelo y mostrar una tarjeta sin ejecutar el borrador ni llamar a un proveedor de IA. La respuesta y la tarjeta permanecen en el historial. Las personas autorizadas pueden abrir la configuración del modelo; los demás miembros ven indicaciones para contactar al administrador y el contacto de soporte de la instancia, si está configurado. Elige un modelo, añade una clave si se requiere y publica el agente antes de ejecutar respuestas normales de IA. Los borradores ordinarios y los agentes archivados siguen sin poder ejecutarse.

Si no hay un agente publicado disponible, el onboarding también permite abrir un chat de configuración con un borrador accesible del AgenticOS incluido. Los miembros no necesitan permisos de gestión de modelos; reciben orientación de configuración, no el resultado de una tarea de IA. Los borradores inaccesibles siguen bloqueados y un agente publicado accesible tiene prioridad.

Cerrar el aviso inicial o elegir **Ocultar durante 24 horas** lo pausa durante 24 horas
según la hora del servidor. Después puede reaparecer si la configuración no se ha
completado y el espacio aún necesita el primer inicio. Tras recorrer las preguntas,
**Finalizar la configuración y abrir la aplicación** registra la finalización para esta
membresía. No son obligatorios los campos opcionales, las invitaciones, un modelo, un
agente ni una ejecución de IA. Completar el onboarding y ejecutar una tarea correctamente
son estados distintos.

Abre **Get started** desde el panel, la propuesta inicial o la ayuda de una página.
En escritorio, el aviso del chat flota como una capa translúcida sobre la consola.
Las dos columnas de navegación conservan toda su altura. Ofrece configuración
a administradores y un ejemplo a miembros; se puede cerrar.
Aceptar una invitación abre este mismo inicio en la organización correspondiente.
El registro intenta iniciar sesión directamente; si falla, el formulario de acceso
conserva el destino y la cuenta ya creada.

El inicio respeta los permisos y el trabajo que ya existe:

| Persona | Inicio guiado |
| --- | --- |
| Administrador de la aplicación | Crear o elegir un workspace de empresa, preparar identidad e invitaciones y decidir cómo se incorporan las cuentas futuras. |
| Administrador de organización | Preparar el workspace y su límite de gasto, sin controles del despliegue. |
| Cuenta nueva de miembro | Bienvenida, perfil personal y contexto laboral opcionales, después una primera tarea. |
| Cuenta existente en otra organización | Bienvenida al workspace; usar el perfil guardado o revisarlo de forma deliberada. |

Un acompañante AgenticOS explica cada decisión con mensajes preparados de la interfaz.
No son respuestas de un modelo ni llamadas de IA. El perfil y el contexto acompañan
la cuenta en sus workspaces. Los datos opcionales se pueden omitir. **Guardar y
continuar** avanza después de guardar correctamente; un error conserva la pregunta.

El despliegue pregunta por el registro, el destino de cuentas futuras y un anuncio
opcional con vista previa. Solo envía campos editados. **Conservar ajustes actuales**
descarta el borrador de esa pregunta sin escribirlo. Elegir empresa conserva el rol
predeterminado y no traslada cuentas existentes. Aspecto, voz, credenciales push de
iOS y mantenimiento son tarjetas opcionales que abren la sección administrativa
correspondiente en otra pestaña. El recorrido no activa mantenimiento ni carga
credenciales automáticamente.

El presupuesto de organización ofrece propuestas y un deslizador. Conserva los límites decimales existentes. Sin límite es una opción explícita;
cero advierte que puede bloquear ejecuciones. Es un límite de uso registrado, no una
suscripción ni saldo de prepago. Aprobaciones, asistentes y voz avanzados quedan
plegados y conservan sus permisos y acciones de guardado habituales.

La URL conserva el paso, la pregunta de configuración y el workspace tras recargar. No conserva ediciones
sin guardar ni concede permisos ni acredita la finalización. Cambiar de organización
o perder permisos impide restaurar un paso privilegiado. El último paso registra la
finalización de la membresía incluso si se omiten datos opcionales y configuración IA.

La finalización antigua de la cuenta se aplica a membresías que ya existían en ese
momento. Una membresía posterior empieza por separado. Los chats propios y recorridos
terminados siguen evitando reinicios automáticos; los agentes publicados ocultan
ofertas de inicio normales. Los enlaces de registro e invitación dan la bienvenida a
miembros sin actividad propia ni finalización incluso si el workspace ya tiene agentes.
Los chats antiguos o fallidos cuentan como actividad sin afirmar una ejecución correcta.
El inicio manual y la reanudación siguen disponibles. El acceso normal abre el chat
o el enlace solicitado.

El nombre actualiza una vista previa identificada antes de crear el espacio.
Las organizaciones existentes muestran su logo o avatar alternativo configurado.
Las tarjetas contiguas de escritorio tienen la misma altura. Las transiciones
y los campos destacados respetan las preferencias de movimiento.
Los miembros eligen ejemplos grabados con pestañas de respuesta y material.
Cambiar de ejemplo mantiene la vista previa en la página. La configuración de IA
abre un diálogo que admite Escape y restaura el foco. Elegir un ejemplo no llama
al modelo.

Elige una nota de reunión ficticia, una pregunta sobre una política o una comparación
de ofertas. Revisa o edita el texto antes de **Run this task**. La ejecución usa
el modelo y los límites de gasto del agente seleccionado y puede generar cargos
del proveedor. Estos ejemplos no necesitan pantalla, micrófono, sandbox ni cuenta externa.

La vista previa del ejemplo sigue disponible sin agente. No llama
al modelo, no procesa las modificaciones y no cuenta como ejecución correcta.
Un builder autorizado puede preparar un asistente de texto compartido con un modelo
de chat compartido elegido explícitamente. Tiene un límite mensual de 5 USD dentro
del presupuesto del espacio. La preparación no modifica borradores existentes;
usa el Builder para cambiarlos. Los demás miembros ven el contacto del propietario.

La elección del ejemplo y su descarte se guardan por pertenencia y se conservan
en otros dispositivos. El inicio enlaza al último chat web propio completado.
Una ejecución completada confirma que se ejecutó, no su utilidad. Las visitas
guiadas son ayuda opcional; cerrarlas no crea una ejecución correcta. Integraciones,
archivos, agentes, invitaciones y rutinas son pasos siguientes opcionales.

Quienes gestionan miembros pueden comprobar si ellos y otro miembro pueden ejecutar un mismo agente publicado. La vista previa devuelve solo esa respuesta, sin nombres de agentes privados ni llamadas al modelo. No confirma la disponibilidad del proveedor. Este inicio bloquea las invitaciones desde una dirección de bucle local; use una dirección del servidor accesible para el destinatario.

Los turnos de chat completados mantienen visible el texto entregado antes de una pregunta del agente junto a la respuesta final, incluso tras rechazar la pregunta o reanudar la ejecución. Los resultados de herramientas y el razonamiento permanecen en el historial desplegable. Se aplica a chats guardados y compartidos; no clasifica las respuestas por su longitud.

El historial distingue a quien pregunta del publicador cuya autoridad admite una solicitud externa. Los remitentes de canales sin vincular aparecen como cuentas de chat explícitamente no verificadas, tanto en escritorio como en móvil; una solicitud anónima no recibe una identidad de miembro inventada. La API conserva `user_id` como contexto de autoridad y expone `initiated_by_publisher_fallback` y `asked_in_chat` para atribuir correctamente la solicitud. Esta presentación no vincula cuentas ni concede acceso a conexiones personales del publicador.
