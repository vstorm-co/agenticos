---
source_sha: "f5fcd6aff7b4"
---

# Archivos de contexto { #context-files }

Un **archivo de contexto** es un trozo de conocimiento permanente escrito una vez
y vinculado a muchos agents: un glosario, una voz de marca, una matriz de
escalado, la lista de los productos que realmente vendes.

Es la respuesta a un problema con el que toda empresa se topa en su tercer agent
— los mismos tres párrafos pegados en tres juegos de instrucciones, y luego
editados en uno solo de ellos.

## Dónde queda, entre los skills y el conocimiento { #where-it-sits-between-skills-and-knowledge }

Tres cosas ponen texto delante de un modelo, y elegir mal es la causa habitual de
un agent que o ignora lo que se le dijo o no lee nada en absoluto.

| | Contiene | El modelo lo ve |
|---|---|---|
| **Archivo de contexto** | Hechos permanentes, pequeños y estables — un glosario, una guía de tono, un organigrama | Siempre, o bajo demanda — tú eliges |
| **[Skill](skills.md)** | Un procedimiento para un tipo de tarea — cómo tratar una petición de reembolso | Cuando el modelo decide que esa tarea es lo que está ocurriendo |
| **[Colección de conocimiento](file-processing.md)** | Un corpus demasiado grande para leerlo — cada documento de política, cada ticket | Solo los fragmentos que devuelve una búsqueda |

La regla práctica: **si es corto y siempre relevante, es un archivo de contexto.
Si es largo, es conocimiento. Si es un procedimiento, es un skill.**

## Dos modos, y la diferencia es el coste { #two-modes-and-the-difference-is-cost }

Todo archivo de contexto lleva un modo, y ese modo decide cómo llega el archivo
al modelo.

=== "`inject` — siempre presente"

    El cuerpo se empalma literalmente en las instrucciones del agent. El modelo
    siempre lo conoce, sin decidir mirarlo y sin ninguna llamada a herramienta.

    Úsalo para lo que el agent nunca debe equivocarse: cómo se llaman tus
    productos, a quién escalar, cómo referirse a la empresa.

    **Se lee en absolutamente todos los turnos**, así que forma parte del coste
    de cada mensaje. Mantén cortos los archivos inyectados.

=== "`link` — leído bajo demanda"

    El cuerpo se queda fuera del prompt y se expone a través de una herramienta. El
    modelo lo lee solo cuando decide que el archivo es relevante, eligiendo a
    partir del nombre y de una descripción de una línea que escribes tú.

    Úsalo para material de consulta que importa a veces: una política que se
    necesita rara vez, una variación regional, una lista larga.

    No cuesta nada en los turnos que no lo necesitan, y nada en absoluto si el
    modelo nunca lo mira — que es también el riesgo.

!!! tip "Escribe la descripción para un modelo, no para una persona"

    Un archivo vinculado se elige únicamente a partir de su nombre y su
    descripción. «Política de devoluciones» le dice menos a un modelo que «cuándo
    un cliente puede devolver un artículo, los plazos y las tres excepciones» — y
    la diferencia está en si el archivo llega a abrirse alguna vez.

## Vincularlos a un agent { #attaching-them-to-an-agent }

Los archivos de contexto son de una organización, no de un agent. Escribes uno, y
se vincula a él cualquier número de agents.

Activa la capability **Context** en el agent y luego vincula los archivos que
debería tener. Editar el archivo después cambia lo que sabe cada agent vinculado
**en su siguiente run** — sin republicar, en ninguno de ellos.

Esa es toda la idea, y también aquello con lo que hay que tener cuidado: un
cambio en un archivo inyectado es un cambio en cada agent que lo lleva. Trátalo
como el texto compartido y portante que es.

La capability tiene un ajuste que vale la pena conocer. **Desactivar** la herramienta de
lectura significa que solo los archivos inyectados llegan al modelo y que no se
lee nada bajo demanda — una elección razonable cuando quieres que las entradas de
un agent sean del todo predecibles.

## Acceso { #access }

Un archivo de contexto tiene un propietario y una visibilidad, como cualquier otro
recurso de aquí, y `context:view` regula la lectura del catálogo. Un archivo que a
alguien no se le ha concedido es un archivo que no puede vincular, y eso lo
deciden [las mismas tres capas](permissions.md) que en todo lo demás.

Lo que sea de verdad secreto no va en uno — un archivo de contexto es texto que un
agent lee en voz alta cuando se le hace la pregunta adecuada. Las credenciales van
en [el vault](secrets.md).

## Resumen { #recap }

- Un archivo de contexto es **conocimiento permanente escrito una vez y vinculado
  a muchos agents**.
- **`inject`** está siempre en el prompt y cuesta en cada turno; **`link`** se lee
  bajo demanda y no cuesta nada hasta que ocurre.
- Un archivo vinculado se elige por su **descripción**, así que escríbela para el
  modelo.
- Editar un archivo actualiza **cada agent vinculado en su siguiente run**, sin
  republicar nada.
- Corto y siempre relevante → contexto. Largo → [conocimiento](file-processing.md).
  Un procedimiento → [un skill](skills.md).
