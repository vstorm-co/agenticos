---
source_sha: 883886c71472
---

# Usa las valoraciones de los mensajes { #use-message-ratings }

Las personas pueden valorar las respuestas de un agent, y esas valoraciones se
leen de dos maneras: en la propia respuesta, y de forma agregada para quien
administra el despliegue.

## Valorar mensajes { #rating-messages }

### Me gusta / No me gusta { #likedislike }

Cada mensaje del asistente muestra dos botones:

- **Me gusta (👍)** — Púlsalo para indicar que la respuesta fue útil
- **No me gusta (👎)** — Púlsalo para indicar que la respuesta tuvo problemas

### Comportamiento del interruptor { #toggle-behavior }

- Pulsar de nuevo el mismo botón **elimina** tu valoración
- Pulsar el botón contrario **cambia** tu valoración (me gusta → no me gusta o al revés)
- Solo se pueden valorar los mensajes del asistente, no los tuyos

### Añadir comentarios { #adding-feedback }

Cuando valoras negativamente una respuesta, aparece un diálogo que pregunta **"¿Qué ha fallado?"**

Puedes dejar opcionalmente un comentario de hasta 2000 caracteres explicando el
problema. Ese comentario es valioso para entender por qué una respuesta no
resultó útil.

Motivos habituales para una valoración negativa:

- Información incorrecta o alucinada
- La respuesta no abordaba la pregunta
- Demasiado extensa o demasiado breve
- Formato o estructura deficientes

## Recuento de valoraciones { #rating-counts }

Cada mensaje muestra el total de valoraciones positivas y negativas de todos los
usuarios. La tuya aparece resaltada: verde para me gusta, rojo para no me gusta.

## Para administradores { #for-administrators }

### El panel de valoraciones { #ratings-dashboard }

Ve a **Admin → Response Ratings** (o `/admin/ratings`) para abrir el panel de analítica.

#### Cifras de resumen { #summary-statistics }

- **Total ratings** — Todas las valoraciones del sistema
- **Likes** — Número de valoraciones positivas
- **Dislikes** — Número de valoraciones negativas
- **Average** — Satisfacción global en una escala de -1,0 a 1,0

#### Gráfico de valoraciones { #ratings-chart }

Un gráfico de barras muestra las valoraciones de los últimos 30 días. Las barras
verdes son positivas y las rojas, negativas.

!!! note "La ventana de esta página está fijada en 30 días"

    Para leer las mismas cifras en un periodo que elijas tú, usa la tarjeta del
    dashboard **Answer quality, deployment-wide**, que sigue el filtro de periodo
    de la parte superior de la página.

### Filtrar valoraciones { #filtering-ratings }

Usa los desplegables de filtro para acotar los resultados:

| Filtro | Opciones |
|--------|----------|
| Tipo de valoración | Todas / solo positivas / solo negativas |
| Comentarios | Todos / solo con comentario |

### La tabla de valoraciones { #ratings-table }

La tabla muestra las valoraciones una a una, con:

- **Date** — Cuándo se envió la valoración
- **Rating** — 👍 positiva o 👎 negativa
- **Comment** — El texto del comentario, si lo hay
- **Message** — Vista previa de la respuesta valorada
- **User** — Quién envió la valoración
- **Actions** — Enlace a la conversación completa

### Exportar los datos { #exporting-data }

Exporta las valoraciones para analizarlas fuera del producto:

- **JSON** — Datos estructurados completos, aptos para scripts y herramientas de análisis
- **CSV** — Formato de hoja de cálculo para Excel o Google Sheets

!!! tip "Una exportación respeta los filtros puestos"

    Acota a las valoraciones negativas con comentario y exporta: eso es
    exactamente lo que obtienes. Los filtros forman parte de la consulta, no de
    la vista.

### Ver conversaciones { #viewing-conversations }

Pulsa **"View conversation"** en cualquier valoración para abrir el chat con esa
conversación cargada. Sirve para entender el contexto de una valoración.

## La página de conversaciones de Admin { #admin-conversations-page }

Ve a **Admin → All Conversations** (o `/admin/conversations`) para ver todas las conversaciones de los usuarios.

Esta página ofrece:

- Una lista de todas las conversaciones, con búsqueda
- Filtro por correo electrónico o nombre de usuario
- Filtro por periodo, predefinido o elegido por ti
- Enlaces directos al detalle de una conversación

## Enlaces directos a una conversación { #direct-conversation-links }

Puedes compartir un enlace directo a una conversación concreta añadiendo el parámetro `id` a la URL del chat:

```
http://localhost:3000/chat?id=550e8400-e29b-41d4-a716-446655440000
```

Esto es útil para:

- compartir el contexto de una conversación con el equipo
- guardar conversaciones importantes como marcadores
- enlazar desde herramientas externas o desde una documentación

Pulsar **"View conversation"** en una valoración o en la lista de Admin abre
exactamente un enlace así.

## Acceso desde la API { #api-access }

Para el acceso programático a los datos de valoraciones, están los endpoints de administración:

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/admin/ratings` | GET | Listar valoraciones, con paginación y filtros |
| `/admin/ratings/summary` | GET | Cifras agregadas sobre `from`/`to` (fechas UTC inclusivas, por defecto los últimos 30 días) |
| `/admin/ratings/export` | GET | Exportar valoraciones (JSON/CSV) |
| `/admin/conversations` | GET | Listar todas las conversaciones |

!!! warning "Cada endpoint `/admin` pertenece al superadministrador del despliegue, no a un rol de organización"

    La puerta es `CurrentAppAdmin` — un usuario con sesión iniciada cuyo
    `users.is_app_admin` es verdadero. No existe la columna `users.role`, y
    ningún rol de organización llega a estas rutas. Consulta
    [permisos](../permissions.md#layer-1-usersis_app_admin-the-deployment-superadmin).
