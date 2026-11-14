---
source_sha: "37f61b35dd4e"
---

# Desplegar en Kubernetes { #deploy-on-kubernetes }

`charts/agenticos` instala API, worker y consola desde imágenes publicadas.
Requiere PostgreSQL externo con pgvector, Redis/Valkey y un bucket S3 existente.
No instala bases de datos ni prepara sus copias de seguridad. `appVersion` define
la versión de imagen predeterminada. Fija otra versión con `image.tag` o imágenes
inmutables con `image.backendDigest` y `image.frontendDigest`.

Las imágenes de backend anteriores a 1.63.0 esperan archivos temporales de
ingesta compartidos y no son compatibles con este chart.


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
  tag: "1.63.0"
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
