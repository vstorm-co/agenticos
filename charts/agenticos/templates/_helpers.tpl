{{- define "agenticos.name" -}}
{{- printf "%s-agenticos" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- define "agenticos.labels" -}}
app.kubernetes.io/name: agenticos
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
{{- define "agenticos.backendImage" -}}
{{- if .Values.image.backendDigest -}}
{{ .Values.image.backend }}@{{ .Values.image.backendDigest }}
{{- else -}}
{{ .Values.image.backend }}:{{ default (default .Chart.AppVersion .Values.image.tag) .Values.image.backendTag }}
{{- end -}}
{{- end -}}
{{- define "agenticos.frontendImage" -}}
{{- if .Values.image.frontendDigest -}}
{{ .Values.image.frontend }}@{{ .Values.image.frontendDigest }}
{{- else -}}
{{ .Values.image.frontend }}:{{ default (default .Chart.AppVersion .Values.image.tag) .Values.image.frontendTag }}
{{- end -}}
{{- end -}}
{{- define "agenticos.env" -}}
{{- $env := dict
  "ENVIRONMENT" "production"
  "POSTGRES_HOST" (required "postgres.host is required" .Values.postgres.host)
  "POSTGRES_PORT" .Values.postgres.port "POSTGRES_DB" .Values.postgres.database
  "POSTGRES_USER" .Values.postgres.user "POSTGRES_SSLMODE" .Values.postgres.sslMode
  "REDIS_HOST" (required "redis.host is required" .Values.redis.host)
  "REDIS_PORT" .Values.redis.port "REDIS_DB" .Values.redis.database "REDIS_SSL" .Values.redis.ssl
  "FRONTEND_URL" (required "public.siteUrl is required" .Values.public.siteUrl | trimSuffix "/")
  "PUBLIC_BASE_URL" (required "public.apiUrl is required" .Values.public.apiUrl | trimSuffix "/")
  "CORS_ORIGINS" (list (.Values.public.siteUrl | trimSuffix "/") | toJson)
  "RATE_LIMIT_TRUST_FORWARDED_FOR" .Values.trustedProxy.enabled
  "FILE_STORAGE_BACKEND" "s3"
  "FILE_STORAGE_S3_BUCKET" (required "storage.bucket is required" .Values.storage.bucket)
  "FILE_STORAGE_S3_REGION" .Values.storage.region "FILE_STORAGE_S3_ENDPOINT" .Values.storage.endpoint
  "FILE_STORAGE_S3_PATH_STYLE" .Values.storage.pathStyle "FILE_STORAGE_S3_PREFIX" .Values.storage.prefix
  "FILE_STORAGE_S3_ENCRYPTION" .Values.storage.encryption "FILE_STORAGE_S3_KMS_KEY_ID" .Values.storage.kmsKeyId
  "MEDIA_DIR" "/app/media" "MODELS_CACHE_DIR" "/app/models_cache"
  "XDG_CACHE_HOME" "/tmp/cache" "HF_HOME" "/app/models_cache/huggingface"
-}}
{{- if and .Values.trust.existingSecret (has .Values.postgres.sslMode (list "verify-ca" "verify-full")) }}
{{- $_ := set $env "PGSSLROOTCERT" (printf "/etc/agenticos/trust/%s" .Values.trust.postgresCaKey) }}
{{- end }}
{{- if .Values.trust.sslCaKey }}
{{- $_ := set $env "SSL_CERT_FILE" (printf "/etc/agenticos/trust/%s" .Values.trust.sslCaKey) }}
{{- end }}
{{- range $key, $value := mergeOverwrite (deepCopy .Values.extraEnv) $env }}
- name: {{ $key }}
  value: {{ $value | toString | quote }}
{{- end }}
{{- end -}}
{{- define "agenticos.security" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
{{- define "agenticos.mounts" -}}
- {name: tmp, mountPath: /tmp}
- {name: media, mountPath: /app/media}
- {name: data, mountPath: /app/data}
- {name: chroma, mountPath: /app/chroma_data}
- {name: models, mountPath: /app/models_cache}
{{- if .Values.trust.existingSecret }}
- {name: trust, mountPath: /etc/agenticos/trust, readOnly: true}
{{- end }}
{{- end -}}
{{- define "agenticos.volumes" -}}
- name: tmp
  emptyDir: {sizeLimit: 1Gi}
- name: media
  emptyDir: {sizeLimit: 2Gi}
- name: data
  emptyDir: {sizeLimit: 1Gi}
- name: chroma
  emptyDir: {sizeLimit: 1Gi}
- name: models
  emptyDir: {sizeLimit: 5Gi}
{{- if .Values.trust.existingSecret }}
- name: trust
  secret:
    secretName: {{ .Values.trust.existingSecret }}
    defaultMode: 0444
{{- end }}
{{- end -}}
