---
source_sha: "5a5072874712"
---

# Die Telefon-App { #the-phone-app }

Die Konsole funktioniert im Browser eines Telefons und lässt sich als App zum
Startbildschirm hinzufügen. Die AgenticOS-App für iOS und Android ergänzt, was nur
eine App kann: den Sperrbildschirm, die Dynamic Island, Widgets, das Teilen-Menü,
Push bei geschlossener App und eine eigene Sperre. Wie die
[Desktop-App](desktop.md) ist sie eine Shell um die Konsole des Deployments selbst,
also gehören Anmeldung, Berechtigungen und Mandantenprüfungen der Konsole.

> **Screenshot ausstehend — die Telefon-App, eine Live-Aktivität und die Widgets.**

Sie ist eine [Tauri](https://tauri.app)-App in `mobile/`, mit den nativen Hälften -
Swift für iOS, Kotlin für Android - unter `mobile/src-tauri/`.

## Anmelden { #signing-in }

**Einstellungen → Mobile App** in der Konsole zeigt einen QR-Code; scannt die App
ihn, ist sie als Sie angemeldet. Ein Code gilt einmal, eine Minute lang, und die
Sitzung des Telefons wird erst beim Scannen geöffnet, unter dem eigenen Namen des
Telefons. Die Adresse des Servers einzugeben und sich anzumelden geht auch. Die
Sitzung übersteht Neustarts, und die App sperrt sich nach fünf Minuten Abwesenheit
hinter Face ID, Touch ID oder dem Fingerabdruck.

**Aktive Sitzungen** unter Einstellungen → Profil listet jedes angemeldete Gerät:
„AgenticOS for iOS 0.2.0“ für die App, sonst den Browser, und welche davon Push
erhalten. Wer dort eine widerruft, meldet diese App sofort ab.

## Push { #push }

| Wo | Über | Eingeschaltet in |
|---|---|---|
| iPhone | Apples Push-Dienst, mit dem eigenen APNs-Schlüssel der Organisation (Admin → Einstellungen) | Einstellungen der App → Benachrichtigungen |
| Android | ntfy (ntfy.sh oder ein eigener Server des Unternehmens), nicht Google | Einstellungen der App → Benachrichtigungen, mit installierter ntfy-App |
| Ein Browser oder die zum Startbildschirm hinzugefügte Konsole | Web Push, mit dem eigenen Schlüssel des Deployments | Einstellungen → Benachrichtigungen |

Die Benachrichtigungen jedes Ereignisses - E-Mail, Push - werden je Ereignis unter
Einstellungen → Benachrichtigungen gewählt. Eine Benachrichtigung öffnet ihre Seite
durch die Sperre der App.

## Außerhalb der App { #outside-the-app }

**Live-Aktivitäten** - Sperrbildschirm und Dynamic Island auf iOS, eine laufende
Benachrichtigung auf Android - zeigen, was für Sie gerade läuft:

- Ihre laufenden Runs, mit einer Uhr;
- eine Freigabe, die auf Sie wartet, mit Reject und Approve;
- eine Frage, auf deren Antwort ein Agent wartet, die ihre Unterhaltung öffnet;
- ein laufender Sprachanruf, mit seiner Uhr, der sagt, wenn der Agent etwas fragt.

Eine Entscheidung vom Sperrbildschirm wartet auf Face ID oder den Fingerabdruck und
geht dann über dieselbe Anfrage wie die Knöpfe der Warteschlange.

**Widgets.** Das Übersichts-Widget zählt die auf Sie wartenden Freigaben und Ihre
laufenden Runs, mit dem Zeitpunkt der Zählung, und den verbleibenden Anteil des
monatlichen Budgets der Organisation, wenn sie eine Obergrenze hat. Das Widget der
angehefteten Agents öffnet einen neuen Chat mit einem Agent, den Sie auf seiner
Seite angeheftet haben; auf Android legt das Anheften auch eine Verknüpfung im
Launcher mit dem Gesicht des Agents an. Die Zahlen sind die der Konsole und werden
aktualisiert, wann immer sie sie liest.

**Kurzbefehle.** Das Menü bei langem Drücken des App-Symbols, Kurzbefehle und Siri,
die Aktionstaste und das Kontrollzentrum auf iOS sowie eine Kachel in den
Schnelleinstellungen auf Android starten einen Sprachanruf, ein Diktat, einen neuen
Chat oder die Freigaben.

**Mit AgenticOS teilen.** Das Teilen-Menü jeder App bietet AgenticOS an: Text,
Links, Fotos und Dateien (bis 20 MB je Stück) landen in einer neuen Nachricht.
Solange die App gesperrt ist, wird nichts angehängt.

## In der App { #in-the-app }

- **Ein Chat wie ein Messenger.** Das `+` im Eingabefeld öffnet Kamera, Fotos und
  Dateien, dann Spracheingabe und Befehle, den Anruf, das Modell und die Freigaben.
  Beim Öffnen des Chats wird ein gerade aufgenommenes Foto angeboten; nur die Fotos,
  die Sie antippen, kommen in die Nachricht.
- **Gesten.** Wischen Sie eine wartende Freigabe nach rechts, um sie zu erteilen,
  oder nach links, um sie abzulehnen, und ziehen Sie eine Seite nach unten, um sie
  neu zu laden, mit einem haptischen Tippen, wenn das Loslassen etwas auslöst.
- **Seiten bewegen sich wie die des Telefons.** Eine geöffnete Seite gleitet von der
  hinteren Kante herein, eine, zu der man zurückgeht, von der vorderen. Reduzierte
  Bewegung schaltet das ab.

## Ohne Netz { #without-a-network }

Die Telefon-App, die Desktop-App und die zum Startbildschirm hinzugefügte Konsole
halten sieben Tage lang eine Kopie auf dem Gerät: die Liste der Unterhaltungen, die
zwanzig zuletzt geöffneten Unterhaltungen mit ihren neuesten Dateien, die
Freigabe-Warteschlange und die Ausgaben, Fehler und wieder aufzunehmenden
Unterhaltungen des Dashboards. Die Kopie ist mit einem Schlüssel versiegelt, den
kein Skript auslesen kann, und wird beim Abmelden oder beim Wechsel der
Organisation gelöscht; ein einfacher Browser-Tab hält nichts.

Ohne Netz zeigt die Konsole diese Kopie unter einem Banner, das sagt, wann sie
gespeichert wurde. Eine offline geschriebene Nachricht wartet über dem Eingabefeld,
übersteht das Schließen der App und wird gesendet, wenn die Verbindung zurückkehrt;
eine, die der Server ablehnt, kommt mit „Nicht gesendet“ und dem Grund zurück.

## Stattdessen die Konsole installieren { #installing-the-console-instead }

In einem Browser, der sie installieren kann, bietet ein Streifen unter dem Kopf der
Konsole das an: eigenes Fenster, Push und ein Symbol auf dem Startbildschirm, ohne
die nativen Extras oben. Auf einem iPhone sagt er, wie - Teilen, dann Zum
Home-Bildschirm. Einmal geschlossen, kommt er in diesem Browser nicht wieder.

## Geräteverwaltung { #device-management }

Eine Organisation kann den Server festlegen, mit dem sich die App verbindet, ihn
sperren, damit niemand die App woandershin richtet, und die biometrische Sperre
erzwingen oder abschalten - die Schlüssel `serverUrl`, `serverLocked` und
`biometricLock` (`person` | `on` | `off`) in den verwalteten Konfigurationen von
Android und der verwalteten App-Konfiguration von iOS (AppConfig). Eine Richtlinie,
die sich nicht lesen lässt, wird ignoriert, statt jemanden auszusperren.

## Wo es im Baum liegt { #where-it-sits-in-the-tree }

- `mobile/src-tauri/src/` - die Rust-Plugins, die die Konsole aufruft:
  Live-Aktivitäten (`live.rs`), Widgets (`widget.rs`), Anheften, Teilen, Push und
  verwaltete Konfiguration.
- `mobile/src-tauri/ios/Sources/AgenticOSNative/` - die iOS-Plugins und die Typen,
  die die Widget-Erweiterung mit der App teilt.
- `mobile/src-tauri/gen/apple/Widgets/` - die Widgets, Steuerelemente und die
  Live-Aktivität.
- `mobile/src-tauri/gen/android/` - das Android-Projekt: die Plugins, die Widgets
  und ihre Layouts.
- `frontend/src/components/mobile/` - die Hälfte der Konsole: was gerade läuft, die
  Zahlen des Widgets, die Aktionen, die die App zurückgibt.

## Zusammenfassung { #recap }

- **Die Konsole bleibt auf dem Server.** Die App öffnet sie und ergänzt die eigenen
  Flächen des Telefons.
- **Live außerhalb der App**: Runs, Freigaben, Fragen und Anrufe auf dem
  Sperrbildschirm; Zahlen, Budget und angeheftete Agents auf Widgets.
- **Push ohne Google** auf Android, mit dem eigenen Schlüssel der Organisation auf
  dem iPhone.
- **Eine Kopie auf dem Gerät**, versiegelt, für den Fall ohne Netz.
