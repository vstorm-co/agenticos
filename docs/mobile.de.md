---
source_sha: "39d07d6f0165"
---

# Die Telefon-App { #the-phone-app }

Die native OAuth-Anmeldung verwendet S256 PKCE. Die App behält einen privaten Verifier; der Callback enthält nur dessen öffentliche Challenge. Der Verifier wird im Inhalt der Austauschanfrage gesendet, niemals in einer URL. Abmelden entfernt native Benachrichtigungsvorschauen auf dem Telefon.

Die Konsole funktioniert im Browser eines Telefons und lässt sich als App zum
Startbildschirm hinzufügen. Die AgenticOS-App für iOS und Android ergänzt, was nur
eine App kann: den Sperrbildschirm, die Dynamic Island, Widgets, das Teilen-Menü,
Push bei geschlossener App und eine eigene Sperre. Wie die
[Desktop-App](desktop.md) ist sie eine Shell um die Konsole des Deployments selbst,
also gehören Anmeldung, Berechtigungen und Mandantenprüfungen der Konsole.

> **Screenshot ausstehend — die Telefon-App, eine Live-Aktivität und die Widgets.**

Sie ist eine [Tauri](https://tauri.app)-App in `mobile/`, mit den nativen Hälften -
Swift für iOS, Kotlin für Android - unter `mobile/src-tauri/`.

## Verfügbarkeit und eigene Installation { #availability-and-self-installation }

!!! info "Mobile Builds dienen der Entwicklung, nicht der öffentlichen Verteilung"

    Wir bauen die mobile App in CI, veröffentlichen sie derzeit aber weder über
    TestFlight noch im App Store oder bei Google Play und bieten keinen unterstützten
    mobilen Release zum Download an. Wer die native App jetzt nutzen möchte, muss
    sie selbst bauen und installieren und mit einem eigenen oder vom Unternehmen
    betriebenen AgenticOS-Deployment verbinden. Ein gehosteter AgenticOS-Server
    oder Apple-Konten zum Signieren werden nicht mitgeliefert.

Der Workflow **Apps** baut eine Android-Debug-APK und eine unsignierte iOS-Simulator-App.
Das sind Entwicklungsprüfungen, keine Store-Releases. Ein iOS-Simulator-Build lässt
sich nicht auf einem echten iPhone installieren. Für ein echtes Gerät werden eigene
Signaturen und Provisioning-Profile für App und Erweiterungen benötigt.

Nach dem Klonen installierst du Rust und die Plattformwerkzeuge: Xcode auf macOS
für iOS oder Android SDK, NDK und JDK für Android. Danach:

```bash
cd mobile
bun install --frozen-lockfile
bun run ios        # iOS-Entwicklung auf macOS
# oder
bun run android    # Android-Entwicklung
```

Gib beim Start die Adresse deines Deployments ein. Sie muss vom Telefon erreichbar
sein; `localhost` auf dem Telefon bezeichnet das Telefon, nicht den Entwicklungsrechner.
Die [Browser-/Startbildschirm-Version](#installing-the-console-instead) funktioniert
auch ohne eigenen nativen Build.

Die öffentliche mobile Verteilung ist im Release-Workflow standardmäßig deaktiviert.
Eine spätere Aktivierung benötigt `AGENTICOS_MOBILE_RELEASES_ENABLED=true`; iOS braucht
zusätzlich `AGENTICOS_TESTFLIGHT_ENABLED=true` und die Signaturkonfiguration unter
[App-Releases](desktop.md#installers-and-updates). Die regulären CI-Builds bleiben aktiv.

## Anmelden { #signing-in }

Beim Scannen erscheinen zuerst Name und E-Mail-Adresse des Zielkontos. Bestätige das Konto, um dich anzumelden; Abbrechen lässt die aktuelle Sitzung unverändert. Die Vorschau verbraucht den Code nicht und verlängert seine Gültigkeit von einer Minute nicht.

**Einstellungen → Mobile App** in der Konsole zeigt einen QR-Code; scannt die App
ihn, können Sie die Anmeldung bei Ihrem Konto bestätigen. Ein Code gilt einmal, eine Minute lang, und die
Sitzung des Telefons wird erst nach Bestätigung geöffnet, unter dem eigenen Namen des
Telefons. Die Adresse des Servers einzugeben und sich anzumelden geht auch. Die
Sitzung übersteht Neustarts, und die App sperrt sich nach fünf Minuten Abwesenheit
hinter Face ID, Touch ID oder dem Fingerabdruck.

**Aktive Sitzungen** unter Einstellungen → Profil listet jedes angemeldete Gerät:
„AgenticOS for iOS 0.2.0“ für die App, sonst den Browser, und welche davon Push
erhalten. Wer dort eine widerruft, meldet diese App sofort ab.

Wenn die erste Verbindung oder die Rückkehr von der Anmeldung nach 30 Sekunden
noch nicht geladen ist, kehrt die App zum Serverformular mit der gespeicherten
Adresse und einem Verbindungshinweis zurück. Erneut versuchen oder eine andere
Adresse eingeben. Eine erfolgreich geladene Offlinekopie bleibt geöffnet.

## Verbindungsbereitschaft und gespeicherte Server { #connection-readiness-and-saved-servers }

Nach der Anmeldung prüft **Dieses Telefon fertig einrichten** das Konto, einen
verfügbaren veröffentlichten Agenten, die App-Sperre und Benachrichtigungen. Auch
bestehende Konten erhalten diese Prüfung bei fehlenden Einstellungen. Weiter
verschiebt optionale Schritte; **Einstellungen → Mobile App** öffnet sie erneut.
Ändert sich die Menge fehlender Einstellungen, erscheint die Prüfung wieder.
Kamerazugriff wird beim Scannen, Mikrofonzugriff beim Sprachstart angefragt, nie
durch diese Prüfung. Bei verweigerten iOS-Mitteilungen führt eine Schaltfläche zu
den Systemeinstellungen; bei der Rückkehr wird die Berechtigung neu geprüft.

**Einstellungen → Mobile App → Server wechseln** öffnet gespeicherte Verbindungen.
Benenne einen Server, scanne einen weiteren Code oder gib eine Adresse ein. Bis zu
20 Server sind möglich. Vorhandene Adressen werden automatisch übernommen. Die
Rückkehr öffnet das Dashboard mit der gespeicherten Sitzung. Cookies und
Offline-Daten werden nicht zwischen Ursprüngen kopiert; Abmelden oder Kontowechsel
löscht weiterhin den Kontocache. Server benötigen unterschiedliche Hostnamen:
Ports isolieren Cookies nicht. Das Entfernen eines Eintrags löscht keine
Browserdaten; melde dich vor der Weitergabe des Telefons zuerst ab.

Der Wechsel entfernt zuerst die Push-Registrierung des bisherigen Servers. Bei
bestehender Registrierung muss dieser erreichbar sein. Aktiviere Push auf dem
nächsten Server ausdrücklich. Gleichzeitiger Hintergrund-Push mehrerer Server wird
nicht eingerichtet. Organisationsvorgaben für Server und Sperre haben Vorrang;
das Abschalten der App-Sperre erfordert Geräteauthentifizierung.

Ein Wechsel löscht außerdem alte Live Activities, wartende Aktionen und Widget-
Pins. Native Benachrichtigungsklicks sind an die Anmeldung ihrer Push-
Registrierung gebunden; eine verspätete Mitteilung öffnet keine Unterhaltung auf
einem anderen Server.

Ein Wechsel des verknüpften Kontos entfernt bereits angezeigte Android-
Benachrichtigungen. Ein Serverwechsel entfernt außerdem angeheftete Agenten aus
den Schnellaktionen des iOS-App-Symbols.


## Datenschutz bei Benachrichtigungen { #notification-privacy }

Telefoneinstellungen gelten für die aktuelle Anmeldung. **Einstellungen →
Benachrichtigungen** kann den Text ausblenden; Chateinstellungen können eine
Unterhaltung stummschalten. Der Server wendet beides vor dem Versand an APNs oder
Web Push an, auch bei geschlossener App. Ein sichtbarer, fokussierter Chat erneuert
alle 30 Sekunden eine 90-sekündige Unterdrückung. Verlassen oder Hintergrundbetrieb
löscht den Fokus; nach einem Prozessabbruch verfällt er spätestens nach 90 Sekunden.
Dies betrifft Push, nicht den Posteingang oder laufende Live Activities.

Ein erfolgreicher Test bestätigt die Annahme durch den Push-Dienst, nicht die
Anzeige auf diesem Telefon. Prüfe Sperrbildschirm oder Mitteilungszentrale.
Android verwendet UnifiedPush und bietet bei fehlendem Verteiler eine
ntfy-Installationsanleitung. iOS unterscheidet fehlende APNs-Konfiguration der
Organisation von verweigerter Systemberechtigung. Firebase wird nicht hinzugefügt.


## Push { #push }

| Wo | Über | Eingeschaltet in |
|---|---|---|
| iPhone | Apples Push-Dienst, mit dem eigenen APNs-Schlüssel der Organisation (Admin → Einstellungen) | Einstellungen der App → Benachrichtigungen |
| Android | ntfy (ntfy.sh oder ein eigener Server des Unternehmens), nicht Google | Einstellungen der App → Benachrichtigungen, mit installierter ntfy-App |
| Ein Browser oder die zum Startbildschirm hinzugefügte Konsole | Web Push, mit dem eigenen Schlüssel des Deployments | Einstellungen → Benachrichtigungen |

Die Benachrichtigungen jedes Ereignisses - E-Mail, Push - werden je Ereignis unter
Einstellungen → Benachrichtigungen gewählt. Eine Benachrichtigung öffnet ihre Seite
durch die Sperre der App.

Push einer Anmeldung endet, sobald diese Sitzung widerrufen wird oder abläuft.
Ein verknüpftes Token wird nur verwendet, wenn seine Sitzung demselben Benutzer
gehört. Ältere Abonnements ohne gespeicherte Sitzung behalten ihre bestehende
Erlaubnis; entferne und registriere sie erneut, um sie dem aktuellen Gerät
zuzuordnen.

APNs-Vorschauen werden so gekürzt, dass die gesamte Nachricht in 4 KiB passt;
eine zu lange Ziel-URL öffnet das Dashboard. Ein falsches APNs-Topic oder eine
falsche Umgebung löscht die Geräteregistrierung nicht, damit die Konfiguration
korrigiert werden kann. Akzeptiert mindestens ein Gerät den Push vor Ablauf der
Frist, gilt der Versand als erfolgt und wird nicht erneut versucht.


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

Anmeldeformular und Chat passen in den sichtbaren Bereich über der Tastatur,
einschließlich Statusleiste und Gestenanzeige. Touch-Bedienelemente behalten auch
bei kleinen Symbolen eine ausreichend große Trefferfläche; Kopieren und
Ausblenden von Tipps bleiben ohne Mauszeiger sichtbar. Das native Anmeldeformular
wird nicht vom Cookie-Banner des Browsers verdeckt.

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
