<!-- source_sha: 191696f072e5 -->

<div align="center">

<img src="docs/assets/amigo.svg" alt="Amigo, la mascota de AgenticOS" width="96">

<h1>AgenticOS</h1>

<p>
  <b>Un solo lugar para construir, ejecutar y gobernar los agents de IA de tu empresa.</b><br>
  Autoalojado y de código abierto — en tu Postgres, en tu Docker, bajo tu
  dominio.<br>
  <sub>El OS del nombre es una afirmación que cumplimos: <a href="#el-mejor-os-agéntico-que-puedes-ejecutar-tú-mismo">siete funciones, siete mecanismos</a>.</sub>
</p>

<p>
  <a href="#-inicio-rápido">Inicio rápido</a> &middot;
  <a href="#qué-aspecto-tiene">Pantallas</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/presentation/">Presentación</a> &middot;
  <a href="docs/index.es.md">Documentación</a> &middot;
  <a href="#el-mejor-os-agéntico-que-puedes-ejecutar-tú-mismo">Por qué un OS</a> &middot;
  <a href="#comparado-con-las-alternativas">Comparativa</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="docs/testing.es.md"><img src="https://img.shields.io/badge/platform%20layer-100%25-brightgreen" alt="Coverage"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Licence"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
  <a href="https://github.com/vstorm-co/agenticos/stargazers"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat&logo=github&color=e3b341" alt="Stars"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <b>Español</b>
</p>

</div>

---

Una empresa acaba con agents en cinco sitios y no sabe responder a cuatro
preguntas: **qué ejecutamos, cuánto costó, qué tocó y quién dio permiso.**
AgenticOS es un solo lugar para construirlos y una sola contabilidad para todos.

**El harness, como producto**: skills, archivos de contexto — `AGENTS.md` como
una página —, MCP a escala de registro, automatizaciones con horario o con
disparador, y un budget que detiene un run *antes* de la llamada al modelo.

Abajo: una hoja de cálculo soltada en el chat y una frase pidiendo gráficos. El
agent escribe el código, lo ejecuta en una caja cerrada y responde.

<div align="center">

<video src="https://github.com/user-attachments/assets/9a8e0f44-781c-4f93-990d-b5b7094cc8fc" controls muted loop playsinline width="100%">
  <img src="docs/assets/screens/chat-live-demo.webp" alt="Chat: un CSV se convierte en Python dentro de una sandbox, y después en gráficos" width="100%">
</video>

</div>

Y la misma consola en el escritorio, con compañía: la
[aplicación de escritorio](#en-el-escritorio-si-quieres) opcional, su mascota y un
atajo que hace una captura de pantalla directamente en un chat nuevo.

<div align="center">

<video src="https://github.com/user-attachments/assets/b82867ae-3543-406e-a552-e3a8b61f1d10" controls muted loop playsinline width="100%">
  <img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, la mascota de escritorio, con sombrero, diciendo: No more caramba." width="270">
</video>

</div>

<div align="center">
<sub>
¿No te apetece leer? <a href="https://vstorm-co.github.io/agenticos/presentation/"><b>Todo esto en veinte diapositivas</b></a> — cuál es el problema, qué contiene un spec, dónde responde y qué rechaza.
</sub>
</div>

## ⚡ Inicio rápido

Un comando, y lo único que necesita es Docker. Descarga un archivo compose, se
trae las imágenes publicadas, hace cuatro preguntas y te devuelve una consola con
un agent que funciona dentro. Nada sale de tu máquina.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

<details>
<summary><b>macOS</b></summary>

Docker Desktop u [OrbStack](https://orbstack.dev). Nada más.

</details>

<details>
<summary><b>Linux</b></summary>

```bash
curl -fsSL https://get.docker.com | sh
sudo apt install docker-compose-plugin
```

</details>

<details>
<summary><b>Windows</b></summary>

A través de WSL2. En un PowerShell de administrador:

```powershell
wsl --install
```

Después Docker Desktop con la integración de WSL2 activada, y ejecuta el
instalador dentro de la shell de Ubuntu que te da.

</details>

### Qué te pregunta

| | |
|---|---|
| **Qué modelo** | OpenAI, Anthropic, Google, OpenRouter — o *decidir más tarde*, que lo crea todo y te deja pegar una clave en la consola |
| **Tu clave** | Se escribe oculta, se guarda cifrada en tu propia base de datos y nunca se vuelve a mostrar |
| **Tu usuario y el nombre de la organización** | Los valores por defecto sirven para echar un vistazo |
| **Un interruptor** | Replicar el registro público de MCP para que los 5.802 servidores de herramientas se puedan buscar por nombre |

Añade `--check` para solo averiguar qué falta, `--dry-run` para ver todos los
comandos que ejecutaría sin ejecutar ninguno, o hazlo sin supervisión:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- \
  --yes --provider anthropic --api-key sk-ant-... --org "Acme"
```

### O escribe tú mismo los tres comandos

El instalador es una envoltura alrededor de estos, y no hay ningún paso que dé
que no puedas dar a mano:

```bash
mkdir agenticos && cd agenticos
curl -fsSLO https://raw.githubusercontent.com/vstorm-co/agenticos/main/docker-compose.yml
docker compose up -d                                          # postgres (pgvector), redis, api, prefect, console
docker compose exec -T -e BOOTSTRAP_API_KEY=sk-... app \
  agenticos cmd bootstrap                                    # an org, an owner, a key, a model, a published agent
open http://localhost:3000                                   # sign in as admin@example.com / admin123
```

Las imágenes son `ghcr.io/vstorm-co/agenticos-backend` y `agenticos-frontend`,
publicadas para amd64 y arm64 en cada release; `AGENTICOS_VERSION=x.y.z` en un
`.env` junto al archivo fija una. No hay ningún `.env` que escribir antes: toda
variable de compose tiene un valor por defecto. Para cambiar el código, haz
`git clone` y `make dev` en su lugar: un clon construye esas mismas imágenes
desde el árbol.

Si algo no arranca, `docker compose exec app agenticos cmd doctor` responde a la
única pregunta que importa — si este despliegue puede ejecutar realmente un
agent — y [docs/install.es.md](docs/install.es.md) tiene el resto.

## Qué obtienes

- 🧰 **El harness, como configuración.** Retrieval sobre tus documentos, un
  navegador de verdad, Python en una sandbox con archivos y una shell, gráficos,
  imágenes, delegación — activados por agent, no cableados en el código.
- 📄 **Archivos de contexto.** `AGENTS.md` y `CLAUDE.md` como una página:
  instrucciones permanentes escritas una vez y adjuntas a cada agent que las
  necesita.
- 🎓 **Skills.** Un procedimiento escrito una vez en lenguaje llano, que se carga
  cuando el agent decide que es relevante. Edítalo; en vivo en la siguiente
  respuesta, sin release.
- 🔌 **MCP, a escala de registro.** **5.802 servidores** en el catálogo,
  buscables por nombre — 99 de ellos revisados a mano y con su OAuth
  conectado. O cualquier URL.
- 📚 **Documentos leídos como es debido.** Elige el lector de PDF por colección,
  o para un solo archivo: PyMuPDF incorporado, LlamaParse cuando el significado
  está en las tablas, LiteParse OCR autoalojado para escaneos. Más cómo se parte
  y el idioma del OCR.
- ⏰ **Automatizaciones.** Horarios y disparadores por evento — el triaje de las
  07:00, el resumen del lunes. Los mismos límites y el mismo registro que
  cualquier cosa que pida una persona.
- 📡 **Un runner, ocho superficies.** Chat web, una página alojada, un widget, la
  API HTTP, un WebSocket en crudo, Slack, Telegram, Mattermost. Publicado una
  sola vez.
- 🖥️ **Solo hace falta un navegador; una aplicación de escritorio si la quieres.**
  La consola es una aplicación web. La [aplicación de escritorio](docs/desktop.es.md)
  es esa misma consola en una ventana propia, más una mascota en el escritorio y
  un atajo que hace una captura directamente en un chat nuevo. Un añadido, nunca
  un requisito.
- 🛡️ **Gobernado.** Budgets que detienen un run antes de la petición al modelo,
  aprobación para todo lo que tiene efectos, un rastro de auditoría y aislamiento
  de inquilinos en el esquema.
- 📊 **Un dashboard que cada persona organiza.** 35 tarjetas — runs, gasto, salud
  de los servicios, calidad de las respuestas, capacidad de la sandbox —, cada
  una limitada a lo que ese lector puede ver. Un responsable de finanzas y un
  ingeniero mantienen tarjetas distintas en un mismo despliegue.

**El código define, la configuración compone.** Un equipo de negocio compone
agents en un navegador y nunca abre Python; los ingenieros amplían lo que hay
para componer, y la configuración nunca puede alcanzar más que lo que el código
registró. El techo es el registro, no un archivo de configuración — y es
Apache-2.0, en tu hardware.

## Qué aspecto tiene

### Dentro de un agent

Un agent es un **spec**: instrucciones, un modelo, las capabilities que puede
alcanzar, el conocimiento ligado a él, un budget y dónde responde. Nada sale a
producción hasta **Publish**, y cada publicación es una versión.

<img src="docs/assets/screens/dark/builder-build.webp" alt="Definir un agent: instrucciones, modelo y la versión que está en vivo" width="100%">

<table>
<tr>
<td width="50%">

**Toolbox** — Lo que el agent puede hacer, como interruptores: tus documentos, un navegador, Python, gráficos, delegación. Cada uno puede exigir antes la aprobación de una persona. Esto es el **harness de IA**, montado en un formulario.

<img alt="Toolbox" src="docs/assets/screens/dark/builder-toolbox.webp" width="100%">

</td>
<td width="50%">

**Visual map** — El agent como un grafo: qué lo alcanza y qué alcanza él. Una caja con borde discontinuo es algo que nadie ha adjuntado.

<img alt="Visual map" src="docs/assets/screens/dark/builder-visual-map.webp" width="100%">

</td>
</tr>
<tr>
<td width="50%">

**Limits** — Un tope mensual por agent, comprobado *antes* de cada llamada al modelo en lugar de sumado después, más un límite de pasos para ese bucle que sale barato y nunca se detiene.

<img alt="Limits" src="docs/assets/screens/dark/builder-limits.webp" width="100%">

</td>
<td width="50%">

**History** — Todas las versiones que ha tenido, todavía legibles. Volver atrás es un clic.

<img alt="History" src="docs/assets/screens/dark/builder-history.webp" width="100%">

</td>
</tr>
</table>

<sub>Estas cuatro solo están en oscuro — la mitad clara no se ha capturado.</sub>

### La primera pantalla

**Dashboard** — 35 tarjetas, colocadas por quien las lee: runs, gasto, salud de
los servicios, calidad de las respuestas, frescura de las sincronizaciones,
capacidad de la sandbox. Cada una limitada a lo que esa persona tiene permitido
ver, así que un responsable de finanzas y un ingeniero mantienen dashboards
distintos en el mismo despliegue.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/dashboard.webp">
  <img alt="El dashboard: 35 tarjetas organizables" src="docs/assets/screens/light/dashboard.webp" width="100%">
</picture>

### Ejecutar cuarenta de ellos

<table>
<tr>
<td width="50%">

**Agents** — Todos los agents que ejecutas, con la versión que está en vivo y quién puede usarlo.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents.webp">
  <img alt="Agents" src="docs/assets/screens/light/agents.webp" width="100%">
</picture>

</td>
<td width="50%">

**Templates** — Empieza por una creada para tu sector; te queda un borrador que ajustar y publicar.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents-templates-dialog.webp">
  <img alt="Templates" src="docs/assets/screens/light/agents-templates-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Una respuesta, abierta** — Toda respuesta queda registrada: la pregunta, qué miró, cada llamada a una herramienta, la duración y el coste hasta la fracción de céntimo.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-run-detail.webp">
  <img alt="Una respuesta, abierta" src="docs/assets/screens/light/activity-run-detail.webp" width="100%">
</picture>

</td>
<td width="50%">

**Cómo se leen tus documentos** — Tres lectores de PDF — PyMuPDF, LiteParse, LlamaParse — más chunking y OCR. Por colección, anulable en el siguiente archivo. Una lista de precios escaneada y un contrato no quieren el mismo.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-base-upload-parsing-dialog.webp">
  <img alt="Cómo se leen tus documentos" src="docs/assets/screens/light/knowledge-base-upload-parsing-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Context** — Hechos permanentes — nombres de producto, política, el tono de la casa — en un solo sitio en vez de en cuarenta prompts.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img alt="Context" src="docs/assets/screens/light/context.webp" width="100%">
</picture>

</td>
<td width="50%">

**Pregunta antes de actuar** — Todo lo que envía, presenta o reembolsa espera a una persona, con la acción prevista escrita. Se decide exactamente una vez.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-approvals.webp">
  <img alt="Pregunta antes de actuar" src="docs/assets/screens/light/activity-approvals.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Cuánto cuesta** — Gasto por periodo y por agent. El tope se comprueba antes de preguntar al modelo, así que algo desbocado se detiene a media frase en vez de llegar como una factura.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-spend.webp">
  <img alt="Cuánto cuesta" src="docs/assets/screens/light/activity-spend.webp" width="100%">
</picture>

</td>
<td width="50%">

**Claves y credenciales** — Todas las claves, cifradas y separadas por equipo. Reemplazables, nunca legibles de nuevo — tampoco por quien administra el servidor.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/vault.webp">
  <img alt="Claves y credenciales" src="docs/assets/screens/light/vault.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Las herramientas que ya pagas** — 5.802 servidores MCP en el catálogo, buscables por nombre, 99 de ellos revisados a mano y con su OAuth conectado. O cualquier servidor por URL. Ningún conector que escribir.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/mcp-servers.webp">
  <img alt="Las herramientas que ya pagas" src="docs/assets/screens/light/mcp-servers.webp" width="100%">
</picture>

</td>
<td width="50%">

**Dónde se encuentra la gente con él** — Slack, Telegram, Mattermost, un widget en una web, tu propio software a través de la API. Publicado una vez; los mismos límites en todas partes.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/channels.webp">
  <img alt="Dónde se encuentra la gente con él" src="docs/assets/screens/light/channels.webp" width="100%">
</picture>

</td>
</tr>
</table>


<sub>Las capturas siguen tu tema de GitHub. <a href="docs/screens.es.md">Las 35 pantallas</a>.</sub>

## El mejor OS agéntico que puedes ejecutar tú mismo

Eso es una afirmación, y la única forma honesta de hacerla es entregarte los
criterios y dejar que cuentes. Un sistema operativo hace siete cosas. Cada fila
de abajo es un mecanismo que puedes leer en el código fuente, no una promesa.

| Qué hace un sistema operativo | Qué hace AgenticOS |
|---|---|
| **Ejecuta y aísla procesos** | Ejecuta agents, detiene uno al llegar a su budget, aísla inquilinos en el esquema en lugar de en el código de servicio y guarda cada run con lo que costó |
| **Impone límites de recursos** - cuotas, cgroups | Budgets mensuales por agent, comprobados *antes* de cada petición al modelo en lugar de contados después. Un run que falla registra igualmente lo que gastó |
| **Controla el acceso** - usuarios, permisos, `sudo` | Un [catálogo de permisos](docs/permissions.es.md) en el código, roles compuestos a partir de él y concesiones por recurso que amplían y nunca reducen. `approval: required` es el `sudo`: una herramienta que actúa sobre el mundo exterior espera a una persona |
| **Alcanza el hardware a través de controladores** | Una sola interfaz hacia [27 providers de modelos](docs/models.es.md) y hacia [cualquier servidor MCP por URL](docs/mcp.es.md). Cambia un perfil de modelo y todos los agents que lo usan se mueven, sin que haya que republicar ninguno |
| **Mantiene un sistema de archivos** | [Colecciones, skills y contexto adjunto](docs/file-processing.es.md) en tu propio Postgres, con los embeddings con clave por organización |
| **Da una sola shell a muchas interfaces** | Un solo runner detrás del chat web, la API HTTP, Slack, Telegram, un widget, una página alojada y un horario. El mismo budget, la misma puerta de aprobación, el mismo rastro de auditoría |
| **Escribe un registro de auditoría** - syslog, auditd | Quién ejecutó qué, cuándo, cuánto costó y quién lo aprobó. Se escribe incluso cuando el run falló |

Aplica esas mismas siete a cualquier otra cosa de la categoría. Esa es la prueba
con la que nos gustaría que se nos juzgara, y
[Cuándo usar otra cosa](docs/about/comparison.es.md) es donde la pasamos frente a
las alternativas, incluidas las filas en las que la respuesta honesta aquí es
"todavía no".

**Ahora aplica esas mismas siete a cualquier otra cosa de la categoría**,
incluidas las que tienen mil veces nuestras estrellas. Ninguna explica por qué es
un sistema operativo, porque la mayoría son un workspace con las letras en la
caja. La afirmación entera es esta: no que tengamos más usuarios, sino que somos
los únicos que exponen los criterios y después los cumplen en código que puedes
leer.

Donde la respuesta honesta aquí sigue siendo "todavía no", es una fila de la
comparativa de abajo y una línea de la [hoja de ruta](docs/ROADMAP.md).
[Cuándo usar otra cosa](docs/about/comparison.es.md) es la versión larga, incluido
dónde pierde esto, y
[qué hace que algo sea un sistema operativo para agents](docs/about/index.es.md) son
los criterios por sí solos: cógelos y puntúa a quien quieras, a nosotros
incluidos.

## Qué puede hacer un agent

Se activan por agent, en el Builder. Cada una lleva sus propios ajustes, su
propio alcance de permisos y — cuando actúa sobre el mundo exterior — su propia
puerta de aprobación.

| | |
|---|---|
| **Responder a partir de tus documentos** | Retrieval sobre colecciones en tu propio Postgres, más [skills](docs/skills.es.md) que carga bajo demanda y [archivos de contexto](docs/context.es.md) ligados a varios agents |
| **Ir a averiguarlo** | Búsqueda web, descargar una página como es debido o manejar un **navegador de verdad** por un sitio en el que hay que hacer clic |
| **Hacer el trabajo** | Ejecutar Python, mantener una [sandbox](docs/sandbox.es.md) con archivos y una shell, dibujar gráficos, generar imágenes |
| **Ocuparse de lo que es demasiado grande para una respuesta** | Delegar en subagents, llevar una lista de tareas, pensar más rato, compactar una conversación larga |
| **No salirse de la raya** | Guardrails que redactan o bloquean, topes de salida por herramienta y el reloj |
| **Cualquier otra cosa** | [Cualquier servidor MCP por URL](docs/mcp.es.md) - 5.802 en el catálogo, 99 de ellos revisados y con sus flujos de OAuth conectados, y ningún conector que escribir |

## Dónde responde

Publica una vez. El mismo runner sirve todas estas, así que una respuesta no
depende de por dónde llegó la pregunta.

| | |
|---|---|
| **Chat web** | En la consola, con adjuntos y slash commands |
| **La aplicación de escritorio** | La misma consola en una ventana propia, con una mascota y un atajo de captura de pantalla - una [envoltura opcional](docs/desktop.es.md), no un segundo producto |
| **Una página alojada** | `/e/{key}` - manda un enlace a alguien, sin necesidad de cuenta |
| **Un widget incrustable** | En tu propio sitio, con variables tomadas de la barra de direcciones |
| **La API HTTP** | [Un POST y ya tienes una respuesta](docs/api.es.md) |
| **Un WebSocket en crudo** | Transmite tokens a un frontend que hayas construido tú |
| **Slack, Telegram, Mattermost** | Donde una `@mention` se ejecuta como **la persona que la envió**, no como el bot |
| **Horarios y disparadores** | Un reloj, un webhook o un buzón que consultamos - [routines](docs/triggers.es.md) |

## En el escritorio, si quieres

Todo lo anterior funciona en un navegador, y así es como lo usa la mayoría. Para
quien la quiera en el dock existe una [aplicación de escritorio](docs/desktop.es.md):
una envoltura fina alrededor de la misma consola — mismo inicio de sesión, mismos
permisos, nada empaquetado — con dos cosas que una pestaña del navegador no puede
hacer. Una mascota que vive en el escritorio mientras trabajas y un atajo global
(`⌘⇧A`) que hace una captura de cualquier región y abre un chat nuevo con ella
adjunta.

<div align="center">

<img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, la mascota de escritorio, con sombrero, diciendo: No more caramba." width="270">

<sub>Amigo, una de las cinco mascotas. Arrástrala, haz clic, acaríciala; clic derecho para su menú. <b>No more caramba in your AI.</b></sub>

</div>

## Comparado con las alternativas

El único de estos que puedes ejecutar de principio a fin en infraestructura que
ya tienes, con agents que edita alguien que no es ingeniero y que un contable
puede auditar.

| | **AgenticOS** | Cloudflare&nbsp;OS | Glean | Una&nbsp;biblioteca |
|---|:---:|:---:|:---:|:---:|
| Código abierto | ✅ Apache-2.0 | ✅ Apache-2.0 | — | ✅ |
| **Funciona sobre infraestructura corriente** (Postgres, Redis, Docker) | ✅ | — | — | ✅ |
| Funciona aislado de la red, sin cuenta con el proveedor | ✅ | — | — | ✅ |
| Modelos locales (Ollama, LiteLLM) | ✅ | ✅ | — | ✅ |
| Agent construido y editado por alguien que no es ingeniero | ✅ | ~ | ✅ | — |
| Versionado al publicar, exportable a tu git | ✅ | ~ | — | — |
| Budget que detiene un run antes de la llamada al modelo | ✅ | ~ | ~ | DIY |
| Aprobación humana en herramientas con efectos | ✅ | ✅ | ~ | DIY |
| Aislamiento multiinquilino en el esquema | ✅ | ~ | ✅ | DIY |
| Vault de secretos por organización | ✅ | ✅ | ✅ | DIY |
| **Cualquier servidor MCP por URL, 5.802 en el catálogo** | ✅ | ✅ | ~ | ~ |
| **Slack, Telegram, widget, página alojada y API desde un solo runner** | ✅ | — | ~ | DIY |
| Conectores con ACL a más de 275 sistemas SaaS | — | ~ | ✅ | — |
| Harness de evaluación | — | — | ✅ | ~ |
| SAML / SCIM | — | ✅ | ✅ | — |

<sub>✅ de primera clase · ~ parcial o mediante configuración · — no disponible · DIY lo conectas tú mismo.
"Una biblioteca" significa LangGraph, Pydantic AI o similar. Refleja el estado de cada proyecto a fecha de 2026-08;
las correcciones son bienvenidas por PR. Las tres últimas filas nos toca arreglarlas a nosotros y están en la
<a href="https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md">hoja de ruta</a>.</sub>

## Por qué existe

La mayoría de los frameworks de agents te dan una biblioteca. Escribes Python, lo
despliegas, y cada cambio en el comportamiento de un agent es un pull request,
una revisión y una release. Esa es la forma correcta para una función de producto
y la equivocada para los cuarenta agents pequeños que una empresa quiere de
verdad, porque la persona que sabe qué debe decir el agent no es la persona con
acceso de commit.

AgenticOS saca el agent del código y, en su lugar, pone gobernanza a su
alrededor. Los [secretos](docs/secrets.es.md) se sellan por organización: una clave
copiada de la fila de la base de datos de un inquilino no se puede descifrar para
otro, y ninguna respuesta de la API devuelve jamás una.

## Documentación

| | |
|---|---|
| [Instalación](docs/install.es.md) · [Tu primer agent](docs/first-agent.es.md) | De cero a un agent que responde |
| [Conceptos](docs/concepts.es.md) | Spec, versión, exposición, disparador, run — los cinco sustantivos |
| [Permisos](docs/permissions.es.md) · [Gobernanza](docs/governance.es.md) | Quién puede hacer qué; budgets, aprobaciones, auditoría |
| [Capabilities](docs/reference/capabilities.es.md) · [MCP](docs/mcp.es.md) | Qué puede hacer un agent, y cómo añadir una herramienta |
| [Modelos](docs/models.es.md) · [Secretos](docs/secrets.es.md) | Providers, perfiles, coste; el vault |
| [Conocimiento](docs/file-processing.es.md) · [Skills](docs/skills.es.md) | Parsers, chunking, OCR; conocimiento escrito |
| [Canales](docs/channels.es.md) · [API](docs/api.es.md) | Slack, Telegram, widget, WebSocket, HTTP |
| [Aplicación de escritorio](docs/desktop.es.md) | La envoltura opcional: la consola en una ventana, la mascota, el atajo de captura |
| [Arquitectura](docs/architecture.es.md) · [Pruebas](docs/testing.es.md) | Cómo está construido, y cómo se verifica |

Hecha con MkDocs: `make docs` la sirve en :8001. El stack, en una línea: FastAPI
+ Pydantic v2, PostgreSQL con pgvector, Redis, Prefect,
[Pydantic AI](https://ai.pydantic.dev), Next.js 15. Nada llama a casa: las únicas
llamadas salientes son las que hacen tus agents.

## Contribuir

`make check` antes de un pull request: todos los jobs de CI salvo e2e, unos cinco
minutos. El comportamiento nuevo llega con una prueba; un fallo llega con una
prueba de regresión. La **capa de plataforma se mantiene al 100% de cobertura** y
CI falla por debajo de eso.

Tres cosas que hacen tropezar en un primer cambio: una herramienta es código y un
agent no (no existe `@agent.tool`: una capability se registra y a partir de ahí es
un interruptor en el Builder de todo el mundo); las puertas `require(...)` van
solo en las rutas de colección; y si la herramienta ya existe como servidor MCP,
no escribas ninguna. [CONTRIBUTING.md](CONTRIBUTING.md) tiene el resto,
[`.claude/`](.claude/README.md) tiene esas mismas convenciones escritas para una
máquina, y las buenas primeras tareas están
[etiquetadas aquí](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>El resto del ecosistema OSS de Vstorm</b></summary>

Todo lo de abajo funciona sobre [Pydantic AI](https://ai.pydantic.dev).

| Proyecto | Qué es | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | El generador con el que se construyó AgenticOS — FastAPI + Next.js 15, RAG, streaming, autenticación, más de 20 integraciones | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Un Claude Code de código abierto y autoalojado — un asistente de terminal y el framework que lo sostiene | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — seguimiento de costes, detección de inyección de prompts, filtrado de PII, redacción de secretos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Delegación anidada en subagents, ejecución en paralelo, cancelación de tareas | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Almacenamiento de archivos y sandboxes aisladas con Docker, con un sistema de permisos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Planificación jerárquica de tareas con almacenamiento en PostgreSQL y un sistema de eventos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Paquete de skills que convierte a un agent de programación en un ingeniero sénior de producción | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Paquete de skills de estudio de contenido para agents de programación — consciente de la marca, con anti-slop incorporado | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Míralos todos en **[oss.vstorm.co](https://oss.vstorm.co)**.

Míralos todos en **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Licencia

Apache License 2.0 - consulta [`LICENSE`](LICENSE) y [`NOTICE`](NOTICE).
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) lista cada componente que
llevan las imágenes y su licencia; la revisión de a qué obligan esas licencias, y
los hallazgos todavía abiertos, está en [la documentación](https://vstorm-co.github.io/agenticos/licenses/).

Apache-2.0 en vez de MIT porque AgenticOS está pensado para desplegarse dentro de
otras empresas: la concesión explícita de patentes es la parte por la que
pregunta su revisión legal, y MIT no dice nada al respecto.

---

<div align="center">

### ¿Necesitas ayuda para poner agents en producción?

<p>
Somos <a href="https://vstorm.co"><b>Vstorm</b></a>, una consultoría de ingeniería
de IA agéntica aplicada con más de 30 implantaciones de agents en producción.<br>
AgenticOS es aquello sobre lo que los construimos, y lo desplegamos dentro de la
infraestructura del cliente: tu nube, tu centro de datos o aislado de la red.
</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Hecho con cariño por <a href="https://vstorm.co"><b>Vstorm</b></a> ·
<a href="https://oss.vstorm.co">oss.vstorm.co</a>

</div>
