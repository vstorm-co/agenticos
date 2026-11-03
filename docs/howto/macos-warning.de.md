---
source_sha: "59b1d49e3e88"
---

# Warum macOS eine Warnung anzeigt { #why-macos-shows-a-warning }

Ein manuell heruntergeladenes AgenticOS-DMG kann **Apple konnte diese App nicht überprüfen** anzeigen. Gatekeeper prüft damit den Herausgeber. Das Standardrelease verwendet ein dauerhaftes selbstsigniertes Zertifikat. Es erhält die Signieridentität, ersetzt aber keine Developer-ID-Notarisierung durch Apple. Die Warnung erteilt keinen Bildschirm- oder Mikrofonzugriff.

## Ein Release installieren { #install-a-release }

Lade ausschließlich von [AgenticOS Releases](https://github.com/vstorm-co/agenticos/releases/latest) herunter. Verschiebe die App nach Applications, öffne sie einmal und wähle danach **Systemeinstellungen → Datenschutz & Sicherheit → Dennoch öffnen**, soweit deine Organisation dies erlaubt. Beachte [Apples Anleitung](https://support.apple.com/de-de/102445). Deaktiviere Gatekeeper nicht systemweit.

Alternativ verwende `brew install --cask vstorm-co/agenticos/agenticos` oder den [Projektinstaller](https://github.com/vstorm-co/agenticos/blob/main/scripts/install_macos.sh). Beide installieren das Release und entfernen die Quarantänemarkierung nur für diese App. Das Skript prüft Release-Prüfsumme und gespeicherten Herausgeber-Fingerprint. Fehlende oder fehlerhafte Pin-Antworten, falsche Signaturen und Prüfsummen stoppen die Installation. Vor der Veröffentlichung der Homebrew-Prüfsumme bindet der Release-Workflow beide Mac-Images ein und prüft jede App gegen den gespeicherten Herausgeber-Fingerprint. Ein fehlender Pin, eine ungültige Signatur oder ein anderer Signierer stoppt die Veröffentlichung.

## Berechtigungen über Updates erhalten { #keep-permissions-across-updates }

Bildschirmaufnahme- und Mikrofonfreigaben gehören zur Signieridentität. Verwende dasselbe Release-Zertifikat für weitere Versionen. Ein älterer Ad-hoc-Build oder ein neues Zertifikat kann erneute Freigaben erfordern. Die Updatesignatur allein erhält keine Betriebssystemberechtigungen. Aktiviere nur benötigte Freigaben im Assistenten oder in den macOS-Einstellungen.

## Release-Signierung konfigurieren { #configure-release-signing }

Maintainer erstellen das dauerhafte Zertifikat mit `scripts/create_macos_signing_cert.sh`. `MACOS_SELF_SIGNED_P12` und `MACOS_SELF_SIGNED_P12_PASSWORD` gehören als Secrets, `MACOS_SELF_SIGNED_IDENTITY` als Variable in `apps-release`. Committe nur den öffentlichen SHA-1-Fingerprint in `scripts/macos_signing_identity.txt`, niemals P12 oder Passwort. Nach Veröffentlichung des Pins verlangt der Installer damit signierte Releases.

Developer-ID-Signierung und Notarisierung bleiben ein optionaler Modus mit Apple-Account und Zugangsdaten des Maintainers. Die [Desktop-Release-Konfiguration](../desktop.md#installers-and-updates) führt sie auf. Selbstsignierung behauptet keine Notarisierung.
