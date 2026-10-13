---
source_sha: "7cb876b5ef26"
---

<!-- source_sha: 7cb876b5ef26 -->

# Contribuir a AgenticOS

[English](CONTRIBUTING.md) · [Polski](CONTRIBUTING.pl.md) · [Deutsch](CONTRIBUTING.de.md) · **Español**

Gracias por pasarte. Este documento va corto de ceremonia y es concreto sobre lo
que de verdad hace que se rechace una pull request.

## El listón

El código entra cuando un maintainer lo fusionaría sin cambios. En concreto:

- **Completamente tipado.** Nada de `Any`, nada de `# type: ignore`, ningún
  `except:` que haga desaparecer un error. Modela con tipos precisos en lugar de
  con dicts sueltos.
- **Los errores se oyen.** Falla con un mensaje claro; nunca te tragues una
  excepción ni tapes un bug con un fallback. Una respuesta equivocada en
  silencio es peor que un cuelgue.
- **Nada de peso muerto.** Ni abstracciones especulativas, ni parámetros sin
  usar, ni código comentado, ni ramas "por si acaso".
- **Los comentarios explican el *por qué*.** Lo que hace el código se ve; por qué
  lo hace así, no, y eso es lo que necesita quien lo lea dentro de seis meses.
- **Ajústate al código de alrededor.** Sus modismos ganan a la preferencia
  personal.

## Puesta en marcha

```bash
make dev            # postgres, redis, api, worker, frontend
make seed           # an organization, an owner, a default model profile
```

El backend necesita una `VAULT_MASTER_KEY`. Sin ella recurre a `SECRET_KEY`, lo
cual está bien en local y se rechaza en producción.

## Ejecutar los tests

Mira [`CLAUDE.md`](CLAUDE.md#testing) para el cuadro completo. La versión corta:

```bash
make test               # backend, with the coverage gate
make test-frontend      # vitest unit + integration, no coverage
make test-frontend-cov  # the same, plus the gate CI applies
make test-e2e           # playwright
make check              # every CI job except e2e — run this before a pull request
```

**`make test-frontend` no mide cobertura alguna, y la única puerta del frontend
es un umbral de cobertura.** Es el bucle; `make check` es la respuesta.

**La capa de plataforma se mantiene al 100% de cobertura** y la CI lo hace
cumplir. Eso quiere decir `app/agents/`, el catálogo de permisos, el vault y los
servicios construidos encima. Los subsistemas heredados de la plantilla (el
pipeline de RAG, los conectores, los adaptadores de canal) se informan pero no
son una puerta para el build — someter al mismo listón un código que no
diseñamos nosotros significaría tests llenos de mocks que compran un número en
lugar de confianza.

Si añades un archivo a la capa de plataforma, necesita tests que fallarían si
cambiara el comportamiento. Un test que solo recorre el camino feliz no cuenta.

## La arquitectura, en un párrafo

Un agent es **datos**, no código. `AgentSpec` es el contrato: el Builder lo
edita, la base de datos lo versiona, `app/agents/factory.py` lo instancia y un
cliente puede confirmarlo como YAML en su propio repositorio git. Todo aquello
con lo que se ensambla un agent es una **capability** — búsqueda en el
conocimiento, investigación en la web, un guardián del budget, un conjunto de
skills — declarada en código con metadatos y compuesta por configuración. La
configuración nunca puede alcanzar más que lo que el código registró.

De ahí se siguen dos reglas, y la mayoría de los comentarios de revisión vuelven
a ellas:

**Los ids son permanentes.** El id de una capability aparece en los specs
guardados y en los repositorios de los clientes. Renombra la clase de Python sin
miedo; cambiar el id es un cambio incompatible.

**Valida al publicar, no en tiempo de ejecución.** Un agent roto debe rechazarse
mientras alguien mira un formulario, no a las 3 de la madrugada en una
conversación con un cliente.

## Añadir una capability

Una carpeta bajo `app/agents/capabilities/`, con la misma forma que las demás:

```
app/agents/capabilities/your_thing/
    __init__.py        # registration + public exports
    _capability.py     # the AbstractCapability subclass
    _toolset.py        # its tools, if it has any
    README.md          # the decisions behind it, not a description of the code
```

Regístrala en el `load_builtins()` de `_registry.py` o, en lo que al Builder
respecta, no existe — ese acoplamiento es deliberado.

Si la capability puede actuar sobre el mundo exterior, márcala con
`side_effecting=True`. Eso hace que la aprobación humana sea lo predeterminado, y
olvidarse del flag es la forma en que un agent acaba enviando correo sin
supervisión.

## Pull requests

- Un asunto por PR. Una refactorización y una funcionalidad en el mismo diff se
  revisan como ninguna de las dos.
- Los bugs se entregan con un test de regresión que falla sin el arreglo.
- Cuenta en la descripción qué decidiste y por qué. El qué ya lo enseña el
  código.

## Seguridad

No abras una issue pública por una vulnerabilidad. Mira
[`SECURITY.md`](SECURITY.md).

## Licencia

Al contribuir aceptas que tu trabajo queda licenciado bajo la Apache License
2.0, los mismos términos que el resto de este repositorio. No hay CLA.
