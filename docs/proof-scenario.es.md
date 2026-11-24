---
source_sha: "f0e7bf18f180"
---

# Escenario de prueba { #proof-scenario }

Un cambio no está terminado hasta que el agente reproduce el fallo, lo ve
pasar y puede mostrar la evidencia. Unas pruebas simuladas en verde no
prueban que la experiencia del usuario funcione. La prueba es la evidencia
observada en la sesión - salida de un comando, una reproducción, una captura
de pantalla - para cada cambio del diff.

Esto es el principio «Prueba, no diffs» del `full-send` de Theo en tstack,
como capacidad. El procedimiento está en la skill `proof-scenario`
(`backend/app/core/catalog/skills/proof-scenario/SKILL.md`); esta página dice
qué hace la capacidad con la evidencia.

## Cómo funciona un escenario { #how-a-scenario-works }

El agente registra un escenario con `proof_scenario_record` **antes de
arreglar nada**: qué reproduce, cómo se ejecuta - un comando, una
reproducción o un flujo de interfaz -, qué archivos del diff cubre y el
intento anterior a la corrección que muestra el fallo. Tras la corrección,
ejecuta la **misma** reproducción de nuevo y registra el intento posterior
con lo que realmente vio.

Un escenario solo está probado cuando la misma reproducción falló antes de la
corrección y pasó después, ambas veces con evidencia observada. Una mitad
sola no prueba nada: un fallo sin una repetición que pase es un informe de
error, y un éxito sin un intento previo que fallara nunca mostró que la
corrección arreglara nada. Un intento que se ejecutó pero no probó nada - el
comando falló antes de llegar al comportamiento, la captura mostró la
pantalla equivocada - es `inconclusive` y no cuenta como ninguna de las dos
mitades.

Una ejecución de pruebas unitarias se registra cuando el agente la entrega,
con el tipo de evidencia `unit_test`, y nunca cuenta para la cobertura. Para
cambios de interfaz, la evidencia es una captura o un flujo observado -
ejecutar la app y mirar -, no una prueba de componente.

## El veredicto de cobertura { #the-coverage-verdict }

Antes de pedir una fusión, el agente llama a `proof_scenario_verdict` con los
archivos cambiados, si las comprobaciones requeridas están en verde en el
head actual, cuántas siguen pendientes y cuántos hallazgos de revisión siguen
abiertos. El veredicto informa qué archivos cambiados tienen prueba
observada y cuáles no:

| Veredicto | Significado |
|---|---|
| `proven` | Cada archivo cambiado está cubierto por un escenario probado. |
| `partial` | Algunos archivos están cubiertos; el informe nombra el resto. |
| `unproven` | Ningún archivo está cubierto. |
| `no_scenarios` | No se registró nada en absoluto. |

La misma llamada informa de la mitad de prueba de la puerta de fusión:
prueba, comprobaciones y hallazgos. Las tres deben cumplirse para que la
puerta se lea como lista - una prueba que cubre el diff, comprobaciones
requeridas en verde sin pendientes y ningún hallazgo de revisión abierto.
Lista no fusiona nada: fusionar necesita la petición explícita del usuario,
en el head actual, sin que ninguna revisión humana siga pidiendo cambios y
con la rama actualizada y fusionable. Nunca usar `--admin` ni ningún otro
atajo.

Cuando no se encuentra forma de probar un cambio, el agente lo dice y
pregunta al usuario, en lugar de afirmar una prueba que no tiene. Un cambio
sin probar presentado como sin probar es trabajo honesto; un cambio sin
probar presentado como probado no lo es.

## Dónde vive la prueba { #where-the-proof-lives }

Los escenarios viven en el manifiesto de la ejecución, junto a las peticiones
y las correcciones del revisor, y el cajón de la ejecución muestra cada
escenario con sus intentos y si está probado. No hay migración: los
escenarios son JSONB en el manifiesto, no una tabla. El manifiesto de una
ejecución guarda como mucho veinte escenarios y seis intentos por escenario,
y la salida observada se recorta antes de guardarse.

## Lo que deliberadamente no hace { #what-it-deliberately-does-not-do }

- **Ni fusionar, ni comentar, ni actuar sobre el cambio.** Solo prueba e
  informe.
- **Ninguna prueba a partir de pruebas unitarias.** Un cambio cuya única
  evidencia es una suite de pruebas en verde se informa como no probado.
- **Ninguna prueba inventada.** Lo que el agente no vio, no lo registró.
- **No ejecuta nada.** La capacidad nunca ejecuta un comando por sí misma:
  el agente ejecuta la reproducción y entrega lo que observó.
