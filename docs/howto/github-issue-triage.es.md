---
source_sha: "50cf8da35126"
title: "Clasifica automáticamente los issues nuevos de GitHub"
description: "Dispara un agent en cuanto se abre un issue, haz que proponga prioridad y etiquetas a partir de la entrega y prueba el trigger firmando tú mismo una entrega."
---

# Clasifica automáticamente los issues nuevos de GitHub { #triage-new-github-issues-automatically }

Conecta un [trigger de eventos](../triggers.md) al webhook `issues` de un repositorio para que un issue nuevo llegue a un agent en cuanto se abre, y haz que el agent proponga una prioridad, etiquetas y una comprobación de duplicados a partir del texto de la entrega. Esta página prueba por separado la mitad del trigger, firmando una entrega sintética y enviándola directamente al webhook, sin usar ninguna cuenta de GitHub. Es un procedimiento para ejecutar, con un run registrado como referencia para esa mitad. Etiquetar o comentar en el issue necesita una conexión con GitHub que este entorno no tiene, y no se ejecuta aquí.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Para dispararlo de verdad: un repositorio al que puedas añadir un webhook (la fuente **GitHub** como OAuth App) o una GitHub App registrada para tu organización (**GitHub (App)**); consulta [las dos formas de conectar GitHub](../triggers.md#two-ways-to-connect-github-and-how-to-tell-which-you-are-running). Ninguna está configurada para la comprobación de abajo.
- Para que el agent etiquete o comente de verdad: una [conexión MCP de GitHub](../mcp.md#development) (autenticación por token) o los permisos de escritura de la propia GitHub App, vinculados al agent. Tampoco está configurado aquí.

## Prepara la entrada { #prepare-the-input }

Un payload del webhook `issues` recortado pero realista para un repositorio ficticio, lo bastante pequeño para comprobar la clasificación a mano:

```json
{
  "action": "opened",
  "issue": {
    "number": 42,
    "title": "Export button does nothing on Safari",
    "html_url": "https://github.com/acme/widgets/issues/42",
    "body": "Steps to reproduce:\n1. Open the reports page in Safari 18\n2. Click Export as CSV\n3. Nothing happens, no download, no error in the console\n\nWorks fine in Chrome. This is blocking our weekly export for finance."
  },
  "repository": {"full_name": "acme/widgets"}
}
```

Nada de esto es un repositorio real ni un informe real.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. Deja vacío el Toolbox para esta prueba: solo tiene que leer una entrega y razonar sobre ella. **Date and time** basta si quieres que la clasificación haga referencia a la fecha de hoy.
3. Pon como instrucciones el prompt de la plantilla incluida y luego pulsa **Publish**:

```text
You triage new GitHub issues from the delivery described in the task message.
Suggest a priority (low, medium, high) and one or two labels.
Say whether it looks like a duplicate of an existing issue, using only what the message gives you.
Flag immediately, in the first line, if it looks like a security report.
End with a short comment-ready summary a maintainer could paste onto the issue.
You have no tool to read the repository or post the comment yourself - say so if asked to do either.
```

Es el prompt de **Triage the new issue** en las plantillas de triggers (`GET /trigger-templates`), que rellena exactamente esto en un trigger de eventos **GitHub** nuevo.

## Configura el trigger { #set-up-the-trigger }

En **Routines → New event trigger → GitHub**, elige este agent, mantén el filtro por defecto (solo dispara con `opened`) y pega la URL del webhook resultante y el secreto de firma en **Settings → Webhooks → Add webhook** del repositorio, con el tipo de contenido `application/json`; consulta [una receta para GitHub](../triggers.md#a-github-recipe-5-minutes) para los campos exactos. Ese paso necesita el repositorio, que esta prueba no tiene.

## Ejecútalo { #run-it }

Sin un repositorio desde el que entregar, firma tú mismo una entrega sintética, exactamente como describe [firmar tú mismo una entrega](../triggers.md#signing-a-delivery-yourself) para la fuente genérica. Las entregas de GitHub usan el mismo esquema `HMAC-SHA256`; solo cambia el nombre de la cabecera:

```python
import hashlib, hmac, json, httpx

secret = b"<the trigger's signing secret>"
body = json.dumps(payload).encode()  # the fixture above
signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

httpx.post(
    f"{BASE}/api/v1/webhooks/triggers/github/{trigger_id}",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
    },
)
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| El POST firmado | `202`, al instante |
| El run en Activity | Superficie `schedule` (un trigger de eventos se dispara igual que una programación), estado completado |
| La clasificación | Nombra una prioridad y una o dos etiquetas, responde a la pregunta de duplicados y no se marca como informe de seguridad |
| La última línea de la respuesta | Un resumen breve, listo para comentar |
| Llamadas a herramientas | Ninguna: este agent no tiene herramienta de GitHub, así que solo razona sobre el texto entregado |
| Pedirle que ponga la etiqueta él mismo, en la conversación del mismo run | Dice que no tiene herramienta para ello, en lugar de inventarse una |
| El mismo payload firmado con el secreto equivocado | `403`, antes de considerar siquiera el run |
| Una entrega con `"action": "edited"` | `202` y ningún run nuevo: el filtro por defecto solo dispara con `opened` |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. La entrega firmada respondió `202`; unos diez segundos después apareció un run en Activity en la superficie `schedule`, con un coste de 0,003861 USD y el mensaje que añadió el trigger: "A GitHub issue was opened in acme/widgets. Issue #42: Export button does nothing on Safari …".

    La respuesta: "**Not a security report.** Priority: High. Labels: `bug`, `browser-compatibility`. Duplicate check: Nothing in the provided information suggests this is a duplicate …", terminando con un párrafo listo para comentar que nombraba los pasos de reproducción y sugería a un maintainer revisar el manejo de `Blob`/`<a download>` en Safari. No hubo llamadas a herramientas. Una entrega firmada con el secreto equivocado volvió como `403` con `"Webhook signature did not verify"`; el mismo payload con `"action": "edited"` volvió como `202` sin run nuevo.

## Cuando algo sale mal { #when-it-goes-wrong }

- **`403` en cada entrega, real o sintética.** El secreto no coincide, o el tipo de contenido no es `application/json`: una entrega codificada como formulario firma bytes distintos de los que envió GitHub. La pestaña **Recent Deliveries** del webhook en GitHub muestra la petición y la respuesta exactas para un repositorio real.
- **`202` pero nada en Activity.** `202` significa aceptado, no terminado, y también "no coincidió nada": un trigger inactivo o una acción filtrada responden igual. Revisa el filtro del trigger antes de suponer un fallo.
- **Un trigger `GitHub (App)` no tiene webhook que buscar en la configuración del repositorio.** Es lo esperado: la App entrega en una URL compartida por instalación, no en una URL por trigger. Consulta [cuando llega una entrega](../triggers.md#when-a-delivery-arrives).
- **El agent intenta comentar y no puede.** El agent de esta prueba no tiene herramienta de GitHub a propósito. Añadir una es un paso aparte y deliberado; consulta abajo.

## Registra la prueba { #record-the-trial }

Guarda el payload firmado, el filtro del trigger, el run en Activity y su respuesta. Esto solo demuestra el trigger y el prompt; no demuestra etiquetar ni comentar, que necesita su propia capability y su propia revisión.

## Siguientes pasos { #next-steps }

Para que el agent actúe en lugar de solo proponer, vincula una [conexión MCP de GitHub](../mcp.md#development) o los permisos de escritura de la GitHub App, y decide quién revisa una etiqueta o un comentario antes de publicarse. Las herramientas MCP no tienen aprobación propia por herramienta, así que esa revisión tiene que venir de una persona que observa el run o del modo del chat **Ask about everything**, igual que al [convertir notas de reunión en tareas](meeting-to-tasks.md). Un trigger siempre se ejecuta como [el miembro que lo creó](../concepts.md#it-runs-as-a-person), así que da ese papel a quien deba responder de un trigger que falle, no a quien lo configuró por casualidad.
