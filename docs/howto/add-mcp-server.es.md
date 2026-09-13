---
source_sha: 34c34d991836
---

# Añade un servidor al catálogo MCP { #add-a-server-to-the-mcp-catalog }

El [catálogo](../mcp.md#the-catalog) es lo que hace útil el selector de conexiones
en lugar de un campo de URL en blanco. Añadir una entrada son datos, no código:
un objeto en `backend/app/core/catalog/mcp_servers.json`.

!!! tip "No necesitas hacer esto para usar un servidor"

    Cualquier servidor MCP alcanzable por URL se conecta con la entrada *Custom
    server*, y sus herramientas se introspeccionan al conectar. El catálogo le
    ahorra a alguien buscar una URL y un párrafo de configuración a ciegas; no es
    una puerta.

## La entrada { #the-entry }

```json
{
  "key": "acme",
  "name": "Acme",
  "description": "Read and update work orders.",
  "category": "operations",
  "auth": "token",
  "url": "https://mcp.acme.com/mcp",
  "docs_url": "https://docs.acme.com/mcp",
  "token_hint": "A read-only service token from Settings → API, scoped to work orders.",
  "icon": "acme"
}
```

| Campo | |
|---|---|
| `key` | Id estable. Las conexiones lo guardan, así que trátalo como se tratan los ids de capability: renombra cuanto quieras, recodifica nunca |
| `name` | Lo que muestra el selector |
| `description` | Una frase, en imperativo, sobre lo que hacen las *herramientas* |
| `category` | Agrupa el selector. Reutiliza una existente salvo que el servidor no tenga de verdad dónde encajar |
| `auth` | `none`, `token` u `oauth` |
| `url` | Vacío cuando el cliente aloja el servidor o el fabricante emite un endpoint por cuenta — el formulario la pide entonces |
| `docs_url` | Dónde documenta el fabricante su servidor |
| `token_hint` | Solo para `token`. Ver más abajo |
| `icon` | Un nombre de `BrandIcon`, o vacío |

!!! note "Validado al importar"

    El archivo se comprueba contra `CatalogEntry` cuando se carga el módulo, así
    que una entrada mal formada impide que la aplicación arranque en lugar de
    desaparecer en silencio del selector.

## Escribe la pista del token { #write-the-token-hint }

!!! important "Este es el campo que justifica la entrada"

    Las instrucciones genéricas son el principal motivo de que falle la
    configuración de un token, y "un token de API" no le dice a nadie dónde
    pulsar.

Di de dónde sale el token y qué tiene que poder hacer:

> Un token de acceso personal de grano fino con acceso de lectura a los
> repositorios que el agent deba ver.

Déjalo vacío para `oauth` y `none` — no hay nada que pegar.

## Iconos { #icons }

`icon` nombra una marca. Si ningún conjunto de iconos compilado la lleva, deja un
SVG en `backend/app/core/catalog/icons/<name>.svg` y lo sirve
`GET /catalog/icons`, dibujándose para cualquier entrada del catálogo o provider
cuyo id coincida.

Los colores del propio archivo se **ignoran** — se renderiza como una silueta con
`currentColor`, así que el registro monocromo de la consola se mantiene por
construcción. Consulta `icons/README.md` para el contrato.

Un `icon` vacío recurre a un monograma. Eso es un aspecto deliberado y no uno que
falta: todo conjunto de iconos es finito y este catálogo no lo es.

## Antes de hacer commit { #before-you-commit-it }

!!! warning "Una entrada es una promesa"

    De que alguien miró el servidor, de que el flujo de autenticación funciona, de
    que la descripción es honesta. Es la razón entera de que esta sea una lista
    mantenida a mano y no un espejo del registro público — así que haz que la
    promesa sea cierta:

1. Conéctalo en un despliegue en marcha.
2. Ejecuta `POST /api/v1/mcp-connections/{id}/test` (el botón **Test**) y lee la
   lista de herramientas con la que responde. Si las herramientas no encajan con
   tu `description`, arregla la descripción.
3. Para `oauth`, completa el flujo de principio a fin. El descubrimiento, el
   registro dinámico y el intercambio del token fallan cada uno de forma
   distinta, y un servidor que se atasca en el segundo paso se ve en la interfaz
   igual que uno que simplemente va lento.
4. Comprueba que el nombre no choca con el
   [prefijo de herramientas](../mcp.md#name-collisions) de una entrada existente.

## Qué no hace falta cambiar { #what-does-not-need-changing }

Nada más. El selector se dibuja a partir del catálogo, y el servicio de conexión,
la sonda, la lista de permitidos y el prefijado son todos genéricos. Una entrada
añadida aquí está en el producto en el siguiente reinicio.
