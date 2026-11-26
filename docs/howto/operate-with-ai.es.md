---
source_sha: "d2ccce975127"
---

# Gestionar AgenticOS con un cliente de IA { #operate-agenticos-with-an-ai-client }

El [plugin de AgenticOS](https://github.com/vstorm-co/agenticos/tree/main/plugins/agenticos)
añade procedimientos a las herramientas MCP: despliegue, dependencias, soluciones
y publicación de agentes probados. Actúa con los permisos del miembro conectado
en una organización. La instalación requiere una terminal o un ejecutor de CI.

## Instalar y conectar { #install-and-connect }

```bash
claude plugin marketplace add vstorm-co/agenticos
claude plugin install agenticos@agenticos
claude mcp add --transport http agenticos https://<api-host>/mcp
```

Complete OAuth en el navegador y seleccione la organización y los scopes.
Configuración → Clientes MCP muestra los comandos de cada cliente. El plugin
no incluye una dirección fija. [MCP](../mcp.md) explica los permisos y aprobaciones.

La base se probó con 1.82.2. Las nuevas herramientas de dependencias, calidad y
paquetes usan el contrato MCP 1, anunciado por `get_platform_context`. Un servidor
anterior conserva sus herramientas existentes. El cliente debe descubrir las
funciones y scopes: una versión no concede permisos. Las rutas exclusivas del
asistente requieren OAuth; las claves normales conservan el límite de la API pública.

## Crear y publicar una solución { #build-and-release-a-solution }

Describa el resultado, los usuarios, las fuentes y los efectos permitidos con sus
propias palabras. El cliente descubre capabilities, nodos de workflow, conexiones
y recursos existentes antes de diseñar. Los paquetes de soporte, repositorio y
onboarding son ejemplos, no una lista cerrada de casos compatibles.

Los perfiles de modelo pueden usar IDs existentes del vault.
`list_secret_references` muestra solo nombres, IDs, tipos y propósitos accesibles,
sin valores ni fragmentos de claves. El descubrimiento de endpoints identifica
servicios locales de embeddings. `get_setup_link` devuelve la entrada de secretos
y el consentimiento OAuth a la sesión propia de la persona en la consola.
Nunca pegue credenciales ni la dirección de callback OAuth en una conversación o paquete.

`plan_solution` valida un manifiesto y devuelve su hash y permisos necesarios.
`install_solution` requiere ese hash, el manifiesto exacto y una clave de
instalación. Crea recursos privados y su registro en una transacción, sin publicar,
ejecutar, indexar ni programar. Los reintentos iguales devuelven el registro;
un manifiesto distinto para el mismo usuario, organización y clave se rechaza.
Otra copia requiere otra clave y nombres de recursos sin conflictos.

Las referencias lógicas vinculan agentes con sus nuevos Context, skills y bases
de conocimiento. La preparación de un workflow puede incluir una tabla y su ID
provisional. Modelos, embeddings y conexiones externas siguen usando IDs explícitos
del despliegue. Lea los recursos tras instalar: el registro conserva la historia,
no prueba que no hayan cambiado o desaparecido después. Edite los recursos con
sus operaciones normales; la instalación no los sobrescribe como actualización del paquete.

Para publicar, cree un dataset con casos evaluables, estime y ejecute evals,
compruebe el resultado y luego publique una versión y promueva un entorno. Fije
producción antes de publicar si sigue la última versión y necesita staging.
Se mantienen las conexiones de prueba, las puertas y los límites de excepciones.
El rollback apunta el entorno a una versión existente y conserva la historia.
Consulte [Entornos](../environments.md).

## Verificar un despliegue o fork { #verify-a-deployment-or-fork }

El skill de despliegue usa el [procedimiento para un host](../deploy.md), bootstrap
y doctor existentes. El skill de desarrollo gestiona el prefijo de imágenes del
fork y los PR de actualización desde upstream. MCP no concede permisos SSH ni de nube.

Para una comprobación local aislada desde un checkout:

```bash
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0
# Ejecutar el plan y guardar el informe fuera del entorno temporal:
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0 --run --report /tmp/agenticos-smoke.json
```

La prueba usa imágenes publicadas, un proyecto Compose aislado, credenciales
locales generadas y un modelo local determinista. Inicializa una organización,
comprueba consola y API y completa una ejecución de agente con un cliente MCP
real. Después elimina sus contenedores y volúmenes. Verifica el funcionamiento
de la plataforma, no la calidad del modelo, un proveedor de pago, DNS externo ni TLS de producción.
