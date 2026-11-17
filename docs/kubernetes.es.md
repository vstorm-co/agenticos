---
source_sha: "673afa1052f7"
---

# Desplegar en Kubernetes { #deploy-on-kubernetes }

`charts/agenticos` instala API, worker y consola desde imágenes publicadas.
Requiere PostgreSQL externo con pgvector, Redis/Valkey y un bucket S3 existente.
No instala bases de datos ni prepara sus copias de seguridad. `appVersion` define
la versión de imagen predeterminada. Fija otra versión con `image.tag` o imágenes
inmutables con `image.backendDigest` y `image.frontendDigest`.

Las imágenes de backend anteriores a 1.63.0 esperan archivos temporales de
ingesta compartidos y no son compatibles con este chart.


## Kubernetes y OpenShift { #kubernetes-and-openshift }

Kubernetes programa y administra contenedores. Red Hat OpenShift es una plataforma
Kubernetes con componentes y políticas adicionales, como Security Context
Constraints (SCC), integración con SELinux y Routes. El mismo chart es el punto de
partida para ambas plataformas. Una prueba satisfactoria de Kubernetes no valida
esos componentes de OpenShift ni la integración de identidad y almacenamiento de
un proveedor de nube.

| Despliegue | Evidencia y comprobaciones pendientes |
| --- | --- |
| Kubernetes con Helm | Prueba smoke reproducible en kind descrita abajo; el ingress público y la aplicación de NetworkPolicy requieren pruebas en tu clúster |
| OpenShift con Helm | Perfil candidato `values-openshift.yaml`; falta validar SCC, SELinux, Routes y almacenamiento en un clúster real |
| Argo CD en ambas plataformas | Correspondencia de hooks de migración descrita abajo; la prueba de Helm no valida una sincronización de Argo CD |
| Sandbox y OIDC | Integraciones opcionales con configuración y pruebas de aceptación independientes descritas abajo |

## Compatibilidad y límites { #compatibility-and-limits }

La prueba reproducible usa kind 0.33.0, Kubernetes 1.37.0 y Helm 4.3.1. Comprueba
admisión Pod Security restringida, sistemas raíz de solo lectura, UID numéricos
arbitrarios, migraciones, inicio de sesión, respuesta de un agente publicado,
upload S3, ingesta y ejecución duradera en segundo plano. El modelo es un fixture
determinista del protocolo; no verifica disponibilidad ni calidad de un proveedor
de pago.

**OpenShift sigue sin validar.** `values-openshift.yaml` elimina UID fijos y
`fsGroup` para que `restricted-v2` asigne los rangos del namespace. Pruébalo en tu
versión real de OpenShift. Un UID arbitrario en Kubernetes no valida admisión SCC,
SELinux, Routes ni controladores de almacenamiento. No concedas `anyuid`, SCC
privilegiadas ni acceso al socket del nodo para conseguir que arranque.

El chart base no incluye daemon de sandbox, servicio de navegador ni renderer de
artefactos, y no monta el socket de Docker. La ejecución en contenedores, el uso
de ordenador/navegador y el rendering que necesitan esos servicios quedan
indisponibles hasta configurar el servicio externo correspondiente. Usa la
[configuración de sandbox](sandbox.md) y el vault; no montes
`/var/run/docker.sock` de un nodo en los pods de la aplicación.

## Preparar servicios externos { #prepare-external-services }

Crea la base de datos y el usuario `agenticos` en PostgreSQL con pgvector. La
identidad de migración necesita permiso para crear la extensión vector, o el
administrador debe instalarla antes. Da acceso a la aplicación a su propia base,
base Redis y bucket. Consulta [servicios externos y conexiones](scaling.md).

Crea el bucket antes del bootstrap: también almacena los avatares de agentes
iniciales. El cifrado predeterminado es `sse-s3`. `storage.encryption: sse-kms`
requiere además `storage.kmsKeyId`. El MinIO de pruebas sin KMS usa `none`; no es
una recomendación de desactivar el cifrado en producción.

Mediante tu gestor de secretos, crea un Secret en el namespace de la aplicación
**antes de ejecutar Helm**. Debe contener valores independientes de `SECRET_KEY`,
`API_KEY` y `VAULT_MASTER_KEY`, generados con `openssl rand -hex 32`, y
`POSTGRES_PASSWORD`. Conserva estas claves durante las actualizaciones. Cambiar la
clave del vault es una [rotación](secrets.md), no una reinstalación: permite
descifrar las credenciales guardadas de las organizaciones. Añade `REDIS_PASSWORD`
si hace falta y la pareja `FILE_STORAGE_S3_ACCESS_KEY` /
`FILE_STORAGE_S3_SECRET_KEY` para credenciales S3 estáticas. Omite ambas claves S3
si utilizas la cadena de credenciales de identidad de workload del proveedor.

El chart usa una cuenta de servicio existente sin montar automáticamente el token
de API. Para identidad de workload, establece `serviceAccountName` y configura
las anotaciones/proyección de token que necesita tu proveedor. Los hooks de
migración también usan esa cuenta. Las claves de modelos siguen siendo secretos
de organización en el vault del producto.

Para `postgres.sslMode: verify-full` (predeterminado) o `verify-ca`, crea el
Secret indicado por `trust.existingSecret` con el certificado CA de la base bajo
la clave `postgres-ca.crt`. El chart lo monta en solo lectura en migración, API
y worker y establece `PGSSLROOTCERT`. `trust.postgresCaKey` selecciona otro nombre.
Para una CA privada de Redis, añade un bundle de CA públicas/privadas e indica su
clave en `trust.sslCaKey`; esto establece `SSL_CERT_FILE`. Conserva las CA públicas
necesarias para proveedores de modelos. Otros ajustes del SDK, como
`AWS_CA_BUNDLE`, pueden referenciar el mismo montaje mediante `extraEnv`.

## Instalación { #install }

Usa el chart del tag del repositorio correspondiente a la versión que despliegas.
Prepara `cluster-values.yaml` con configuración, sin credenciales:

```yaml
existingSecret: agenticos-runtime
public:
  siteUrl: https://app.example.com
  apiUrl: https://api.example.com
  websocketUrl: wss://api.example.com
postgres:
  host: postgres.internal
  database: agenticos
  user: agenticos
  sslMode: verify-full
trust:
  existingSecret: agenticos-trust
  postgresCaKey: postgres-ca.crt
redis:
  host: valkey.internal
  ssl: true
storage:
  bucket: agenticos-files
  region: eu-central-1
  # endpoint: https://s3.example.com
  # pathStyle: true
image:
  tag: "1.80.0"
trustedProxy:
  enabled: true
  namespaceLabels:
    kubernetes.io/metadata.name: ingress-system
  podLabels:
    app.kubernetes.io/name: your-ingress-controller
ingress:
  enabled: true
  className: your-ingress-class
  siteHost: app.example.com
  apiHost: api.example.com
  tls:
    - secretName: agenticos-tls
      hosts: [app.example.com, api.example.com]
```

```bash
helm lint charts/agenticos --strict -f cluster-values.yaml
helm upgrade --install agenticos charts/agenticos \
  --namespace agenticos --create-namespace -f cluster-values.yaml \
  --wait --timeout 15m
kubectl -n agenticos exec deployment/agenticos-agenticos-api -- agenticos cmd bootstrap
```

[Instalación](install.md) explica las credenciales de bootstrap y los proveedores.
Crea el namespace antes del Secret si todavía no existe. Configura
`imagePullSecrets` para registros privados. No apliques el chart renderizado con
`kubectl apply`: omite el orden de migraciones de Helm.

Usa dos nombres de host públicos, como en el
[despliegue Compose](deploy.md#why-two-hostnames). El controlador ingress debe
admitir upgrades WebSocket, límites suficientemente largos de inactividad y
peticiones, y los tamaños de upload permitidos. Configúralo mediante sus propias
anotaciones en `ingress.annotations`. Termina TLS con un Secret de certificado
existente o un controlador de certificados. En OpenShift puedes desactivar ingress
y proporcionar dos Routes propias.

Restringe el tráfico con políticas del clúster: la consola accede a la API; API y
worker acceden a PostgreSQL, Redis, S3 y proveedores/servicios externos configurados
explícitamente. No publiques puertos de base de datos ni del worker.

El ingress público requiere `trustedProxy.enabled: true` y selectores no vacíos
de etiquetas de namespace/pods del controlador. Sustituye el ejemplo por las
etiquetas reales de tu controlador protegido. Esto activa
`RATE_LIMIT_TRUST_FORWARDED_FOR` junto con NetworkPolicies: solo el controlador
accede a la consola; la API también admite los pods de consola del release. Usa
un CNI que aplique NetworkPolicy y no publiques los servicios directamente.
Protege esos namespaces frente a pods no confiables. Sin aplicación de políticas,
no actives la confianza en el encabezado.

Exactamente un proxy confiable debe añadir el cliente real a `X-Forwarded-For`.
El limitador lee la última dirección y la consola conserva el encabezado al
reenviar auth. Si un CDN/load balancer añade otro salto, normaliza la dirección
verificada en el edge. La prueba ClusterIP no valida tu controlador ingress ni
CNI: comprueba aislamiento y encabezados antes de exponer tráfico de producción.
Las Routes/proxys externos necesitan los mismos ajustes de proxy confiable.

## Credenciales S3 y diagnóstico del bootstrap { #s3-credentials-and-bootstrap-troubleshooting }

S3 es el protocolo de almacenamiento, no un requisito de usar AWS. Para un servicio
compatible como MinIO, configura `storage.endpoint`, `storage.bucket`,
`storage.region` y los requisitos de `storage.pathStyle` y cifrado del proveedor.
La API nativa de Azure Blob Storage no es un endpoint S3; este chart necesita un
servicio compatible con S3.

Guarda las credenciales estáticas en el Secret indicado por `existingSecret`, con
las claves exactas `FILE_STORAGE_S3_ACCESS_KEY` y `FILE_STORAGE_S3_SECRET_KEY`.
API, worker y migración lo cargan mediante `envFrom`. No pongas claves en `storage`
o `extraEnv`, en Git ni en comentarios públicos de diagnóstico. Una identidad de
workload debe proporcionar una cadena de credenciales que entienda el cliente S3;
la identidad del clúster Azure por sí sola no proporciona credenciales S3.

`botocore.exceptions.NoCredentialsError` durante `agenticos cmd bootstrap` indica
que el cliente S3 no encontró credenciales al guardar un avatar inicial. La
transacción se revierte; «Created owner» no demuestra que se haya confirmado.
Corrige el Secret, reinicia API y worker para recargar las variables, espera a que
estén listos y repite bootstrap. Comprueba por separado el bucket, la conectividad,
la confianza TLS y los permisos de escritura. Nunca imprimas valores secretos.

## Instalación en OpenShift y directorios escribibles { #openshift-installation-and-writable-directories }

Crea primero el proyecto, el Secret de ejecución y la cuenta de servicio. Conserva
el nombre de release `agenticos` para los siguientes comandos. Aplica el perfil
candidato antes de los valores del clúster y deja sin fijar los UID y grupos:

```bash
oc new-project agenticos
helm upgrade --install agenticos charts/agenticos --namespace agenticos \
  -f charts/agenticos/values-openshift.yaml -f cluster-values.yaml \
  --wait --timeout 15m
oc -n agenticos get pods
oc -n agenticos get pods -o 'custom-columns=NAME:.metadata.name,SCC:.metadata.annotations.openshift\.io/scc'
```

Verifica que la SCC admitida sea la política restrictiva prevista. No soluciones
permisos concediendo `anyuid`, SCC privilegiadas o escritura en el sistema raíz.
El frontend monta volúmenes `emptyDir` escribibles en `/tmp` y `/app/.next/cache`;
los montajes del backend están en `templates/_helpers.tpl`. Un error `router-cache`
necesita la **ruta absoluta exacta**, tag/digest de imagen, versión de OpenShift,
SCC admitida y log sin datos sensibles. El chart no cubre cachés fuera de estos
montajes. No montes sobre todo `/app/.next`, porque ocultaría la aplicación compilada.

Con `ingress.enabled: false`, proporciona dos Routes HTTPS hacia los Services de
API y frontend, ambas con el puerto llamado `http`. Configura `public.siteUrl`,
`public.apiUrl` y `public.websocketUrl` con sus direcciones externas. Configura los
timeouts del router, WebSockets, límites de carga, selectores protegidos del router
en `trustedProxy` y NetworkPolicy aplicada por el clúster. Terminar TLS no demuestra
que se reenvíe correctamente la dirección del cliente.

## Orden de migraciones en Argo CD { #argo-cd-migration-ordering }

Argo CD renderiza plantillas Helm; no ejecuta `helm upgrade`. Su
[correspondencia de hooks Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/#helm-hooks)
convierte el Job de migración `pre-install` y `pre-upgrade` de este chart en
`PreSync`; `before-hook-creation` permite repetirlo en la siguiente sincronización.
Prepara namespace, Secrets y cuenta de servicio **antes** de esa fase, fuera de
esta Application o en una operación previa de preparación ya completada.

Ejecuta una sincronización completa de Application y confirma que termina la
migración antes de cambiar los Deployments. La sincronización selectiva omite
hooks. Las anotaciones de hooks Argo CD cambian el tratamiento de hooks Helm;
no mezcles ciclos de vida sin probar el resultado. Mantén iguales los nombres de
Application y release Helm salvo que configures explícitamente el seguimiento de
recursos Argo CD para conservar los selectores de instancia de este chart.

Revertir Git no revierte la base de datos. Argo CD no implementa `pre-rollback` de
Helm; una sincronización completa del chart anterior sigue su propia fase PreSync.
Prueba rechazo tras migración fallida, actualización correcta y reversión compatible
con tu versión de Argo CD antes de habilitar sincronización automática. No uses
Helm y Argo CD como propietarios competidores del mismo release.

## Configuración de OIDC y sandbox { #oidc-and-sandbox-configuration }

Configura los ajustes OIDC no secretos del backend en `extraEnv` de nivel superior,
guarda `OIDC_CLIENT_SECRET` en `existingSecret` y activa el botón por separado:

```yaml
extraEnv:
  OIDC_ISSUER: https://identity.example.com/realms/company
  OIDC_CLIENT_ID: agenticos
  OIDC_REDIRECT_URI: https://api.example.com/api/v1/oauth/oidc/callback
frontend:
  extraEnv:
    OAUTH_PROVIDERS: oidc
    OIDC_DISPLAY_NAME: Company SSO
```

`frontend.extraEnv` está disponible desde la versión `0.1.1` del chart; los anteriores
ignoran la opción. Contiene ajustes públicos de consola, nunca el secreto del cliente.
Las URLs del backend y públicas gestionadas por el chart prevalecen sobre claves
duplicadas del entorno frontend. Registra el callback exacto en el proveedor de
identidad. Verifica botón, redirección, callback, claim de correo verificado,
acceso a organización, cierre de sesión y restricciones de registro. Consulta
[OIDC genérico](configuration.md#single-sign-on-generic-oidc) para claims y ajustes
por proveedor. Una prueba de inicio con contraseña no valida SSO.

Para herramientas sandbox, conecta un servidor OpenSandbox administrado por separado
en **Settings → Sandboxes → Connections**, con su clave API en el vault de la
organización. El chart base no instala ese servidor. AgenticOS validó su ciclo de
vida en Docker; Kubernetes Secure Access y aislamiento OpenShift requieren pruebas
en vivo. Sigue la [configuración de sandbox](sandbox.md) y prueba creación,
ejecución de shell, escritura y lectura entre turnos, reset explícito y limpieza.
Prueba navegador y renderizado por separado. Nunca montes el socket Docker de un
nodo en pods de la aplicación.

## Salud, almacenamiento y capacidad { #health-storage-and-capacity }

La API usa `/api/v1/health/live` para arranque/liveness y
`/api/v1/health/ready` para disponibilidad de base de datos/Redis. El worker
comprueba su archivo de heartbeat de base de datos. La consola usa `/login` para
arranque/disponibilidad y el socket de escucha para liveness. Un proveedor lento
no indica que el proceso esté muerto. Cada workload tiene 60 segundos para
terminar; el worker deja de aceptar tareas y las termina o devuelve a la cola.

Configura recursos por separado en `api.resources`, `worker.resources`,
`frontend.resources` y `migration.resources`. La memoria de los hijos de ingesta
se suma al proceso padre. Ajusta `extraEnv.WORKER_INGEST_CHILDREN` y
`extraEnv.WORKER_INGEST_MEMORY_MB` junto al límite del pod. Escala con `api.replicas`,
`worker.replicas` y `frontend.replicas`, contando el pool de conexiones de cada proceso.

S3 conserva los archivos; el worker descarga su propia copia para ingerirlos. No
hace falta un sistema de archivos compartido ni un claim RWX. Caché y staging usan
volúmenes `emptyDir` limitados: su pérdida es esperada y no son backups. Un proceso
de ingesta matado puede dejar un archivo hasta reemplazar el pod; finalización
normal, errores del parser y cancelación eliminan la copia. Las fuentes de
sincronización de directorios locales deben ser accesibles desde el worker que
las ejecuta; el chart no monta directorios del operador.

## Actualización y rollback { #upgrade-and-rollback }

Antes de actualizar, respalda PostgreSQL, S3 y las claves. Revisa las release notes
y la compatibilidad de migraciones con la aplicación vieja y nueva. Un Job previo
a instalación/actualización ejecuta `agenticos db upgrade`. Si falla, Helm no
modifica los deployments. Los Jobs fallidos permanecen para diagnóstico:

```bash
kubectl -n agenticos logs job/agenticos-agenticos-migrate
helm history agenticos -n agenticos
```

Guarda los logs antes de reintentar: el siguiente hook elimina el Job anterior.
No ejecutes actualizaciones simultáneas de un release, no uses `--no-hooks` ni
arranques pods nuevos manualmente tras una migración fallida. Una migración
parcial requiere evaluación del operador; Helm no revierte efectos en la base.

Las actualizaciones progresivas necesitan esquemas y tareas de cola compatibles
mientras sigan vivos procesos antiguos. Para cambios incompatibles, detén el
tráfico, espera a que termine el trabajo activo, escala los tres deployments a
cero, respalda y actualiza en una ventana de mantenimiento. Comprueba disponibilidad
y una ejecución real antes de reabrir el tráfico.

En la primera actualización de un despliegue S3 existente a 1.63.0, deja terminar
la ingesta y reemplaza los workers antes de actualizar la API, o usa una ventana
de mantenimiento. La API nueva ya no escribe las copias compartidas que esperan
los workers antiguos. El almacenamiento local conserva el directorio compartido.

`helm rollback agenticos REVISION -n agenticos --wait --timeout 15m` restaura la
aplicación antigua solo si su hook acepta la base actual. No revierte el esquema.
Si la imagen antigua no reconoce una revisión nueva, el hook pre-rollback impide
reemplazar los pods. Cuando lo exijan las release notes, restaura deliberadamente
una copia compatible de la base, los objetos y las claves. `helm uninstall`
elimina la aplicación; bases externas, bucket y Secret siguen siendo del operador.

## Validación local y aceptación { #local-validation-and-acceptance }

Puedes probar ambas plataformas localmente, pero necesitan clústeres separados.
Usa kind para Kubernetes y [OpenShift Local (CRC)](https://crc.dev/docs/getting-started/)
para OpenShift real. Instalar `oc` en kind no añade SCC ni Routes. CRC admite
Apple silicon con el preset OpenShift, pero no con OKD.
Los [requisitos mínimos actuales](https://crc.dev/docs/installing/) de OpenShift
son cuatro núcleos físicos, 10,5 GB de memoria libre y 35 GB de disco, antes de
recursos adicionales para aplicaciones. No ejecutes ambos clústeres a la vez en un
portátil con recursos limitados.

La prueba smoke de Kubernetes crea servicios desechables de pgvector, Valkey, MinIO
y un simulador del protocolo del modelo; no necesita cuenta AWS ni clave de modelo
de pago. `SMOKE_IMAGE_TAG` fija el release de ambas imágenes. `SMOKE_BACKEND_IMAGE`
y `SMOKE_FRONTEND_TAG` reemplazan la imagen correspondiente para probar compilaciones
del código fuente.

```bash
python3 scripts/kubernetes/test_chart.py
SMOKE_IMAGE_TAG=1.80.0 scripts/kubernetes/run-smoke.sh
```

La prueba automática de consola solo confirma la configuración visual de OIDC;
no contacta con un proveedor de identidad. El simulador prueba el protocolo del run,
no la calidad del modelo. La prueba usa port-forwarding de ClusterIP y no valida
TLS público, WebSockets a través de un router, aplicación de CNI ni Argo CD.

Para OpenShift Local instala CRC de Red Hat y obtén tu propio pull secret.
Después prepara e inicia el preset OpenShift en el host:

```bash
crc config set preset openshift
crc setup
crc start
```

`crc setup` configura red y virtualización del host y puede necesitar permisos de
administrador. Sigue las instrucciones de acceso de CRC con un kubeconfig separado.
Verifica el clúster elegido antes de modificarlo. Prepara servicios de datos externos
accesibles, Secrets y cuenta de servicio como se indica arriba; instala con el perfil
OpenShift. No uses las dependencias de prueba kind como sustituto de validar
servicios compatibles con políticas restrictivas. Al terminar, usa `crc stop`.

Registra digests de imágenes, revisión del chart, versiones del clúster y Argo CD,
SCC admitida, comandos, resultados y logs sin datos sensibles. Antes de afirmar que
esta vía funciona, comprueba:

- La migración termina antes de cambiar workloads; un fallo deliberado impide el
  rollout. Una actualización y reversión compatibles conservan los datos.
- API, worker y consola permanecen listos bajo la política restrictiva prevista;
  navegar y subir archivos no produce errores de sistema de archivos de solo lectura.
- Funcionan bootstrap, acceso, respuesta del agent, carga, ingesta y job duradero.
- Ambas direcciones HTTPS, WebSockets, límites de carga, reenvío y aislamiento de red
  funcionan con el ingress o las Routes reales.
- OIDC funciona con proveedor, claims y restricciones de registro elegidos;
  los archivos sandbox persisten entre turnos y la limpieza termina correctamente.
- Con Argo CD, repite instalación, migración fallida, actualización y reversión con
  sincronizaciones completas; una ejecución Helm no valida GitOps.

El éxito local en OpenShift es evidencia para esa versión y configuración. Identidad
y red Azure, controladores de almacenamiento y configuración Argo CD del usuario
requieren validación en su entorno. Marca los puntos incompletos como no probados,
no como aprobados.

## Reproducir la prueba { #reproduce-the-test }

Instala Docker, kubectl 1.37.0, kind 0.33.0, Helm 4.3.1 y Python con PyYAML. Desde el
repositorio, ejecuta `python3 scripts/kubernetes/test_chart.py` y después
`scripts/kubernetes/run-smoke.sh`. El script crea y elimina su propio clúster kind,
usa un kubeconfig independiente y se niega a reemplazar un clúster existente. No
usa tu contexto actual de Kubernetes. Necesita libres los puertos 18000 y 13000.

Antes del primer release con este cambio, construye el backend desde el código
y establece `SMOKE_BACKEND_IMAGE=agenticos-smoke-backend:ci` y
`SMOKE_FRONTEND_TAG=1.62.8`, como el workflow Kubernetes. También prueba una
migración fallida, upgrade correcto, rollback con el mismo esquema y rollout con
UID arbitrario. Las bases y el bucket del fixture son servicios desechables de
un solo nodo, no manifiestos de producción. CI registra versiones de herramientas
e identificadores de imágenes. `SMOKE_KEEP_CLUSTER=true` conserva el clúster para
diagnóstico; elimínalo después con `kind delete cluster --name agenticos-smoke`.
