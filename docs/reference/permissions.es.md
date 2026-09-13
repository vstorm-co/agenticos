---
source_sha: 35041987d0af
---

# El catálogo de permisos { #the-permission-catalog }

Todo lo que se le puede permitir a un miembro, hasta dónde llega cada permiso y
cómo se componen los roles integrados a partir de ellos.

Consulta [Permisos](../permissions.md) para la explicación y para ver cómo se
combinan las cuatro capas; esta página es la referencia generada y por eso se
queda en inglés — se lee de los docstrings del código fuente en el momento del
build.

::: app.core.permissions

## Resolver el acceso a una sola fila { #resolving-access-to-one-row }

No se genera. `app/services/` es un paquete de espacio de nombres implícito - no
tiene `__init__.py` - así que el recolector estático no puede entrar en él, y
una página de referencia que omitiera en silencio la mitad de sus símbolos sería
peor que una que dice dónde mirar.

La fórmula y cada rechazo que produce están documentados en
[Permisos](../permissions.md#how-the-layers-combine). El código fuente es
[`app/services/access.py`](https://github.com/vstorm-co/agenticos/blob/main/backend/app/services/access.py),
que lleva el razonamiento en sus docstrings.
