<!-- source_sha: c911383112ac -->

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

El modelo de amenazas, la declaración de flujo de datos (qué sale del deployment
y hacia quién), qué se cifra y dónde, y la matriz de controles — cada control
mapeado al mecanismo que lo satisface y al test que lo sostiene — viven en una
sola copia en la página
[Seguridad](https://vstorm-co.github.io/agenticos/security/) (`docs/security.md`).
Este archivo conserva solo las dos cosas para las que se lee el `SECURITY.md` de
un repositorio: cómo informar de una vulnerabilidad, arriba, y la lista de
endurecimiento para producción, abajo. Dónde viven los datos personales y qué
alcanza un borrado está en [Protección de datos](docs/data-protection.es.md); los
componentes que envían las imágenes y sus licencias, en
[Licencias](docs/licenses.es.md).

## Lista de endurecimiento para producción

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
