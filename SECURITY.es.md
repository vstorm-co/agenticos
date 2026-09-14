---
source_sha: "5bb89334b619"
---

<!-- source_sha: 49074c4c262a -->

# Seguridad

[English](SECURITY.md) · [Polski](SECURITY.pl.md) · [Deutsch](SECURITY.de.md) · **Español**

> [!IMPORTANT]
> El texto en inglés es el que manda. Una traducción es una comodidad y, cuando
> los dos no coincidan, informa de la vulnerabilidad contra lo que dice el
> archivo en inglés.

## Informar de una vulnerabilidad

Correo: **kacper.wlodarczyk@vstorm.co** (o abre un aviso de seguridad privado en el repositorio). Incluye, por favor:

- La versión / el commit afectados
- Los pasos para reproducirlo
- Una valoración del impacto (exposición de datos / escalada de privilegios / DoS / …)

Aspiramos a acusar recibo en 48h y a entregar un arreglo en 7 días para los problemas de severidad alta.

---

## Modelo de seguridad

### Autenticación
- **JWT (`HS256`)** firmado con `SECRET_KEY`. TTL del access token = `ACCESS_TOKEN_EXPIRE_MINUTES` (30 min por defecto). TTL del refresh token = `REFRESH_TOKEN_EXPIRE_MINUTES` (7 días por defecto).
- **Hash de contraseñas:** bcrypt vía `passlib`. Las contraseñas en claro no se guardan nunca.
- **OAuth 2.0 (Google)** — flujo de código de autorización. El token se valida en el servidor y el registro interno de usuario se busca o se crea por correo.
- **Gestión de sesiones** — sesiones respaldadas por la base de datos, con revocación. Cada emisión de un refresh token crea una fila de sesión; el endpoint `/sessions` permite a los usuarios ver y revocar dispositivos.
- **Clave de API de administración** — la `settings.API_KEY` estática, comparada con la cabecera `X-API-Key` para las llamadas entre servicios. La comparación es de tiempo constante, con `secrets.compare_digest()`.

### Autorización

- **Basada en permisos** — la autoridad dentro de una organización es una fila de membresía más el catálogo de permisos (`app/core/permissions.py`). No hay columna de rol en el usuario ni dependencia de ruta basada en roles.
- **Roles de organización** — un rol es un nombre en la membresía (`owner` / `admin` / `builder` / `operator` / `member` / `viewer`) que se corresponde con un conjunto de permisos. Las rutas de colección ponen una puerta sobre un permiso; el acceso por recurso resuelve el rol junto con las concesiones explícitas, y una concesión amplía lo que permite un rol — nunca lo estrecha. Mira [Permisos](docs/permissions.es.md).
- **Scope del workspace** — toda petición autenticada resuelve una `ActiveOrg` (por defecto = la organización personal). Los recursos quedan acotados por la clave foránea `organization_id`.
- **Administración del despliegue** — el flag `is_app_admin` en un usuario, comprobado por su propia dependencia; no es un rol.

### Transporte / red

- **CORS** — la lista de orígenes sale de `settings.CORS_ORIGINS`. Restríngela a tus dominios en producción.
- **HTTPS** — imponlo con un proxy inverso (Nginx / Traefik / ALB). La cabecera Strict-Transport-Security se pone en el middleware cuando `ENVIRONMENT=production`.
- **Cabeceras de seguridad** — el frontend sirve una Content-Security-Policy completa (`default-src 'self'`, un `connect-src` que nombra solo este origen y los `PUBLIC_API_URL` y `PUBLIC_WS_URL` configurados, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`) más `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` y una `Permissions-Policy` que deniega la cámara y la geolocalización y permite el micrófono solo para la transcripción de voz. La política vive en `frontend/src/lib/csp.ts` y las cabeceras en `frontend/src/lib/security-headers.ts`, ambas afirmadas por tests; mira [El despliegue](docs/deployment.es.md#security-headers).

### Datos

- **Secretos** — se leen del entorno vía `pydantic-settings`. Nunca se confirman en el repositorio. Mira `backend/.env.example` y [Configuración](docs/configuration.es.md).
- **Registro de auditoría** — las acciones de app-admin (actualizaciones de usuario, borrados, suplantaciones) quedan registradas en la tabla `app_admin_audit_logs` con el actor + la IP + una instantánea de la carga útil. Las acciones a nivel de organización que cambian el acceso o gastan dinero llevan su propio rastro, con una puerta sobre `audit:read` — mira [Governance](docs/governance.es.md).
- **Documentos de RAG** — las subidas de archivos quedan acotadas por organización. No hay endpoint público de lectura; toda la recuperación ocurre en el servidor durante el chat.
- **Datos personales** — dónde residen, qué sale del despliegue y bajo qué ajuste, qué alcanza el borrado y qué no, con las lagunas abiertas nombradas: [Protección de datos](docs/data-protection.es.md).

### Lista de endurecimiento para producción

- [ ] Rota `SECRET_KEY` y `API_KEY` respecto a los valores generados por defecto.
- [ ] Pon `DEBUG=false` y `ENVIRONMENT=production`.
- [ ] Restringe `CORS_ORIGINS` a tu dominio o dominios.
- [ ] Ajusta `RATE_LIMIT_RUN_PER_MINUTE` / `RATE_LIMIT_EMBED_PER_MINUTE` en `.env`.
- [ ] Revisa los límites de frecuencia de cada superficie pública — el límite de
      mensajes por visitante del widget embed y el `rate_limit_rpm` por
      remitente de cada bot de canal. Las rutas de la propia consola no se
      miden.
- [ ] Detrás de un proxy o de una CDN, pon `RATE_LIMIT_TRUST_FORWARDED_FOR=true`
      **y** asegúrate de que la API no sea además alcanzable directamente — si
      no, todos los visitantes comparten un mismo cubo, o la cabecera se puede
      falsificar. El limitador lee el salto más a la derecha de
      `X-Forwarded-For` (el que añadió tu proxy), así que pon exactamente un
      proxy de confianza delante; con dos, colapsa la cabecera a un solo salto
      en tu borde.
- [ ] Impón HTTPS en la capa del proxy.
- [ ] Ejecuta `pip-audit` / `bun audit` en la CI para las vulnerabilidades de
      las dependencias.
- [ ] Configura copias de seguridad de la base de datos + un calendario de
      pruebas de restauración.

## Limitaciones conocidas

- **Sin 2FA / MFA** de serie.
- **Sin SAML / OIDC** más allá del OAuth de Google. Un SSO de empresa necesita una integración a medida con el IdP.
- **Sin redacción automática de PII** en los logs — ten cuidado con lo que registras.
