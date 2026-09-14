---
source_sha: "e2011b4848b5"
---

# La puesta en marcha { #rolling-it-out }

Esta página es para quien responde por la decisión y no por la instalación: qué
cambia en una empresa que ejecuta esto, quién hace qué, cuánto cuesta y las tres
formas en que suele salir mal.

Nada de lo que hay aquí necesita un terminal. [La instalación](install.md) es la
otra mitad.

## Qué reemplaza { #what-it-replaces }

No a una persona. **A un backlog.**

Toda empresa tiene una cola de pequeñas automatizaciones que nunca se construyen:
la respuesta que contesta la misma pregunta del cliente, el resumen semanal que
alguien monta a mano, el formulario que se rellena desde un correo, la pregunta
interna que se responde interrumpiendo a la única persona que lo sabe.

Cada una es demasiado pequeña para justificar un proyecto y hay cuarenta. Se
quedan sin hacer porque la única manera de construir una ha sido un desarrollador,
un repositorio y una release — y el tiempo de un desarrollador se aprovecha mejor
en el producto.

AgenticOS convierte cada una de ellas en un documento que alguien escribe, en
lugar de software que alguien despacha.

## Quién hace qué { #who-does-what }

Tres roles, y el reparto importa más que la herramienta.

| | Quién es | De qué responde |
|---|---|---|
| **El builder** | La persona que sabe la respuesta — responsable de soporte, jefe de operaciones, analista | Escribe las instrucciones del agent, elige qué puede hacer, le señala los documentos correctos, lo prueba, lo publica |
| **El owner** | Quien responde por el gasto y por el comportamiento | Fija budgets, decide qué acciones necesitan aprobación humana, lee el registro de auditoría |
| **El ingeniero** | Una persona, a tiempo parcial, pasada la primera semana | Ejecuta la instalación, conecta los sistemas, añade una capability si de verdad hace falta algo nuevo |

El sentido del reparto es que el builder no dependa del ingeniero. Si todo cambio
en lo que dice un agent tiene que pasar por la persona con acceso de commit, has
comprado una versión más lenta de lo que ya tenías.

!!! info "La carga del ingeniero baja después de la puesta a punto"

    Conectar un sistema es [un servidor MCP por URL](mcp.md), no un connector que
    alguien escribe. Cambiar el comportamiento es una edición y una publicación,
    no una release. La mayoría de las semanas el coste de ingeniería es cero.

## Unos primeros noventa días realistas { #a-realistic-first-ninety-days }

| | | Qué aspecto tiene "hecho" |
|---|---|---|
| **Semana 1** | Instalar, conectar un provider de modelos, invitar a tres personas | Un agent responde una pregunta real a partir de un documento real |
| **Semanas 2–4** | Un agent, un equipo, una tarea repetida. El budget fijado bajo a propósito | El equipo lo usa sin que nadie se lo pida |
| **Semanas 5–8** | Ponlo donde ya ocurre el trabajo — [Slack, un widget, routines dirigidas por correo](channels.md) | Alguien de fuera del equipo piloto lo usa sin formación |
| **Semanas 9–12** | Segundo y tercer agent, construidos por otra persona | Alguien que no es ingeniero ha publicado un agent de principio a fin |

El hito que importa es el último. **Un agent demuestra la tecnología; el segundo
agent, construido por otra persona, demuestra el modelo de trabajo.** Si todos
los agents siguen saliendo de la misma persona, tienes una herramienta, no una
plataforma.

## Cuánto cuesta { #what-it-costs }

Tres partidas, y solo una de ellas sorprende.

- **Infraestructura.** Postgres, Redis y un host de contenedores. Una VM pequeña
  aguanta un piloto; esta es la partida más barata y sigue siéndolo.
- **Uso del modelo.** Medido por run y por agent, y visible antes de la factura.
  Esta es la partida a vigilar, y para la que existen los
  [budgets](governance.md#budgets) — comprobados *antes* de cada petición al
  modelo, de modo que un agent que se pasa del budget se detiene en lugar de
  gastar de más.
- **Personas.** Un ingeniero para la puesta a punto, luego a tiempo parcial. Un
  builder por equipo, como parte de su trabajo actual y no como uno nuevo.

No hay licencia por puesto, porque no hay licencia: es Apache-2.0 y lo ejecutas
tú. Eso cambia la forma de la decisión — añadir el agent número once y el usuario
número cien no cuesta nada más que los tokens que consuman.

!!! tip "Fija el primer budget más bajo de lo que crees"

    Un budget que detiene un run enseña mucho mejor que una factura. Empieza por
    una cifra que se vaya a alcanzar, mira adónde se va y luego súbela
    deliberadamente. [Elegir un modelo](choosing-models.md) cubre qué dispara de
    verdad la factura.

## Qué preguntará tu revisión de seguridad { #what-your-security-review-will-ask }

Las preguntas llegan en un orden previsible, y las respuestas son la razón por la
que se eligió esta arquitectura.

| Preguntan | La respuesta |
|---|---|
| ¿Adónde van nuestros datos? | A tu Postgres, en tu infraestructura. Nada llama a casa. Las únicas llamadas salientes van a los providers de modelos que hayas configurado — y [ninguna en absoluto](choosing-models.md#closed-models-or-open-weights) si ejecutas el modelo tú mismo |
| ¿Quién puede ver qué? | [Tres capas](permissions.md): un admin del despliegue, un rol de organización y grants por recurso. Un control que alguien no puede usar no se renderiza, no se renderiza y luego se rechaza |
| ¿Qué impide que un agent haga daño? | Nada con efectos secundarios se ejecuta sin [aprobación](governance.md#approvals) cuando la exiges, y una aprobación se decide exactamente una vez |
| ¿Podemos demostrar qué ocurrió? | Cada run, cada aprobación, cada rotación de un secreto está en el [registro de auditoría](governance.md#audit) — incluidos los runs que fallaron |
| ¿Dónde están las credenciales? | En [un único vault](secrets.md), sellado por organización. Ninguna respuesta de la API, línea de log ni entrada de auditoría lleva jamás una clave en claro |
| ¿Cumple el RGPD? | Lo cumple un despliegue, o no lo cumple; el código se puede desplegar dentro de uno que sí. [Protección de datos](data-protection.md) asigna cada almacén, cada destino y cada control a un mecanismo, una prueba o una incidencia abierta, y enumera lo que el propio despliegue tiene que decidir |
| ¿Podemos leer el código? | Sí. Ahí suele terminar la conversación |
| ¿De qué está hecho, y bajo qué licencias? | Apache-2.0, encima de unos quinientos paquetes que son casi todos MIT, Apache-2.0 o BSD. [Cada uno está listado con su evidencia](licenses.md), y los hallazgos todavía abiertos aparecen primero en lugar de diluirse en la media. Un componente, el parser de PDF, es AGPL-3.0: un despliegue que modifique la plataforma y la sirva por red les debe a sus usuarios el código fuente modificado, y [esa decisión tiene su propia sección](licenses.md#the-agpl-component) |

## Tres formas en que esto sale mal { #three-ways-this-goes-wrong }

Cada una se ha visto; cada una es evitable.

**Una sola persona construye todos los agents.** La plataforma se convierte en la
cola de esa persona y vuelves al punto de partida. Solución: haz que el segundo
agent sea de otra persona, y siéntate con ella mientras lo construye.

**El primer agent es demasiado ambicioso.** Un agent que toca cuatro sistemas y
toma decisiones falla de una manera que nadie puede depurar, y el fallo se
recuerda como "la IA no funciona aquí". Solución: el primer agent responde
preguntas a partir de documentos. Es aburrido, funciona, y se gana al segundo.

**Nadie fijó un budget ni una aprobación.** El run que sorprende a alguien es el
que no tenía tope ni puerta, y cuesta más confianza que dinero. Solución: fija
ambos el primer día, en cada agent, antes de que nadie más tenga acceso.

## Qué medir { #what-to-measure }

Resístete a contar conversaciones. Mide las cuatro cosas que deciden si esto
mereció la pena:

| | Por qué es la cifra correcta |
|---|---|
| **Preguntas respondidas sin una persona** | El resultado real. Todo lo demás es un indicador indirecto de esto |
| **Coste por tarea resuelta** | Baja a medida que afinas el retrieval y bajas un escalón de modelo — y es visible por run, no por mes |
| **Cuántas personas han publicado un agent** | La cifra de adopción que predice si esto sobrevive a quien lo impulsó |
| **Aprobaciones en espera** | Una cola que crece significa que la puerta está en la acción equivocada, o que aún no se confía en el agent. Vale la pena saber ambas cosas pronto |

## Conseguir ayuda { #getting-help }

Puedes ejecutar esto enteramente por tu cuenta. Es Apache-2.0, la documentación
es la historia completa y no un aperitivo, y nada de lo que hay aquí está detrás
de un contrato de soporte.

Dos sitios donde preguntar cuando algo no está cubierto:
[las issues y discussions de GitHub](https://github.com/vstorm-co/agenticos) del
proyecto, y [Recursos](resources/index.md) para las guías de quien contribuye.

**[Vstorm](https://vstorm.co) construye AgenticOS, y también lo despliega.** Eso
vale la pena saberlo si el trabajo que tienes delante es uno de estos:

| | |
|---|---|
| **Llevarlo a producción dentro de tu infraestructura** | Tu nube, tu centro de datos o aislado de la red, conectado a los sistemas que ya ejecutas |
| **Poner en pie modelos locales** | Para que la inferencia nunca salga del edificio — el hardware, el runtime y los perfiles que apuntan a él |
| **Adaptar la plataforma a un proceso concreto** | Una capability que nadie ha escrito, una vía de ingesta para la forma de tus documentos, un channel que usas tú y nadie más |
| **Construir los primeros agents con tu equipo** | De forma integrada, para que el segundo sea suyo y no nuestro |

Nada de eso es una licencia — la plataforma es el mismo open source en cualquier
caso, y un despliegue que hizo otra persona sigue siendo tuyo para leerlo,
cambiarlo y mantenerlo en marcha.

[Habla con nosotros →](https://vstorm.co/contact-us/)

## Resumen { #recap }

- Reemplaza **un backlog de pequeñas automatizaciones**, no a una persona.
- El reparto que hace que funcione: **el builder no depende del ingeniero.**
- El hito que importa es el **segundo agent, construido por otra persona.**
- **Sin licencia por puesto** — el agent número once solo cuesta los tokens que
  consume.
- Fija **un budget y una aprobación el primer día**, en cada agent, antes de que
  nadie más tenga acceso.

[Instálalo →](install.md) · [Construye el primer agent →](first-agent.md) ·
[Qué rechaza →](about/index.md)
