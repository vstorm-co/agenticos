---
source_sha: "cd9dbfb49b0b"
---

# Die Desktop-App { #the-desktop-app }

Die native OAuth-Anmeldung verwendet S256 PKCE. Die App behält einen privaten Verifier; der Callback enthält nur dessen öffentliche Challenge. Der Verifier wird im Inhalt der Austauschanfrage gesendet, niemals in einer URL. Abmelden entfernt native Benachrichtigungsvorschauen auf dem Telefon.

Beim Trennen, Abmelden oder Serverwechsel werden Freigaben für Ordner, lokale Dienste, den gesamten Computer und den Bildschirm gelöscht. Die Kopplung zeigt das Konto an, bevor der Einmalcode verbraucht wird. Gemeinsame Ordnerfreigaben für Routinen bleiben bei Sitzungsablauf und erneuter Kopplung mit demselben verifizierten Konto und Server erhalten. Bis zur erneuten Identitätsprüfung bleiben sie inaktiv; explizites Trennen, Abmelden oder ein Server- oder Kontowechsel entfernt sie.

Ein veröffentlichter Delegat, der diesen Computer benötigt, kann im selben Chat um Freigabe bitten, auch wenn der Hauptagent in der Cloud läuft. Die Zustimmung gehört dem Hauptagenten, der den Lauf startet. Lokale Coding-Delegaten verlangen Vollzugriff; verschachtelte Delegaten nutzen den freigegebenen Gerätearbeitsbereich, ohne ihn anderen Cloud-Delegaten zugänglich zu machen. Abbruch oder Zeitüberschreitung eines Befehls beendet auch seine untergeordneten Prozesse.

AgenticOS läuft im Browser, und so nutzen es die meisten. Die Desktop-App ist für
alle, die mehr davon auf dem eigenen Computer wollen: die Konsole in einem eigenen
Fenster, eine schnelle Frage von überall, Blobby auf dem Desktop und - was ein
Browser nicht kann - die eigenen Agents, die in einem Ordner auf diesem Computer
und auf seinem Bildschirm arbeiten. Die Plattform selbst braucht sie nicht.

> **Screenshot ausstehend — die Desktop-App, Blobby und die schnelle Frage.**

Die Anwendung im Fenster ist dieselbe Next.js-Konsole, die der Server ohnehin
ausliefert, vom Server geladen, mit derselben Anmeldung, denselben Berechtigungen
und denselben Mandantenprüfungen wie ein Browser-Tab. Sie ist eine
[Tauri](https://tauri.app)-Shell in `desktop/`.

!!! note "Eine Shell, kein Build des Frontends"

    `frontend/` ist eine Next.js-Anwendung mit einer Serverhälfte - Route-Handler,
    die an das Backend weiterleiten, Sitzungs-Cookies, die sie setzen, eine
    Middleware, die die Sprache wählt, und auf dem Server gerenderte Seiten. Nichts
    davon läuft in einer Desktop-Binärdatei, also versucht es die Shell gar nicht:
    Sie öffnet die URL des Deployments wie ein Browser. Installiert wird das
    Deployment; die App ist der Weg, es zu öffnen.

Ohne gespeicherte Auswahl startet die Desktop-App mit dem **System**-Modus und
dem Stil **Glass**. Eine ausdrücklich gespeicherte Auswahl hat Vorrang.

Unter **Chat controls → Computer use** bietet **Lokaler Computer** dieser Unterhaltung Screenshot-, Maus- und Tastaturwerkzeuge, auch wenn der Agent keine Computer-use-Fähigkeit hat. Die Auswahl ist unabhängig von Browser und Work on: Sie gewährt weder Ordner- noch Befehlszugriff und ändert den veröffentlichten Agenten nicht. Die Person muss ihr eigenes gekoppeltes Gerät verbunden haben; die native Bildschirmzustimmung und Betriebssystemberechtigungen gelten weiterhin.

Bei der Rückkehr aus den Systemeinstellungen wird die Bereitschaft auch dann aktualisiert, wenn die Webview sichtbar bleibt. Ist die Bildschirmaufnahme aktiviert, der Zugriff aber weiterhin verweigert, beende und öffne die laufende Kopie erneut und aktualisiere den Status. Berechtigungen können zwischen einer installierten Version und einer Ad-hoc-Testkopie abweichen.

Lokale ACP-Aufgaben enden nach 16.384 eingehenden Ereignissen oder insgesamt 8 MiB serialisierten Updates, einschließlich der Sitzungswiedergabe. Der Fehler wird angezeigt und der Adapter geschlossen.

Ein eingecheckter Publisher-Zertifikat-Pin erfordert passendes Signaturmaterial: Fehlt MACOS_SELF_SIGNED_P12, stoppt das Release. Ad-hoc-Signaturen sind nur bei einer Distribution ohne Pin möglich.

## Die App installieren { #installing-the-app }

Lade das Paket für deinen Computer aus dem [GitHub-Release](https://github.com/vstorm-co/agenticos/releases/latest) herunter. Für die Installation eines Releases brauchst du weder Rust noch Entwicklungswerkzeuge.

- **macOS:** Wähle Apple silicon oder Intel, öffne die `.dmg` und ziehe AgenticOS entlang des Pfeils nach **Applications**. Starte die App aus Applications und wirf das Disk-Image aus.
- **macOS ohne Warnung:** `curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/install_macos.sh | bash` lädt das Release herunter, prüft seine SHA-256 gegen die mitveröffentlichte, kopiert die App nach Applications und entfernt von dieser einen App die Download-Markierung. `brew install --cask vstorm-co/agenticos/agenticos` macht dasselbe über [den Tap des Projekts](https://github.com/vstorm-co/homebrew-agenticos). Releases sind nicht von Apple beglaubigt, daher fragt eine im Browser geladene `.dmg` weiterhin nach **Trotzdem öffnen**. Sobald das Projekt das Zertifikat festlegt, mit dem seine Releases signiert sind (`scripts/macos_signing_identity.txt`), lehnt das Skript auch eine App ab, die anders signiert ist.
- **Windows:** Öffne den Installer `setup.exe`. Er verwendet die Systemsprache und installiert für deinen Benutzer ohne Administratorrechte. Starte AgenticOS aus dem Startmenü. Für verwaltete Installationen steht auch `.msi` bereit.
- **Linux:** Öffne `.deb` oder `.rpm` im Software-Installer deiner Distribution. Für eine portable Installation erlaube das Ausführen der `.AppImage` in ihren Dateieigenschaften und öffne sie.

Beim ersten Start führt dich der Assistent zur Serververbindung oder einer lokalen Instanz. Nur lokale Instanzen benötigen Docker; der Assistent erkennt es und bietet bei Bedarf einen Download an. Die Installation gewährt keinen Bildschirm- oder Mikrofonzugriff.

[Warum macOS diese Warnung anzeigt](howto/macos-warning.md).

### Desktop-Widgets unter macOS { #desktop-widgets-on-macos }

Starte unter macOS 14 oder neuer die installierte App einmal. Klicke dann mit der rechten Maustaste auf den Schreibtisch, wähle **Widgets bearbeiten** und suche nach **AgenticOS**. Das kleine Widget öffnet Quick Ask; das mittlere zusätzlich Chat, Inbox und Activity. Widgets folgen dem Systemdesign und enthalten nur Verknüpfungen ohne Kontodaten. Ein Klick startet niemals eine Aufnahme oder einen Anruf.

Die Release-CI baut native Pakete für Mac (Apple silicon und Intel), Windows und Linux. macOS-Pakete verwenden das stabile selbstsignierte Zertifikat. Ad-hoc-Signaturen sind nur ohne Publisher-Pin möglich; die Pakete sind nicht von Apple beglaubigt. Kopiere die App nach Applications und versuche, sie zu öffnen. Blockiert macOS sie wegen eines nicht verifizierten Entwicklers, wähle **Systemeinstellungen → Datenschutz & Sicherheit → Dennoch öffnen** und bestätige. Verwaltete Computer können diese Ausnahme verbieten. Siehe [Apples Anleitung](https://support.apple.com/de-de/102445). Heruntergeladene Updates benötigen weiterhin eine gültige Signatur mit dem Update-Schlüssel des Releases.

Nach einem Ad-hoc-Update kann macOS erneut Zugriff auf Mikrofon, Bildschirmaufnahme, Bedienungshilfen oder Schlüsselbund verlangen. Geht die Gerätekopplung verloren, verbinde das Gerät erneut. Update-Signaturen prüfen das Paket, bieten aber keine stabile Apple-Signierungsidentität.

Hat der Release-Workflow ein stabiles selbstsigniertes Zertifikat (`scripts/create_macos_signing_cert.sh` erzeugt eines), behält macOS die Berechtigungen für Bildschirmaufnahme und Mikrofon über Updates hinweg, weil sie an die Signaturidentität gebunden sind. Erzeuge es einmal und ersetze es nie: Ein neues Zertifikat fragt jede Person erneut. Selbstsignieren entfernt die Gatekeeper-Warnung nicht; das schaffen nur Developer-ID-Signatur und Beglaubigung.

## Starten { #running-it }

Der Assistent beginnt mit der Sprache und der Wahl zwischen lokalem
Arbeitsbereich und Organisationsserver. Bildschirmaufnahme, Bedienungshilfen
und Mikrofon sind optionale Funktionen in App readiness oder bei ihrer Nutzung;
sie sind keine Voraussetzung für die Wahl einer Verbindung.

Beim Verbinden der Desktop-App können Sie statt der Serveradresse den ursprünglichen Einladungslink einfügen. Die App verbindet sich mit dessen Server und öffnet die Einladung; das Ziel bleibt beim Anmelden erhalten. Die Einladung wird nicht automatisch angenommen und ihr Token nicht in den nativen Einstellungen gespeichert. Die optionale Verbindungsprüfung wartet, bis die Einladung abgeschlossen ist.

Nativer Start und Konsole unterstützen Englisch, Polnisch, Deutsch und Türkisch.
Die Auswahl wird an die Konsole übergeben; die gespeicherte Kontosprache hat
weiterhin Vorrang. Lokal wird ein Arbeitsbereichsname abgefragt; ein separater
Organisationsname ist eine erweiterte Option. Nach der Verbindungsprüfung öffnet
**Erste Schritte** den gemeinsamen Aufgabenstart. Ein lokaler Arbeitsbereich kann
Material an einen entfernten KI-Anbieter senden; lokal installiert bedeutet nicht Offline-KI.

Voraussetzungen sind Rust über [rustup](https://rustup.rs) und die Webview der
Plattform - WebKit auf macOS, WebView2 auf Windows, WebKitGTK auf Linux; Tauris
eigene [Seite der Voraussetzungen](https://v2.tauri.app/start/prerequisites/) hat
die Liste je Plattform. Die Tauri-CLI ist in `desktop/package.json` festgelegt, und
`make install` holt sie mit allem anderen.

```bash
make desktop-dev     # opens the shell
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

Beim ersten Start fragt die App, wo AgenticOS ist:

- **Auf diesem Computer.** Die App prüft Docker, richtet die veröffentlichten
  Images mit Konsole und API nur auf Loopback ein, legt Ihre Organisation und
  deren Besitzer an und startet, stoppt und aktualisiert diesen Stack danach aus
  der Menüleiste.
- **Auf dem Server Ihrer Organisation.** Geben Sie seine Adresse ein; ein bloßer
  Host (`agenticos.acme.com`) wird über HTTPS geöffnet. Sie melden sich in Ihrem
  eigenen Browser an (siehe [Anmelden](#signing-in)).

!!! warning "Einfaches `http://` nur für diesen Rechner"

    `localhost`, `127.0.0.1` und `::1` dürfen unverschlüsselt erreicht werden;
    jeder andere Host wird abgelehnt, bis er `https://` ist. Die Konsole sendet das
    Passwort und erhält das Token über diese Verbindung, und ein LAN ist genau der
    Ort, an dem jemand anderes mitlesen kann.

Eine Adresse, unter der nichts antwortet, wird ebenfalls abgelehnt: Die Shell
öffnet eine TCP-Verbindung, bevor sie die Webview irgendwohin richtet, weil WebKit
eine abgewiesene Verbindung als leeres weißes Fenster zeichnet.

Die Einstellungen liegen in `server.json` im Konfigurationsverzeichnis der App -
`~/Library/Application Support/co.vstorm.agenticos/` auf macOS,
`%APPDATA%\\co.vstorm.agenticos\\` auf Windows, `~/.config/co.vstorm.agenticos/` auf
Linux. Eine Datei, die sich nicht mehr lesen lässt, wird als `server.json.invalid`
beiseitegelegt und eine neue geschrieben. Der Server wird unter
**Einstellungen…** (`⌘,`), im Tray-Menü oder per Start mit `--server <address>`
geändert.

**Server wechseln…** befindet sich im Kontomenü am unteren Rand der
Konsolenseitenleiste. Öffnen Sie Ihren Kontonamen oder den Avatar in der
eingeklappten Leiste und wählen Sie den Eintrag, um das Verbindungsformular
zu öffnen. Er bleibt auch bei ausgeblendetem Blobby verfügbar.

### Docker und mehrere lokale Instanzen { #docker-and-multiple-local-instances }

Eine neue Instanz öffnet einen eigenen Schritt mit gruppierten Feldern für
Arbeitsbereich, Eigentümer und Anbieter. **Cancel** führt zur Instanzliste zurück.
Blobby bleibt während der Einrichtung verborgen und kehrt mit der Konsole
gemäß seiner gespeicherten Sichtbarkeit zurück.

Wähle **Set up this computer**, um die lokale Laufzeit vorzubereiten. AgenticOS
lädt Docker Desktop 4.97.0 für deinen Prozessor und prüft die festgelegte
SHA-256-Prüfsumme. macOS prüft den Installer mit Gatekeeper, verifiziert die
Signaturidentität von Docker Inc und fordert eine
Systemautorisierung an. Windows startet den signierten Installer; fehlende
WSL-Funktionen werden nach Systemautorisierung eingerichtet. Starte Windows bei
Aufforderung neu und öffne AgenticOS erneut. Ubuntu, Debian und Fedora auf x86-64
verwenden den System-Paketinstaller. Bestätige Dockers eigene Bedingungen beim
ersten Start.

Unter Linux ergänzt die Einrichtung bei Bedarf Dockers signierte
Paketquelle und fordert Administratorrechte für Pakete und KVM-Zugriff an.
Starte den Computer bei Aufforderung neu. Eine Statusprüfung allein installiert
keine Software.

Vor der Installation prüft AgenticOS auf 4 GB freien Speicherplatz. Der lokale
Stack benötigt außerdem mindestens 3 GB für die Engine sichtbaren Arbeitsspeicher.
Das sind Startprüfungen, keine Kapazitätsgarantie für jede Aufgabe. Image-Downloads
zeigen Fortschritt und sind auf 30 Minuten begrenzt. **Retry** setzt dieselbe
Instanz mit ihren vorhandenen Schlüsseln fort. Zur normalen Nutzung sind auf dem
Host weder Git, Python, uv noch Node.js erforderlich.

Neue Instanzen verwenden die mit der App gelieferte Plattformversion. Ein Update
der Desktop-App ersetzt nicht automatisch die Version einer laufenden Instanz.
**Update** lädt passende Plattform-Images, pausiert Schreibprozesse und sichert vor
dem Update Datenbank, Mediendateien und Bereitstellungsschlüssel im privaten
`backups/`-Verzeichnis der Instanz. Eine fehlgeschlagene Sicherung verhindert das
Update. Sicherungen enthalten personenbezogene Daten und müssen geschützt werden.
Migrationsfehler werden gemeldet; Datenbank-Downgrades erfolgen nicht automatisch.

Beim Öffnen startet AgenticOS den gespeicherten verwalteten lokalen Arbeitsbereich
automatisch, wenn er gestoppt ist, einschließlich der installierten Laufzeit auf unterstützten Systemen. Externe Server und nicht verwaltete Entwicklungsumgebungen werden nicht
gestartet. Die App übergibt Dockers CLI- und Anmeldehilfsprogramm-Verzeichnisse an
Kindprozesse, auch beim Start aus dem Finder. Du musst weder Dockers
Anmeldekonfiguration noch dein Shell-Profil bearbeiten.

Öffentliche Produkt-Images verwenden eine private anonyme Registry-Konfiguration,
um Abfragen von Anmeldehilfen und Schlüsselbund zu vermeiden. Deine bestehende
Docker-Konfiguration bleibt unverändert. Die lokale Installation lehnt Kontexte
ab, die auf eine entfernte Engine verweisen.

Wähle **New instance**, gib einen Namen sowie Organisation und Eigentümerkonto an.
Die App vergibt freie Loopback-Ports und erstellt ein eigenes Compose-Projekt mit
Datenbank, Dateivolume, Netzwerk, Arbeitsverzeichnis und Bereitstellungsschlüsseln.
Sitzungscookies erhalten einen Instanz-Namensraum, damit ein Wechsel die Anmeldung
einer anderen Installation nicht ersetzt. Die Frontend-Images müssen dies
unterstützen; ältere Images werden vor der Kontoerstellung und Sitzung abgelehnt.

Die lokale Ansicht zeigt gespeicherte Instanzen, Adressen und ihren Laufstatus.
**Start and connect** startet die gewählte Instanz; **Finish setup** wiederholt eine
unterbrochene Installation mit ihren vorhandenen Dateien und Schlüsseln. Start,
Stop und Update im Menü betreffen die verbundene verwaltete Instanz. Die Verbindung
zu einem extern gestarteten Entwicklungsstack macht diesen nicht appverwaltet.

Eine lokale Instanz betreibt API, Worker, Konsole, Datenbank und Redis, aber
keinen Sandbox-Dienst, keinen Browser-Dienst und keinen Objektspeicher. Agenten
erhalten den reinen Datei-Workspace. Wählen Sie unter **Chat controls → Tools & files**
**Work on → This computer** für Ordnerzugriff und **Browser → Local browser**
zum Browsen. **Computer use** gibt Bildschirm, Maus und Tastatur separat frei.

Metadaten liegen in `local-instances.json` im Konfigurationsverzeichnis; neue
Instanzdateien unter `local-stacks/<id>/` im Datenverzeichnis. Bestehende
`local-stack/`-Installationen behalten ihr Compose-Projekt und ihre Daten.
Passwörter und Anbieterschlüssel gelangen zum Bootstrap, ohne in diesen Dateien
oder Docker-Befehlsargumenten zu stehen. Bereitstellungsschlüssel bleiben in der
privaten `.env`; Anbieterschlüssel speichert der Servertresor. Der native Assistent
verwendet einen neutralen Tastaturfokus und fokussiert Auswahlknöpfe nicht automatisch.

## Verbindungseinrichtung und App-Bereitschaft { #connection-setup-and-app-readiness }

Das Kontomenü öffnet **App-Bereitschaft** direkt, auch aus den Desktop-Einstellungen. Die Checkliste ersetzt den schwebenden Einrichtungszähler und verdeckt keine Bedienelemente.

Die Verbindungsprüfung ist auf dem nativen Glasmaterial zentriert, auch wenn die
Konsole einen undurchsichtigen Stil verwendet. Die Statuszeilen bleiben beim Prüfen
sichtbar. Verbinden und Weiter zeigen sofort Fortschritt; das Dashboard wird
während der Einrichtung vorgeladen. Die Eingangsanimation beachtet reduzierte Bewegung.

Nach der Verbindung mit einem Server öffnet sich die App-Bereitschaft auch für
bestehende Konten. Sie prüft Anmeldung, Computerverbindung, verfügbare veröffentlichte
Agenten, Assistentenmodell, Tastenkürzel und macOS-Berechtigungen. Erst **Aktivieren**
fordert eine Berechtigung an. Optionale Schritte können offen bleiben; der Bereich
ist später unter **Einstellungen → Desktop-App** oder **Activity & Access** erreichbar.
Die Konsole merkt sich eine zurückgestellte Prüfung pro Konto, Organisation und
Server. Eine erneute ausdrückliche Verbindung bietet eine neue Prüfung an.
Prüffehler bleiben sichtbar und lassen sich erneut prüfen. Nach der Rückkehr aus
den Systemeinstellungen werden die Berechtigungen aktualisiert.

Fehler bei Screenshots und Bildschirmsteuerung verweisen auf Bildschirmaufnahme
oder Bedienungshilfen; Mikrofonfehler in Quick Ask führen zum selben Bereich.
Nach Freigabe der Bildschirmaufnahme kann die Reparatur die interaktive
Bereichsauswahl erneut öffnen. macOS kann einen Neustart der App verlangen.

**Einstellungen → Desktop-App → Benachrichtigungen** steuert Abschlüsse, Fehler,
Freigaben, Fragen und weitere Meldungen. Vorschauen sind standardmäßig ausgeblendet;
private Freigabemeldungen öffnen die Anfrage in der App statt einer blinden
Bestätigung. In den Chat-Einstellungen lassen sich einzelne Unterhaltungen stummschalten.
Während die entsprechende Unterhaltung in der Konsole oder Quick Ask fokussiert ist,
wird die Meldung unterdrückt. Systemberechtigungen und der macOS-Fokus bestimmen
weiterhin die Zustellung.

**Activity & Access** zeigt laufende Arbeit und wartende Anfragen. Ein Eintrag öffnet
die Konsole; **Stop** ist verfügbar, wenn diese App die ursprüngliche Verbindung
der Unterhaltung hält. Andere Serverläufe bleiben über **Open** erreichbar.
Das Menü widerruft auch einzelne Ordner- oder Computerfreigaben und gibt die
Bildschirmsteuerung zurück.

Die Kopfzeile bietet **Neuer Chat** (`⌘N` oder `Strg+N`), den Wechsel zur Konsole
und Schließen. Ein neuer Chat setzt Gesprächsauswahl und Entwurfskontext zurück;
der Editor bleibt unter dem Verlauf und hat eine sichtbare Senden-Schaltfläche.

Quick Ask unterstützt `@mention` mit denselben Ressourcen wie der Chat-Editor.
Pfeiltasten und Enter oder Tab wählen aus; Escape schließt zuerst die Vorschläge.
Das Löschen einer Erwähnung entfernt ihre Ressourcenbindung aus der nächsten Nachricht.

## Eine Anwendung, kein Tab { #an-application-not-a-tab }

Auf macOS trägt die Seitenleiste der Konsole die Fensterknöpfe und zieht das
Fenster, das Fenster merkt sich Größe und Position, und Schließen lässt die App in
der Menüleiste. Die Menüleiste hat File, Edit, View, Go (`⌘1`-`⌘5`, `⌘[` und `⌘]`)
und Window; ein Tray-Menü tut dasselbe auf Windows und Linux. Native
Benachrichtigungen tragen Approve und Reject für eine wartende Freigabe, und Dock
oder Taskleiste zeigen, wie viele warten. **Einstellungen → Desktop-App** öffnet
die App bei der Anmeldung, hält sie bei geschlossenem Fenster am Laufen und schaltet
die Plakette an oder aus.

Über dem Inhalt liegt eine eigene Zeile zum Ziehen des Fensters, außerhalb des
Scrollbereichs. Seitenaktionen und Schließen-Schaltflächen bleiben dadurch
anklickbar. Der Web-Architect bleibt am rechten Rand der Desktop-Konsole und
fährt beim Darüberfahren aus; die Ecke bleibt für Kartenaktionen und Blobby frei.

Der Chat füllt den Inhaltsbereich ab der Oberkante, ohne eigene Ziehleiste oder
Seitenabstand. Das Fenster lässt sich am Kopf der Chatliste ziehen; die Schaltflächen
bleiben anklickbar.

**Erscheinungsbild** im Kontomenü bietet den Hell-/Dunkelmodus sowie Standard,
Glass, Graphite, Midnight und Paper mit Vorschauen. Der Menüeintrag nennt den
aktuellen Stil. Es sind dieselben Einstellungen wie unter
**Einstellungen → Profil → Erscheinungsbild**; ein Stilwechsel behält den
Farbmodus bei und bleibt nach einem Neustart erhalten.

**Angeheftete Agents**: Die Seite eines Agents bietet „An Dock anheften“ (sonst an
die Taskleiste). Ein angehefteter Agent steht im Dock-Menü und im Tray-Menü, einen
Klick von einem neuen Chat mit ihm entfernt. Eine Datei, die auf das Dock-Symbol
oder auf Blobby fallen gelassen wird, startet einen Chat mit dieser Datei im
Anhang.

## Blobby { #blobby }

Ein Wesen im Stil der Agent-Avatare, das auf dem Desktop sitzt, während die
Konsole offen, minimiert oder geschlossen ist: einer aus einer Besetzung von sechs,
das Gesicht eines Ihrer Agents oder ein eigenes Gesicht. Es sagt, wenn eine
Freigabe wartet, etwas Neues im Posteingang ist oder Ihre Runs laufen, und öffnet
es per Klick. Ziehen Sie es irgendwohin; ziehen Sie es mit zwei Fingern auf, scrollen
Sie mit gedrücktem `⌘` darüber oder nutzen Sie den Regler in den Einstellungen, um
die Größe zu ändern. Sein eigener Tab in den Einstellungen wählt die Figur, wie
gesprächig sie ist und ob sie überhaupt Aktivität zeigt.

Sein Fenster ist transparent, was auf macOS `macOSPrivateApi` in `tauri.conf.json`
braucht - und das schließt den Mac App Store aus, wohin eine selbst gehostete
Konsole ohnehin nicht wollte.

## Schnelle Frage und Sprache { #quick-ask-and-voice }

**AgenticOS öffnen** (`⌘⇧O` unter macOS, sonst `Ctrl+Shift+O`) bringt die Konsole
aus jeder App nach vorne. Ändern oder löschen Sie die Belegung unter
**Einstellungen → Tastenkürzel**. Menüleiste, Tray und Blobby zeigen die aktiven
Kürzel zum Öffnen von AgenticOS, für Schnelle Frage und Screenshot zu neuem Chat.
Änderungen werden sofort übernommen. Nicht registrierbare Kürzel erscheinen
nicht im Menü.

**Schnelle Frage** (`⌥Space`, änderbar) öffnet ein schwebendes Feld, um einen
beliebigen Agent von überall zu fragen, ohne die Konsole nach vorn zu holen. Auf
macOS kann sie mitnehmen, was Sie gerade angesehen haben: den in einer anderen App
markierten Text, die Zwischenablage oder die im Finder ausgewählten Dateien - jedes
vor dem Senden gezeigt und nur, wenn Sie AgenticOS das Lesen der Auswahl erlaubt
haben.

Halten Sie `⌥⇧Space`, um in die schnelle Frage zu diktieren; ein Sprachanruf mit
dem Standard-Agent hat ein eigenes Kürzel. **Einstellungen → Tastenkürzel** belegt
sie alle neu: Eine Kombination braucht mindestens eine Sondertaste, eine, die schon
eine andere App hält, wird abgelehnt und die alte Belegung bleibt, und
**Löschen** schaltet sie ab.

**Screenshot in einen neuen Chat** (`⌘⇧A`) zeigt das Fadenkreuz des Systems; der
gewählte Bereich landet in einem neuen Chat, schon angehängt. Der erste Druck
fragt macOS nach Bildschirmaufnahme, die nach einem Neustart greift.

Quick Ask behält das vollständige Gespräch: Ihre Fragen, frühere Antworten sowie
Werkzeugaktivitäten und Ergebnisse nutzen die Nachrichtenansicht der Konsole.
Freigaben, Rückfragen und Verbindungsanfragen lassen sich im Panel beantworten.
Offline wartender Text bleibt sichtbar; die Stopptaste beendet den Run. Anhänge und
zitierte Quellen öffnen sich im Panel. Nach oben scrollen pausiert das automatische
Folgen, bis Sie zum Ende zurückkehren.

Wählen Sie Dateien über die Büroklammer, fügen Sie ein Bild aus der Zwischenablage
ein oder ziehen Sie Dateien auf Quick Ask. Anhänge erscheinen vor dem Senden und
lassen sich einzeln entfernen. Es gilt dieselbe Upload-Grenze wie im Chat. Senden
und ein neuer Chat warten, bis alle Uploads abgeschlossen sind. Ein fehlgeschlagener
Upload erhält den Nachrichtenentwurf. Dateien lassen sich auch ohne Text senden.

Die Stecknadel hält Quick Ask über anderen Anwendungen sichtbar, wenn Sie außerhalb
des Fensters klicken. Lösen Sie die Stecknadel, um das automatische Ausblenden bei
Fokusverlust wiederherzustellen. Schließen, Escape im Eingabefeld und das Quick-Ask-
Tastenkürzel können das angeheftete Panel weiterhin ausblenden. Die Einstellung gilt
für die aktuelle Desktop-Sitzung, auch nach einem Neuladen der Seite.

## Auf diesem Computer arbeiten { #work-on-this-computer }

Lokale Dateioperationen arbeiten relativ zu einem offenen Handle des freigegebenen Verzeichnisses. Ein durch einen symbolischen Link ersetztes Verzeichnis oder eine Datei kann Schreibzugriffe nicht nach außen umleiten. Das freigegebene Verzeichnis und seine übergeordneten Verzeichnisse werden ohne Folgen symbolischer Links geöffnet; Vorschau und Dateilisten nutzen dieselbe Grenze.

Das eine, was ein Browser nicht kann: Ein Desktop-Chat
kann statt in der Cloud in einem Ordner auf dem Computer arbeiten, auf dem die App
läuft. Die Datei- und Shell-Werkzeuge des Agents - auflisten, lesen, schreiben,
bearbeiten, ausführen - erreichen diesen Ordner über die App.

**Den Computer einmal verknüpfen.** Wählen Sie in den Chat-Einstellungen
**Arbeiten auf → Dieser Computer**, um ihn direkt zu verknüpfen. Bestätigen Sie im
nativen Dialog und wählen Sie anschließend im selben Bereich einen Ordner und
seinen Zugriffsmodus. **Einstellungen → Desktop-App → Dieser Computer → Diesen
Computer verknüpfen** bietet dieselbe Aktion. Die App erhält eine eigene Sitzung
für diesen Computer und speichert ihr Refresh-Token im Schlüsselbund des Systems.
Sie hält eine ausgehende WebSocket-Verbindung zum Device-Hub des Servers
(`/api/v1/ws/device`); auf dem Computer lauscht nichts. **Trennen** beendet die Sitzung; es fragt vorher
nach und nennt, was es löscht.

**Pro Chat wählen.** In der Desktop-App bieten die Einstellungen eines Chats
**Arbeiten auf (Work on): Cloud / Diesem Computer**. Die Wahl dieses Computers
fragt im nativen Auswahldialog nach einem Ordner und danach, wie weit der Agent
darin gehen darf:

Dieser Computer wird erst nach der Freigabe eines Ordners ausgewählt. Die
Zugriffsauswahl zeigt den genehmigten Modus dieses Ordners; eine Änderung öffnet
die native Ordnerauswahl erneut, um die neue Berechtigung zu bestätigen.
Abbrechen behält die bisherige Auswahl bei. Ordner und Modus bleiben ausgewählt,
wenn die Einstellungen geschlossen werden und ein neuer Chat seine ID erhält.

| Modus               | Was der Agent darf                                           | Wie das durchgesetzt wird                                                                                                       |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Nur lesen           | Dateien lesen; nichts wird geschrieben und kein Befehl läuft | Die App lehnt Schreibzugriffe und Befehle ab                                                                                    |
| Im Ordner schreiben | Lesen, im Ordner schreiben, Befehle ausführen                | Befehle laufen unter Seatbelt auf macOS und bubblewrap auf Linux, schreibbar nur im Ordner und in den temporären Verzeichnissen |
| Vollzugriff         | Befehle laufen als Sie, ohne Sandbox                         | Jeder Befehl wird zuerst in einem nativen Dialog zur Freigabe gezeigt                                                           |

Ordnerbefehle dürfen den freigegebenen Ordner und System-Laufzeitdateien lesen,
aber keine anderen Dateien im Home-Verzeichnis oder geerbte Anmeldedaten der
Anwendung. Dafür ist eine separate Freigabe des ganzen Computers nötig. Direkte
lokale Lese- und Schreibzugriffe sind auf 10 MiB begrenzt, damit große Transfers
die Geräteverbindung nicht trennen. Größere Schreibvorgänge werden vor der
Kodierung und Übertragung der Dateidaten abgelehnt.

Windows bietet Nur lesen und Vollzugriff. Linux bietet Schreiben im Ordner nur,
wenn `bwrap` mit Unterstützung für `--bind-fd` installiert ist. Die App hält bis zum Sandbox-Start ein ohne Folgen symbolischer Links geöffnetes Verzeichnishandle fest. Umbenennen oder Ersetzen des Ordners durch einen symbolischen Link kann das genehmigte Verzeichnis dadurch nicht ändern. Unter Linux werden Umgebungsvariablen der Aufgabe innerhalb der Sandbox gesetzt, nicht in ihrem Startprozess; ihre Werte werden über einen privaten Deskriptor übergeben.

Der Stammpfad eines Routine-Ordners darf keine symbolischen Links oder Junctions enthalten. Wählen Sie im Dialog den tatsächlichen Ordner; die Hintergrundzulassung löst keine Links im Stammpfad auf.

**Der Computer entscheidet, nicht der Server.** Die gewählten Ordner mit ihren
Modi stehen in den Einstellungen der App, und jede Operation nennt einen Ordner und
einen Modus, die die App damit abgleicht: ein Ordner, den Sie nie gewählt haben,
ein Modus, der weiter geht als erlaubt, oder ein Pfad, der aus dem Ordner
herausführt, wird auf dem Computer abgelehnt, egal was der Server verlangt hat. Die
Wahl wird je Unterhaltung gespeichert. Neue Chats übernehmen die letzten Ordner-
und Werkzeugeinstellungen dieses Kontos und dieser Organisation; Projekteinstellungen
haben Vorrang. Die im Chat erteilte Zustimmung zum gesamten Computer wird niemals
übernommen; eine einem Agenten erteilte Zustimmung gilt für diesen Agenten (siehe
**Gesamter Computer**).

**Nur Ihre eigenen Runs.** Ein Chat erreicht Ihren Computer nur, wenn er Ihr
eigener ist - nie ein API-Schlüssel, ein Widget-Besucher oder der Chat eines
anderen - und ein [Trigger](triggers.md) nur, wenn er als sein Ersteller handelt,
der ihm unter **Arbeiten auf** des Triggers einen Ordner seines Computers zuweist.

**Im interaktiven Chat: Wenn der Computer weg ist.** Ein Run, der diesen Computer angefordert hat und die
App nicht verbunden vorfindet, wartet bis zu zehn Minuten auf sie, und der Chat
sagt es. Eine Operation, die die App mitten im Run getrennt vorfindet - Deckel zu,
Netz gewechselt -, wartet bis zu fünf Minuten auf ihre Rückkehr in derselben
Sitzung und macht dann weiter. Solange eine Operation eines Runs läuft, sagt der
Tray, dass ein Agent auf diesem Computer arbeitet.

Der Server prüft die Sitzung vor jeder lokalen Operation. Widerrufene oder abgelaufene Sitzungen verweigern neue Arbeit; der Heartbeat schließt auch inaktive Verbindungen. Laufende Operationen werden beim Schließen der Desktop-Verbindung abgebrochen.

Im Builder speichert **Sandbox → Computer** `backend: local` ohne Pfad oder
native Zustimmung. Jede Person erlaubt ihr eigenes Ziel im Desktop-Chat. Ein
solcher Agent hat keinen Cloud-Workspace, daher bietet **Work on** für ihn keine
Cloud an.

Du kannst ihm
schreiben, bevor du etwas erlaubst: Er beantwortet, was keine Dateien braucht, und
erst wenn eine Anfrage deine Dateien braucht, fragt er, wo er arbeiten darf -
**Gesamter Computer** oder ein Ordner. Der Lauf wartet auf deine Wahl, danach setzt
der Chat von selbst mit den Dateien fort. Die Antwort wird für diesen Agenten auf
diesem Computer gespeichert, sodass seine späteren Chats ohne Nachfrage dort
beginnen. In der Web-Konsole, wo es keinen Computer freizugeben gibt, sagt er, dass
er deine Dateien nicht erreicht. Beim Erstellen
eines Projekts öffnet **Projekt-Sandbox → Computer · Ihre Dateien** die persönliche
Ordnerauswahl; andere Mitglieder behalten den gemeinsamen Projekt-Workspace.

**Gesamter Computer.** Im Desktop-Chat ist **Gesamter Computer** ohne
Ordnerauswahl verfügbar. Eine native Warnung erlaubt den Zugriff: Für einen
Agenten mit dem Workspace **Computer** nennt die Warnung den Agenten, und die
Zustimmung gilt für ihn in jedem Gespräch; sonst gilt sie für dieses Gespräch.
Dateiwerkzeuge erreichen absolute Pfade im Rahmen Ihres Kontos; Befehle laufen als
Sie, ohne einzelne native Bestätigungen. Systemberechtigungen und Freigaberegeln des
Agents gelten weiterhin. **Zugriff auf den gesamten Computer widerrufen** oder
**Cloud** blockiert neue Operationen; laufende Befehle werden nicht abgebrochen.
Die Zustimmung übersteht Neustarts und gilt für diesen Server und den Agenten oder
das Gespräch; bei einem Entwurf wird die Zustimmung eines Gesprächs mit der ersten
Operation gebunden. Ein neuer Chat mit einem anderen Agenten braucht eine eigene
Zustimmung. Dieser Modus durchsucht das Heimatverzeichnis nicht und
sammelt Dateien nicht automatisch als Anhänge.

Lokale Browser- und Dateiwerkzeuge sind im Desktop-Chat auch ohne Browser- oder
Sandbox-Bindung des Agents verfügbar. Die Auswahl ergänzt nur diesen Run, erhält
Domainbeschränkungen und Freigaberegeln und ändert den veröffentlichten Agent nicht.
Interne Anhang-Snapshots verwenden Dateilisten statt Shell-Befehle.

## Der Bildschirm { #the-screen }

[Computer Use](reference/capabilities.md) kann den Bildschirm dieses Computers
steuern. In einem Chat, der auf diesem Computer arbeitet, ist sein Desktop `auto` -
der Standard - dieser Bildschirm; `local` verlangt nichts anderes.

- **Erst gefragt.** Der erste Screenshot einer Sitzung fragt in einem nativen
  Dialog, ob der Agent diesen Bildschirm für eine Stunde sehen und steuern darf.
- **Umrahmt, während er handelt.** Ein Rahmen umgibt den Bildschirm, solange der
  Agent ihn hält.
- **Sofort zu stoppen.** `⌘⌥Esc` (sonst `Ctrl+Alt+Esc`) nimmt den Bildschirm
  zurück; die nächste Aktion wird abgelehnt, bis Sie es wieder erlauben.
- **Das Betriebssystem fragt auch.** macOS braucht AgenticOS unter Datenschutz &
  Sicherheit sowohl in Bildschirmaufnahme als auch in Bedienungshilfen; eine
  Ablehnung nennt beide.

Jeder Desktop, auf dem ein Run arbeitet, dieser eingeschlossen, wird live im Chat
und in der Live-Ansicht des Runs gezeigt, wo **Übernehmen** ihn Ihnen zwischen den
Schritten des Agents überlässt und **Zurückgeben** ihn zurückgibt. Die Live-Ansicht
des Bildschirms dieses Computers gehört nur Ihnen, wer auch immer sonst Runs ansehen
darf.

## Anmelden { #signing-in }

Das Desktop-Hauptfenster reserviert die Ziehleiste getrennt von einem kompakten oberen Inhaltsabstand von 16px. Unter macOS haben die Fensterknöpfe eine reservierte Zeile von 32px. So bleiben die Marke in der Seitenleiste und die Seitenüberschrift ohne den zusätzlichen oberen Abstand des Browserlayouts ausgerichtet.

Konsole, Blobby und Quick Ask teilen ein benanntes dauerhaftes WebView-Profil; private
Agent-Browser-Tabs bleiben isoliert. Der Wechsel von einem älteren Profil kann eine
einmalige Anmeldung erfordern. Unter Glass entspricht der Ziehbereich dem
Inhaltshintergrund. Das Dashboard glättet Tastaturnavigation und diskrete
Mausradschritte, während feine Trackpad-Eingaben nativ bleiben; reduzierte Bewegung
deaktiviert die Glättung.

Die Konsole behält ihre Sitzung in dauerhaften HttpOnly-Cookies, einschließlich eines
bei Nutzung erneuerten Refresh-Cookies. Beim erneuten Öffnen wird die noch gültige
Sitzung wiederhergestellt. Vorübergehende Serverfehler und Ratenlimits behalten das
Desktop-Konto; nach Wiederherstellung der Verbindung oder beim Aktivieren des Fensters
wird die Sitzung erneut geprüft. Abgelehnte oder widerrufene Tokens erfordern weiterhin
eine Anmeldung. Ohne lokal verfügbares Konto zeigt ein unerreichbarer Server eine
Wiederholung statt der Anmeldeseite.

Die eine Navigation, die das Konsolenfenster verweigert. Alles andere lädt im
Fenster; ein Klick auf **Continue with Google** öffnet sich stattdessen in Ihrem
eigenen Browser, und das Ergebnis kommt zur App zurück (#1532).

Was passiert, der Reihe nach:

1. Das eigene `/api/oauth/<provider>/login` der Konsole läuft **im Fenster**, wo es
   das httpOnly-Cookie mit einer vorgemerkten Einladung lesen und anhängen kann.
2. Das Fenster sieht dann eine Navigation zu `/api/v1/oauth/<provider>/login` des
   _Deployments_, übergibt sie mit angehängtem `client=desktop` und frisch
   erzeugtem `desktop_nonce` an den System-Browser und folgt ihr nicht.
3. Sie melden sich dort an, in einem echten Browser mit Ihren eigenen Passwörtern,
   Erweiterungen und welchem zweiten Faktor auch immer.
4. Der Callback des Deployments erkennt, dass dieser Versuch ein Desktop-Versuch
   war - zu _Beginn_ in der Sitzung unter dem OAuth-`state` dieses Versuchs
   vermerkt, nie aus der Rückkehr gelesen - und leitet nach
   `agenticos://auth/callback?code=…` weiter, mit einem Einmal-Code, der nach einer
   Minute abläuft, und der erhaltenen Nonce.
5. Das Betriebssystem übergibt diesen Link der App. Die Shell schickt das
   Konsolenfenster nach `<your server>/auth/callback?code=…`, das den Code von
   Server zu Server gegen das Token-Paar tauscht; die Cookies des Fensters selbst
   werden gesetzt.

**Einen Deep Link kann jeder Prozess auf Ihrem Rechner auslösen**, also ist eng
gefasst, was einer hier darf: die Konsole an einen Pfad schicken, auf dem Server,
den _Sie_ konfiguriert haben, mit einem Code, der genau einmal einlösbar ist - und
nur einer mit der Nonce, die diese App für diesen Versuch erzeugt hat. Auf Windows
und Linux gibt eine Einzelinstanz-Sperre die Argumente eines zweiten Starts an den
ersten weiter. Das Deployment muss beim Schema übereinstimmen -
`DESKTOP_DEEP_LINK_SCHEME`, `agenticos`, sofern niemand es geändert hat - und bei
seiner eigenen öffentlichen Adresse.

## Was sie bewusst nicht tut { #what-it-deliberately-does-not-do }

- **Kein Navigationswächter.** Ein Link, der den Origin des Servers verlässt,
  öffnet sich im Fenster, weil manche OAuth-Abläufe - das Verbinden eines Kontos für
  ein Terminal - zur selben Webview zurückkehren müssen, damit ihr Cookie ankommt.
  Der Fenstertitel nennt jeden anderen Host, den es zeigt. Das Verbinden eines
  MCP-Servers gehört nicht dazu: Seine Zustimmung öffnet sich in Ihrem eigenen
  Browser, wo Ihre Anmeldungen und Passkeys sind, weil der Callback allein durch
  seinen `state` authentifiziert wird. Schließen Sie sie dort ab und kehren Sie
  zurück; der Server erscheint in der App, sobald er autorisiert ist.

- **Kein dauerhafter Zugriff.** Das Verknüpfen des Computers gewährt für sich
  nichts: Ein Run erreicht nur die Ordner, die Sie gewählt haben, in den Modi, die
  Sie gewählt haben, und den Bildschirm erst nach Ihrer Erlaubnis.

## Wo es im Baum liegt { #where-it-sits-in-the-tree }

- `desktop/ui/` - die Seiten des ersten Starts und der Bildschirmrahmen, statische
  Dateien.
- `desktop/core/` - die Teile, auf die sich beide Seiten einigen müssen, ohne
  Laufzeit: die Gerätenachrichten, die Endpunkte und das Back-off, eigenständig
  getestet.
- `desktop/src-tauri/` - die Shell: Fenster, Menüs, Blobby, schnelle Frage, die
  Geräteverknüpfung (`device.rs`), der lokale Ausführer (`local_work.rs`) und der
  Bildschirm (`screen.rs`).
- `backend/app/services/device_hub/` - die Serverhälfte: Präsenz in Redis, damit
  jeder API-Host und Worker einen Computer erreicht, und `DeviceWorkspace`, der
  Sandbox-Workspace, den die App ausführt.

## Coding agents auf diesem Computer { #coding-agents-on-this-computer }

**Settings → Desktop app → Coding agents on this computer** zeigt Versionen und
Anmeldestatus. **Set up** richtet privates Node.js 24.19.0 und festgelegte
Coding-Adapter anhand einer Lockdatei mit Integritätsprüfungen ein. Du musst keine
Entwicklerwerkzeuge separat installieren. **Sign in** startet den eigenen
Browser-OAuth-Ablauf des Agenten; AgenticOS liest oder kopiert keine Zugangsdaten.
**Refresh status** prüft die Anmeldung ausdrücklich. Der Fokuswechsel zur App
fragt nicht ständig den Zugangsdaten-Speicher ab; erfolgreiche Anmeldung und
Einrichtung aktualisieren den Status automatisch.

Wählen Sie in der Desktop-App unter **Chat-Steuerung → Werkzeuge und Dateien → Programmieragent** entweder **Claude Code** oder **Codex**, auch wenn die veröffentlichte Fähigkeit deaktiviert ist oder fehlt. Die App richtet lokale Dateiwerkzeuge ein und öffnet die native Ordnerauswahl, sofern der aktuelle Ordner noch keinen Vollzugriff hat. Abbrechen behält die bisherigen Einstellungen bei. **Agenteneinstellung verwenden** stellt die veröffentlichte Konfiguration wieder her.

Die Auswahl gilt für diesen Chat. Bestehende Nur-Lesen- und Freigaberegeln gelten weiterhin; die native Startfreigabe kann für diesen Agenten und Ordner gespeichert werden. Der Wechsel zur Cloud entfernt die lokale Programmieragenten-Auswahl dieser Unterhaltung. Die Chat-Steuerung öffnet sich über dem Nachrichtenfeld. Ihre Tabs sind **Modell**, **Werkzeuge und Dateien** (Programmieragent, Work on, Browser, Computer use und Skills) und **Einstellungen** (Freigaben und Benachrichtigungen).

Wähle für die Capability **Coding agent** die Option **On this computer**, einen
Ordner unter **Work on** und vollständigen Zugriff. Die native Zustimmung wird für
diesen Agenten, Ordner, die Adapterversion und Verbindung gespeichert. Entfernen
oder erneutes Auswählen des Ordners löscht die Zustimmung und stoppt dort laufende
Agenten; Konto- und Serverwechsel löschen Zustimmungen ebenfalls. Der Adapter
läuft unter deinem Betriebssystemkonto: Der Ordner bestimmt das Arbeitsverzeichnis,
keine Betriebssystem-Sandbox. Zugriff auf den gesamten Computer startet auch einen
Coding agent, im Heimatordner oder einem Ordner darin. Aufgabenfreigaben und Systemberechtigungen gelten weiterhin.

Die Capability-Freigabe gilt einmal pro Aufgabe. `edit` erlaubt angefragte Aktionen; `read_only` verweigert Änderungen. Claude deaktiviert im Lesemodus die Umgehung von Berechtigungen und bietet nur Lesewerkzeuge an. Codex wählt seine native schreibgeschützte Sandbox. Lokale Agents verwenden ihre eigenen Modelleinstellungen. Abonnementnutzung bleibt unbepreist; die angezeigten Run-Kosten sind eine Untergrenze.

Weitere Aufgaben setzen die benannte Sitzung (`main`, wenn eine Aufgabe keine nennt) für dieselbe Unterhaltung, denselben Agent, Harness, Ordner, Account und dieselbe Zugriffsrichtlinie fort; mehrere Sitzungen laufen gleichzeitig, bis zu acht auf einem Computer, jede im Chat-Ordner oder einem Ordner darin. `fresh_session` beginnt ausdrücklich neu. Sitzungskennungen bleiben in den Desktop-Einstellungen außerhalb des Repositorys und werden beim Trennen oder Accountwechsel gelöscht. Kann eine gespeicherte Sitzung nicht geladen werden, schlägt die Aufgabe ausdrücklich fehl. Starte bei Bedarf neu. Eine Trennung stoppt den Prozess; gespeicherte Harness-Verläufe bleiben fortsetzbar.

Eine während der lokalen Aufgabe gesendete Korrektur unterbricht den aktuellen ACP-Turn. Sobald der Adapter den Stopp bestätigt, setzt dieselbe Sitzung mit der Korrektur fort. Das Transkript hält die angewendete Korrektur fest. Nach Abschluss eingehende Nachrichten bleiben für den übergeordneten Agent verfügbar.

Nach Auswahl des Coding-Agenten und eines freigegebenen Ordners zeigen **Coding-Modell** und **Denktiefe** die vom installierten Agenten gemeldeten Optionen. Sie gelten für dieses Gespräch und werden vor neuen oder fortgesetzten Aufgaben angewandt. Leere Felder behalten die eigenen Einstellungen des Agenten bei. Ein Agentenwechsel entfernt inkompatible Vorgaben. Aktualisiere die Optionen nach einer Änderung von Anmeldung oder Konfiguration ausdrücklich; ein weiteres Fenster prüft das Konto nicht erneut. Entfernte oder nicht unterstützte Optionen werden angezeigt und abgewiesen, statt still ersetzt. Das Lesen der Optionen startet keine Modellantwort und erteilt keine Werkzeugfreigabe.

## Eigene Skills und Anweisungen { #your-own-skills-and-instructions }

**Chat controls → Work on → My skills and instructions** wählt die Quellen einer Unterhaltung: `~/.agents/skills`, `~/.claude/skills` und `~/.codex/skills`. Neue Chats starten mit ausgeschalteten Quellen. Dateien werden direkt gelesen, ohne Zugangsdaten oder Konfiguration zu kopieren oder zu synchronisieren.

Unter aktivierten Quellen gewinnt bei gleichen Namen `.agents`, dann `.claude`, dann `.codex`. Zähler berücksichtigen die aktuelle Auswahl. Links auf denselben Skill-Ordner werden beim Lesen dedupliziert. Globale Anweisungen stammen aus der neueren aktivierten Datei `~/.codex/AGENTS.md`, `~/.claude/AGENTS.md` oder `~/.claude/CLAUDE.md`, einschließlich Markdown-Symlinks.

Danach folgen `AGENTS.md` und `CLAUDE.md` des freigegebenen Arbeitsordners. Vor Arbeiten in einem Unterordner kann der Agent mit `load_local_instructions` die Hierarchie von der freigegebenen Wurzel bis dorthin lesen. Spezifischere Dateien folgen den übergeordneten. Der Leser verlässt die Freigabe nicht und folgt keinen Projekt-Symlinks. Anweisungen erweitern keine Run-Berechtigungen.

Geladene Skill- und Anweisungstexte gelangen über deinen Server zum konfigurierten Modell des Agents. Die Quellenauswahl steuert diesen AgenticOS-Kontext; lokal laufende Coding agents behalten ihre eigene Konfiguration und Anweisungssuche.

## Diagnose { #diagnostics }

**Help → Export Diagnostics…** schreibt eine JSON-Datei an einen Ort deiner Wahl, zum Anhängen an einen Fehlerbericht. Sie enthält die Version, das Betriebssystem, was macOS erlaubt hat, ob Claude Code und Codex installiert und angemeldet sind, die Adresse des Servers (nur Schema, Host und Port) und die letzten Abstürze. Sie enthält keine Zugangsdaten, Tokens, Unterhaltungen oder Pfade unter deinem Home-Ordner, und nichts wird irgendwohin gesendet. Ein Absturz wird beim Auftreten in `crash.log` im Datenordner der App festgehalten.

Wenn die Desktop-App 1.38.1 bei **Linked — reconnecting…** bleibt und lokale
Chats **Waiting for your computer** anzeigen, prüfe die Absturzstellen in der
exportierten Diagnose auf `rustls` / `crypto/mod.rs`. Dieser Fehler beim TLS-Start
ist in einer neueren Desktop-Version behoben. Installiere diese und öffne die
App erneut; ein Update nur des Servers ersetzt den Desktop-Client nicht.
Die bestehende Kopplung und die Ordnerfreigaben müssen für diese Korrektur
nicht zurückgesetzt werden.

## Lokaler Browser, Modelle und MCP { #local-browser-models-and-mcp }

Nach dem Koppeln lässt sich unter **Browser → Lokaler Browser** die Einstellung
des Agents für dieses Gespräch überschreiben. Die Wahl ist unabhängig von **Work on**:
Sie benötigt weder Ordnerfreigabe noch Sandbox-Fähigkeit und behält die Cloud-Sandbox
des Agents bei. Lokale Modelle und MCP-Dienste benötigen weiterhin einen freigegebenen
Ordner oder eine Freigabe des gesamten Computers; der Run erhält seine Sandbox-Bindung. Die Telefon-App ruft keine Desktop-Befehle auf.

Dienste werden unter **Settings → Desktop app → Local services** hinzugefügt.
Ein nativer Dialog bestätigt jede Freigabe. Modelle verwenden einen Ollama- oder
OpenAI-kompatiblen HTTP-Endpunkt (etwa `http://127.0.0.1:11434/v1`) und eine
installierte Modell-ID. MCP benötigt einen laufenden Streamable-HTTP-Server
(etwa `http://127.0.0.1:8000/mcp`).

Nur Loopback-Adressen sind erlaubt, ohne
Weiterleitungen oder Zugangsdaten in der URL. Der Desktop hält die Adresse; die
API übermittelt eine undurchsichtige Freigabe-ID. Anfragen und Antworten sind auf
8 MiB begrenzt, die Dienstfrist beträgt zwei Minuten. MCP-Server müssen ohne Token
antworten und HTTP-Antworten beenden; eigenständige SSE-Abonnements und das Starten
von stdio-Prozessen werden nicht unterstützt. Entfernen einer Freigabe verweigert
weitere Aufrufe. Das Organisationsprofil bleibt zur Zuordnung erhalten, ohne seine Cloud-Zugangsdaten zu öffnen.
Lokale Inferenz hat keinen Cloud-Fallback; Funktionen mit separat
konfigurierten Modellen behalten ihre Einstellungen.

**Local browser** zeigt nach Zustimmung auf dem gekoppelten Computer eine native
Seite im Browserpanel der Konsole. Klicken, Scrollen und Tippen erfolgen lokal,
ohne Screenshots zu übertragen. Die private Sitzung importiert keine persönlichen
Tabs oder Passwörter. Seitentext erreicht weiterhin das Agent-Modell. Manuelle
Eingaben übernehmen die Kontrolle; **An Agent zurückgeben** gibt sie zurück.

Bei breitem Chat öffnet sich der Browser neben dem Gespräch, lokal wie remote.
Ziehen Sie die Trennlinie oder ändern Sie die Breite mit deren Pfeiltasten.
**Maximieren** öffnet das Vollbild; **Zurück neben den Chat** stellt den Bereich
wieder her. Schmale Chatbereiche und Telefone verwenden automatisch das Vollbild.

Ein nativer Tab gehört zu Computer, Organisation, Person, Agent und Gespräch.
Er bleibt zwischen Runs offen; `browser_read` setzt ihn fort. Nur ein Run kann ihn
gleichzeitig nutzen. Der Run erneuert die Lease automatisch; stoppt sein Backend,
wird sie nach zwei Minuten wieder verfügbar. **Tab schließen** entfernt ihn; das Schließen des Panels
blendet ihn nur aus. Beim Trennen des gekoppelten Geräts schließen alle Tabs.
Es bleiben höchstens acht Tabs erhalten; zwei Stunden inaktive Tabs können beim
Öffnen eines weiteren Tabs entfernt werden.

Die Zustimmung zum nativen Browser gilt für die Tabs dieses Gesprächs während der aktuellen Geräteverbindung. Neue oder vom Agenten erneut geöffnete Tabs fragen bei gleicher Domain-Richtlinie nicht erneut. Wenn du den letzten Tab selbst schließt, wird die Zustimmung widerrufen; Ausblenden des Panels widerruft sie nicht. Trennen des Geräts löscht sie. Eine andere Person, ein anderer Agent, ein anderes Gespräch oder eine andere Domain-Richtlinie benötigt eine eigene Zustimmung.

Computer use und Webbrowser bieten Umgebungskarten mit kurzen Beschreibungen. Neue Computer-use-Bindungen wählen ausdrücklich Docker / Sandbox. Automatisch wird nicht mehr angeboten; bestehende automatische Konfigurationen bleiben lesbar und unverändert, bis eine Person eine Umgebung auswählt. Docker Compose enthält sandboxd und die Desktop-Laufzeit. Andere Sandbox-Hosts registriert ein Operator mit URL und Schlüssel unter Verbindungen → Sandboxes und wählt sie samt Desktop-Laufzeit in den Sandbox-Einstellungen des Agenten.

Für Chromium-Kompatibilität **Nativen lokalen Browser verwenden** in der
Browserfähigkeit deaktivieren. Aufgaben mit Vision oder Sprach-/Zeitzonenüberschreibungen verwenden ebenfalls
ein isoliertes Chromium-Fenster. Dafür ist Chrome, Chromium, Edge oder Brave
nötig; das temporäre Profil schließt mit dem Run. Native DOM-Aktionen verwenden
Skripte, die manche Seiten von vertrauenswürdiger CDP-Eingabe unterscheiden.
Seiten erhalten keine Konsolen- oder Dateiberechtigungen; sie dürfen nur eine
Übernahme melden. `connection: local` benötigt weiterhin die lokale Browserauswahl.

## Installationspakete und Updates { #installers-and-updates }

Der Apps-Workflow baut auch Entwicklungsinstaller und prüft die Installation ohne UI-Automatisierung: Kopieren der Mac-App aus dem DMG, stille Installation und Entfernung unter Windows, Installation und Entfernung des Debian-Pakets sowie Entpacken der portablen AppImage. Er prüft das eingebettete macOS-Widget und Signaturen, die Isolation persistenter Sitzungen und die Ablehnung veränderter Update-Downloads. Diese Prüfungen nutzen Ad-hoc- oder unsignierte Builds und bestätigen keine öffentliche Beglaubigung oder Store-Freigabe.

Der GitHub-Actions-Workflow **Apps** prüft native Crates auf macOS, Windows und
Linux und baut Android-Debug-APKs sowie die iOS-Simulator-App. Vollständige native
Prüfungen laufen in CI; `make desktop-check` bleibt für gezielte lokale Änderungen
verfügbar. **App release** hängt Installer, signierte Update-Dateien, ein APK und
einen Homebrew-Cask an ein bestehendes veröffentlichtes stabiles Release
`v1.MINOR.PATCH`, dessen Commit auf `main` liegt. Es erstellt kein Plattform-Release.
Der Cask wird auch im Homebrew-Tap veröffentlicht, wenn ein Deploy-Key oder Token konfiguriert ist.
**Check for Updates…** benötigt einen Build mit öffentlichem Update-Schlüssel und
prüft vor der Installation die Signatur.

Desktop-Release-Builds laufen parallel. Jeder lädt seine eigenen signierten
Pakete hoch; ein abschließender Job prüft alle vier nativen Targets und
veröffentlicht `latest.json`. Native CI speichert Build-Ergebnisse getrennt nach
Betriebssystem, Architektur, Compiler, Target und Build-Profil. Releases lesen nur
die gemeinsam genutzten heruntergeladenen Abhängigkeiten aus dem Cache. Ein
fehlgeschlagener Plattform-Build verhindert die Veröffentlichung des Updater-Manifests.

Die Veröffentlichung der mobilen App ist derzeit deaktiviert. Die Repository-Variable
`AGENTICOS_MOBILE_RELEASES_ENABLED=true` aktiviert signierte Android-Releases;
iOS benötigt zusätzlich den unten genannten TestFlight-Schalter. Reguläre CI-Builds
bleiben aktiv. Bis zur Freigabe der Verteilung gilt die Anleitung zur
[Selbstinstallation der mobilen App](mobile.md#availability-and-self-installation).

Vor einem Release die GitHub-Umgebung `apps-release` konfigurieren:

- Dauerhafte macOS-Signierung: Secrets `MACOS_SELF_SIGNED_P12`, `MACOS_SELF_SIGNED_P12_PASSWORD` und Variable `MACOS_SELF_SIGNED_IDENTITY`. Den öffentlichen Fingerprint in `scripts/macos_signing_identity.txt` veröffentlichen.
- Homebrew: Secret `HOMEBREW_TAP_DEPLOY_KEY`, ein schreibender Deploy-Key nur für das Tap-Repository. `HOMEBREW_TAP_TOKEN` bleibt eine Alternative. Temporäre Schlüsseldateien werden auch bei Fehlern entfernt.
- Variable `AGENTICOS_UPDATER_PUBLIC_KEY`; Secrets `TAURI_SIGNING_PRIVATE_KEY`
  und `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (dauerhaftes Update-Schlüsselpaar).
- Optionale macOS-Developer-ID-Signierung: Setze die Repository-Variable `AGENTICOS_MACOS_SIGNING_ENABLED=true` und konfiguriere die folgenden Apple-Zugangsdaten. Fehlende Daten stoppen den Build ohne Ad-hoc-Fallback. Ohne Flag oder bei false wird das konfigurierte dauerhafte selbstsignierte Zertifikat verwendet, sonst eine Ad-hoc-Signatur. Beide sind nicht notarisiert; Apple-Zugangsdaten werden ignoriert.
- macOS: `APPLE_CERTIFICATE` (Base64-P12), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (App-Passwort)
  und `APPLE_TEAM_ID` für Developer-ID-Signatur und Notarisierung.
- Optionales Windows-Authenticode: `WINDOWS_CERTIFICATE_BASE64` (PFX) und
  `WINDOWS_CERTIFICATE_PASSWORD`. Ohne diese bleibt der Installer unsigniert.
- Android: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`,
  `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Updates benötigen denselben Keystore.
- TestFlight: Repository-Variable `AGENTICOS_TESTFLIGHT_ENABLED=true`; Secrets
  `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_PROFILES_BASE64_JSON`
  (JSON-Array mit Base64-Profilen für App, Widgets und Share-Erweiterung),
  `APP_STORE_CONNECT_KEY_P8`, `APP_STORE_CONNECT_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID`, `APPLE_TEAM_ID`. App-IDs, gemeinsame App Group
  und App in App Store Connect zuerst anlegen. Push benötigt weiterhin die
  vorhandenen APNs-Zugangsdaten der Bereitstellung.

Store-Zugangsdaten verbleiben in CI; Jobs löschen temporäre Signaturdateien.
TestFlight-Upload bleibt bis zur ausdrücklichen Aktivierung aus. Store-Freigabe,
Provisioning und signierte Geräteauslieferung erfordern die Konten des Betreibers;
ein unsignierter lokaler Build kann sie nicht bestätigen.

## Zusammenfassung { #recap }

- **Die Konsole bleibt auf dem Server.** Die Shell öffnet sie; nichts wird
  gebündelt.
- **Nativ, wo es zählt.** Menüs, Benachrichtigungen, angeheftete Agents, Blobby,
  schnelle Frage und Sprache von überall.
- **Ihre Agents können auf diesem Computer arbeiten** - in Ordnern, die Sie wählen,
  in Modi, die Sie wählen, vom Betriebssystem eingesperrt und nur für Ihre eigenen
  Runs.
- **Und auf seinem Bildschirm** - erst gefragt, umrahmt während sie handeln und mit
  einem Kürzel gestoppt.

Quick Ask unterstützt bis zu acht unabhängige Tabs pro Fenster. Jeder behält Entwurf, Anhänge, Agentenauswahl und laufende Antworten. Letzte Unterhaltungen öffnet eine durchsuchbare Liste und verwendet einen bereits offenen Tab erneut; gespeicherte Chats laden Nachrichten und frühere Beiträge. Inaktive Tabs übernehmen weder Dateiabgaben noch Diktiershortcuts oder Fokus. Letzte Unterhaltungen zeigt Agenten-Avatare in einem ausklappbaren Abschnitt, der nur seinen tatsächlichen Platz belegt. Neuer Chat ist die einzige Aktion für einen frischen Tab. Die Browser-Seitenleiste bietet den Desktop-Download an; Schließen pausiert die Erinnerung für dieses Konto und diesen Browser für 14 Tage.

Quick Ask bietet eine Mikrofontaste für Diktat per Klick zusätzlich zum Gedrückthalten des Kurzbefehls. Sprachgespräche verwenden dieselben Steuerelemente wie der Chat, mit dem konfigurierten Transport des ausgewählten Agenten, Untertiteln, Freigaben und Fragen. Gesprochene Beiträge werden in der Unterhaltung gespeichert. Textversand und Diktat warten während eines Anrufs. Ein Tab- oder Agentenwechsel beendet den Anruf und gibt das Mikrofon frei.

## Lokale Routinen { #local-routines }

Die Ablehnung eines Ersatzcomputers beweist keinen Widerruf auf dem freigegebenen Computer: Er kann einfach offline sein. Der Eigentümer erhält einen deduplizierten Hinweis zum Verbinden oder Prüfen des Zugriffs; Routine und Ereignisdaten warten weiter. Eine Ablehnung der ursprünglich gewählten aktiven Sitzung stoppt die Routine weiterhin zur Prüfung.

Unter Linux prüft die App vor dem Anbieten von Ordnerschreibzugriff oder dem Start eines Sandbox-Befehls, ob bubblewrap `--bind-fd` unterstützt. Fehlende, ungeeignete oder nicht antwortende Builds werden abgewiesen; aktualisieren Sie bubblewrap für diesen Modus.

Die JSON-Datei der Routinefreigaben wird gegen ihren aktuellen SHA-256-Fingerabdruck im Betriebssystem-Schlüsselbund geprüft. Änderungen oder das Wiederherstellen einer Kopie vor dem Widerruf gewähren keinen Zugriff. Ein nicht verfügbarer Schlüsselbund oder eine Abweichung blockiert Routinen. **Upgrade:** ältere Freigaben haben keinen Fingerabdruck und benötigen neue Zustimmung: Computer explizit trennen, erneut koppeln und Routinen prüfen. Derselbe Reset behebt einen unterbrochenen Schreibvorgang; die App vertraut ungeprüften Dateien niemals automatisch.

Erstelle eine lokale Routine mit **Als ich ausführen**, wähle einen Ordner und separat Lesen, Schreiben und Befehlsausführung. Befehle benötigen Schreibzugriff. Beim Speichern entsteht zunächst eine pausierte Routine. Beim ersten Mal fragt die Desktop-App einmal nativ, ob **alle deine Routinen** in dieser Organisation in diesem Ordner und seinen Unterordnern mit diesen Vorgängen arbeiten dürfen; wähle deinen Benutzerordner für den ganzen Computer.

Jede spätere Routine in diesem Ordner wird ohne Nachfrage gespeichert, und die Erlaubnis gilt auch nach App-Updates und erneuter Anmeldung. Abbrechen lässt dieselbe Routine pausiert; ein erneuter Versuch vervollständigt sie ohne Duplikat. Eine allgemeine Ordnerfreigabe aus einem Chat berechtigt keine Routine.

**Einstellungen → Desktop → Routine-Berechtigungen** zeigt die Freigaben des aktuellen Kontos und der Organisation auf diesem Computer. Ein Widerruf stoppt weitere Vorgänge. Ein Wechsel des Servers oder Kontos löscht die Freigaben; eine Freigabe für eine einzelne Routine aus einer älteren App endet außerdem mit ihrer Sitzung. Ein anderer Ordner oder zusätzliche Vorgänge benötigen eine neue native Bestätigung. Browser, Bildschirm, lokale Modelle, lokale MCP-Dienste und Vollzugriff sind ausgeschlossen. Der veröffentlichte Agent muss Sandbox bereits aktivieren; das lokale Ziel aktiviert keine Fähigkeiten.

Ist genau der bestätigte Computer vor der Ausführung offline, wartet eine dauerhafte Aktivierung in PostgreSQL. Die Routine zeigt die Anzahl wartender Aktivierungen. Zeitplan- und manuelle Auslösungen werden währenddessen zusammengefasst; unterschiedliche eingehende Ereignisse behalten ihren Kontext und ihre Aktivierungs-ID. Der bestehende Minuten-Worker prüft die Wiederverbindung. Bereitschaftsprüfungen rufen kein Modell auf und verbrauchen keine Fehlstartversuche. Die Zulassung wird mit dem Lauf vor dem ersten Modellaufruf festgeschrieben. Eine gestartete Aktivierung wird nach einem Worker-Absturz nicht automatisch wiederholt; ein ungewisser Datei- oder Befehlsvorgang erzeugt keinen neuen Lauf.

Pause, geänderte Aufgabe oder lokale Berechtigung, Löschung und Ablauf der Routine stornieren alte wartende Arbeit statt sie auf einen anderen Ordner umzulenken. Eine widerrufene Gerätesitzung benötigt Prüfung. Drei tote oder verlorene Aufträge vor der Zulassung stoppen die Routine und erzeugen einen Vorfall für die besitzende Person. Der fehlgeschlagene Ereigniskontext bleibt in deren Datenexport verfügbar. Gestartete und stornierte Kontexte werden sofort gelöscht. Abgeschlossene Metadaten und fehlgeschlagene Kontexte folgen der Laufaufbewahrung der Organisation; aktive Offline-Arbeit bleibt bis Zulassung, Stornierung oder Löschung erhalten.

API, Worker und Desktop gemeinsam aktualisieren und alte Worker vor Aktivierung des Vertrags leeren. Ältere Desktops bestätigen keine Routine-Freigaben; bestehende lokale Routinen benötigen ausdrückliche Prüfung. Migration `0272_routine_device_waits.py` ergänzt Wartezustände ohne neue Routine-Identität. Vor einem Downgrade lokale Routinen pausieren und deren Aufträge leeren: der Downgrade löscht wartenden Kontext und führt ihn nicht aus. Ältere geparkte lokale Läufe ohne Ziel-Snapshot benötigen einen neuen Lauf.

Die Auswahl des lokalen Zugriffs gehört zum gewählten Agenten, nicht zu einer globalen Vorgabe für andere Agenten. Das Widerrufen eines Ordners entfernt auch gespeicherte Auswahlen und Coding-Zustimmungen für seine Unterordner. Ältere Desktop-Apps behalten den Zugriff auf den ganzen Computer nur für ein Gespräch; ein Update ermöglicht die Wiederverwendung für weitere Gespräche desselben Agenten.

Die Korrektur `[session:api] Verwende die EU-Zahlen` erreicht die Sitzung `api`. Bei einer aktiven Sitzung erreichen sie auch Korrekturen ohne Adresse; bei mehreren bleiben diese beim übergeordneten Agenten, damit keine andere Aufgabe geändert wird. Der übergeordnete Agent protokolliert die Korrektur einmal, wenn er fortfährt.

 Sandbox-Coding-Aufgaben desselben Toolsets laufen nacheinander, damit sich ihre Dateischnappschüsse nicht überschneiden; unabhängige lokale Sitzungen laufen weiterhin parallel.
