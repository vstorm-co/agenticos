---
source_sha: "59b1d49e3e88"
---

# Por qué macOS muestra una advertencia { #why-macos-shows-a-warning }

Un DMG de AgenticOS descargado manualmente puede mostrar **Apple no pudo verificar esta aplicación**. Es la comprobación del editor de Gatekeeper. La versión predeterminada usa un certificado autofirmado estable que conserva la identidad de firma, pero no equivale a la notarización Developer ID de Apple. La advertencia no concede acceso a la pantalla ni al micrófono.

## Instalar una versión { #install-a-release }

Descarga solo desde [las versiones de AgenticOS](https://github.com/vstorm-co/agenticos/releases/latest). Mueve la aplicación a Applications, intenta abrirla una vez y después usa **Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente**, si tu organización lo permite. Sigue [las instrucciones de Apple](https://support.apple.com/es-es/102445). No desactives Gatekeeper globalmente.

También puedes usar `brew install --cask vstorm-co/agenticos/agenticos` o el [instalador del proyecto](https://github.com/vstorm-co/agenticos/blob/main/scripts/install_macos.sh). Instalan la versión y eliminan la cuarentena solo de esta aplicación. El script comprueba la suma de verificación y la huella fijada del editor. Una respuesta ausente o incorrecta del pin, una firma distinta o una suma incorrecta detienen la instalación. Antes de publicar la suma de Homebrew, el flujo de publicación monta ambas imágenes de Mac y verifica cada aplicación con la huella fijada del editor. Un pin ausente, una firma inválida u otro firmante detiene la publicación.

## Conservar permisos entre actualizaciones { #keep-permissions-across-updates }

Los permisos de grabación de pantalla y micrófono están vinculados a la identidad de firma. Conserva el mismo certificado entre versiones. Una compilación ad-hoc anterior o un certificado nuevo pueden exigir permisos otra vez. La firma de actualización no conserva por sí sola los permisos del sistema. Activa solo los necesarios en la configuración de la aplicación o en los ajustes de macOS.

## Configurar la firma de versiones { #configure-release-signing }

Los maintainers crean el certificado estable con `scripts/create_macos_signing_cert.sh`. Guarda `MACOS_SELF_SIGNED_P12` y `MACOS_SELF_SIGNED_P12_PASSWORD` como secretos y `MACOS_SELF_SIGNED_IDENTITY` como variable en `apps-release`. Publica solo la huella SHA-1 en `scripts/macos_signing_identity.txt`, nunca el P12 ni la contraseña. Tras publicar el pin, el instalador exige versiones firmadas con ese certificado.

La firma Developer ID y la notarización siguen siendo opcionales y requieren la cuenta Apple y credenciales del maintainer. La [configuración de versiones de escritorio](../desktop.md#installers-and-updates) las enumera. Una versión autofirmada no afirma estar notarizada.
