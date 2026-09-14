---
source_sha: "d3a6a1847ec0"
---

# El código de la consola { #the-consoles-code }

[Arquitectura](architecture.md) es el backend. Esta es la otra mitad: la
aplicación Next.js en `frontend/`, para quien está a punto de tocarla.

**Stack.** Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind ·
`next-intl` · TanStack Query · Zustand · vitest y Testing Library ·
Playwright. Gestor de paquetes y runner: **bun**.

## Dónde vive cada cosa { #where-things-live }

| Ruta | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | El producto. Las rutas llevan **prefijo de locale** |
| `src/app/api/…` | Route handlers que hacen de proxy hacia el backend |
| `src/lib/` | Clientes de API tipados, `query-keys.ts` y los registries de más abajo |
| `src/hooks/` | Uno por recurso — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, uno por asunto |
| `src/components/<domain>/` | La UI por dominio; los primitivos en `ui/`, los estados vacíos y de error en `states/` |

Los Server Components son lo predeterminado. `"use client"` es para state,
effects y handlers, no por costumbre.

## El navegador nunca llama al backend { #the-browser-never-calls-the-backend }

Cada petición va a `/api/*` de esta app, que la reenvía a FastAPI con el access
token tomado de una **cookie HttpOnly**. Eso es lo que mantiene el token fuera
del JavaScript y la URL del backend fuera del bundle del cliente.

Lo hace un único reenviador — `src/lib/platform-proxy.ts` — en lugar de un
archivo de ruta hecho a mano por endpoint que repite las mismas doce líneas.

!!! warning "Una respuesta sin `Cache-Control` no es una respuesta que nadie cachee"

    El proxy estampa `no-store` en todo lo que el backend dejó sin marcar. Cada
    respuesta de aquí depende de una cookie, de un conjunto de permisos y de la
    cabecera de organización, y una lista que se vuelve a pedir tras una
    escritura tiene que llegar al servidor.

    Un archivo de ruta hecho a mano debe la misma cabecera — el proxy es el
    único sitio que la aplica por ti.

## Los datos, y dónde vive el state { #data-and-where-state-lives }

**Todo acceso a la API pasa por un cliente de `src/lib/` y se consume a través
de un hook.** Nada de `fetch` en un componente.

Los datos del servidor viven en la capa de queries; **los stores guardan solo
state de UI y efímero**. Registra cada query key en `query-keys.ts` para que la
invalidación tras una escritura se mantenga consistente.

## Los permisos son una decisión de renderizado { #permissions-are-a-rendering-decision }

`use-permissions.ts` da el conjunto de permisos efectivo para la organización
activa. **Un control que quien llama no puede usar no se renderiza** — no se
renderiza, en vez de renderizarse y devolver 403.

Dos trampas, y las dos ya han llegado a producción aquí:

- **Qué roles ofrece un selector es aritmética, no una lista.**
  `assignableRoles` refleja la regla del servidor sobre el catálogo de permisos:
  un rol solo se ofrece cuando el de quien llama lo supera estrictamente. Un
  "todos los roles menos owner" cableado a mano es lo que le ofreció a un Admin
  la opción Admin y devolvió 403 una vez tecleado el correo.
- **Una página que nombra una organización en su URL *es* esa organización.** El
  cliente de API estampa `X-Organization-Id` desde la organización *activa*, así
  que una página que actúa sobre la organización de su ruta mientras lee los
  permisos de la activa decide sobre los miembros de Acme según tu rol en
  Globex. La adopción vive en `ActiveOrgGuard`, una sola vez.

## Cada string visible para el usuario pasa por `next-intl` { #every-user-facing-string-goes-through-next-intl }

`make lint` lo impone en las dos direcciones: un string legible metido en un
componente falla, y también falla una clave que el catálogo guarda y que ningún
componente lee.

Tres reglas con las que la gente tropieza:

- **Un recuento es un `plural` de ICU, nunca un ternario.**
  `{n} file{n === 1 ? "" : "s"}` es una frase que solo el inglés construye así.
- **Un sustantivo con el que concuerda la frase no es un parámetro.**
  `{matched} of {total} {noun}` renderiza `3 of 40 skills` en polaco. El
  sustantivo va dentro del `plural` o del `select`.
- **El catálogo guarda copy, y solo copy.** Un falso positivo se responde con un
  `i18n-exempt` y su motivo; nunca con una clave. Responder a uno moviendo una
  lista de clases de Tailwind a `en.json` es la forma en que traducir un string
  una vez dejó a un componente sin sus estilos.

El inglés es la lengua de origen y se fusiona bajo cada locale, así que una
traducción que falta renderiza inglés en lugar de la clave.

!!! info "Los nombres propios del producto siguen en inglés en cada locale"

    agent, spec, capability, skill, embed, budget, run, prompt, provider, token,
    vault, workspace, sandbox, MCP. Nombran cosas que un cliente también
    encuentra en la documentación, en la API y en el YAML exportado — traducirlos
    en la UI y en ningún otro sitio crea dos vocabularios para un mismo producto.
    Flexiónalos, no los sustituyas.

## Cuatro registries, y ninguna segunda fuente { #four-registries-and-no-second-source }

Cada uno de ellos es una tabla que leen varias partes de la UI. Añadir a la
tabla es el cambio entero; añadir una segunda fuente es el bug.

| | Guarda | Se añade con |
|---|---|---|
| `lib/tool-catalog.ts` | El icono, el rótulo mientras corre, el nombre al terminar y el renderizador de cada tool que registra el backend | Una fila indexada por el id de tool de la capability. Un test de backend compara las dos en ambas direcciones |
| `lib/brand-glyphs.generated.ts` | Cada marca de servicio, de connector y de provider, como datos de path en bruto | Una fila en `scripts/gen-brand-icons.ts`, y después `bun run gen:brand-icons`. Nunca un import de un paquete de iconos |
| `lib/dashboard/registry.ts` | Los widgets del dashboard y el permiso al que está sujeto cada uno | Cinco ediciones, enumeradas más abajo en la página |
| `lib/dialog-sizes.ts` | Un token de anchura y un token de forma por diálogo | Eligiendo un token, nunca una altura a medida |

## Dos cosas que debe una superficie nueva { #two-things-a-new-surface-owes }

Las dos son registries con el mismo modo de fallo: una página añadida en
cualquier otro sitio simplemente no está, nada falla, y la funcionalidad se
publica invisible.

**Una parada del recorrido.** `lib/onboarding/tour.ts` es el recorrido pasivo
que reproduce el "?" de una página, y `flows.ts` es la creación guiada que
ofrece al final. Una página sin parada no renderiza **ningún "?"** — así que una
página nueva cuya cabecera no tiene botón de ayuda no se ha registrado. Sujeta
el paso al permiso que lleva su control, márcalo `optional` cuando el control
necesita que existan datos, y áncralo en algo acotado.

**Un widget del dashboard**, si la funcionalidad produce un estado que alguien
querría ver de un vistazo. Cinco ediciones: el id y la definición en
`dashboard/registry.ts`, el componente en `components/dashboard/widgets/`, una
colocación en `layouts.ts`, el id replicado en
`backend/app/schemas/dashboard_layout.py` — un test falla cuando esos dos se
desvían — y el copy tanto en `en.json` como en `pl.json`.

## Verificar { #verify }

Desde `frontend/`. En la raíz del repositorio vitest no encuentra configuración,
informa de unos 164 fallos fantasma y deja un directorio de caché perdido.

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx   # while writing
```

Una vez, antes de hacer push — desde la raíz del repositorio:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

!!! danger "`test:coverage`, no `test:run`"

    El job que ejecuta CI mide la cobertura y falla por debajo del 100 % de
    líneas, sentencias y funciones, o del 97,5 % de ramas. Una suite en la que
    pasan todos los tests puede estar roja igualmente, y lo ha estado.

Borrar una rama muerta es más fácil que cubrirla: un `?? ""` detrás de una
comprobación que ya demostró el valor es de los que el gate hace bien en
señalar.

**Un spec que agota su tiempo suele ser la máquina.** `testTimeout` es 15 s y
`asyncUtilTimeout` 5 s, los dos medidos y no adivinados. Ninguno de los dos es
razón para conservar un spec que monta más de lo que leen sus assertions.

## Recapitulación { #recap }

- El navegador habla con **`/api/*` de esta app**, nunca con FastAPI — un único
  reenviador, y estampa `no-store`.
- Los datos del servidor viven en la **capa de queries**; los stores guardan
  solo state de UI.
- Un control que quien llama no puede usar **no se renderiza**, y los selectores
  de rol son **calculados, no listados**.
- El copy pasa por **`next-intl`**, los recuentos son plurales de ICU, y el
  catálogo guarda copy y solo copy.
- Una superficie nueva debe una **parada del recorrido**, y un widget si tiene
  estado legible de un vistazo — las dos son registries silenciosos.

[El backend →](architecture.md) · [Añadir una funcionalidad →](adding_features.md) ·
[Pruebas →](testing.md)
