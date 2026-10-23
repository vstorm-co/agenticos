---
source_sha: "c757cc38c0f5"
---

# Die Desktop-App { #the-desktop-app }

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

## Starten { #running-it }

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

## Eine Anwendung, kein Tab { #an-application-not-a-tab }

Auf macOS trägt die Seitenleiste der Konsole die Fensterknöpfe und zieht das
Fenster, das Fenster merkt sich Größe und Position, und Schließen lässt die App in
der Menüleiste. Die Menüleiste hat File, Edit, View, Go (`⌘1`-`⌘5`, `⌘[` und `⌘]`)
und Window; ein Tray-Menü tut dasselbe auf Windows und Linux. Native
Benachrichtigungen tragen Approve und Reject für eine wartende Freigabe, und Dock
oder Taskleiste zeigen, wie viele warten. **Einstellungen → Desktop-App** öffnet
die App bei der Anmeldung, hält sie bei geschlossenem Fenster am Laufen und schaltet
die Plakette an oder aus.

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

## Auf diesem Computer arbeiten { #work-on-this-computer }

Das eine, was ein Browser nicht kann: Ein Chat, dessen Agent eine Sandbox hat,
kann statt in der Cloud in einem Ordner auf dem Computer arbeiten, auf dem die App
läuft. Die Datei- und Shell-Werkzeuge des Agents - auflisten, lesen, schreiben,
bearbeiten, ausführen - erreichen diesen Ordner über die App.

**Den Computer einmal verknüpfen.** **Einstellungen → Desktop-App → Dieser Computer
→ Agents hier arbeiten lassen** gibt der App eine eigene Sitzung für diesen
Computer, nachdem ein nativer Dialog Sie um Bestätigung gebeten hat, und hält ihr
Refresh-Token im Schlüsselbund des Systems. Die App hält dann eine ausgehende
WebSocket-Verbindung zum Device-Hub des Servers (`/api/v1/ws/device`); auf dem
Computer lauscht nichts. **Trennen** beendet diese Sitzung.

**Pro Chat wählen.** In der Desktop-App bieten die Einstellungen eines Chats
**Arbeiten auf (Work on): Cloud / Diesem Computer**. Die Wahl dieses Computers
fragt im nativen Auswahldialog nach einem Ordner und danach, wie weit der Agent
darin gehen darf:

| Modus | Was der Agent darf | Wie das durchgesetzt wird |
|---|---|---|
| Nur lesen | Dateien lesen; nichts wird geschrieben und kein Befehl läuft | Die App lehnt Schreibzugriffe und Befehle ab |
| Im Ordner schreiben | Lesen, im Ordner schreiben, Befehle ausführen | Befehle laufen unter Seatbelt auf macOS und bubblewrap auf Linux, schreibbar nur im Ordner und in den temporären Verzeichnissen |
| Vollzugriff | Befehle laufen als Sie, ohne Sandbox | Jeder Befehl wird zuerst in einem nativen Dialog zur Freigabe gezeigt |

Windows bietet Nur lesen und Vollzugriff. Linux bietet Schreiben im Ordner nur,
wenn `bwrap` installiert ist.

**Der Computer entscheidet, nicht der Server.** Die gewählten Ordner mit ihren
Modi stehen in den Einstellungen der App, und jede Operation nennt einen Ordner und
einen Modus, die die App damit abgleicht: ein Ordner, den Sie nie gewählt haben,
ein Modus, der weiter geht als erlaubt, oder ein Pfad, der aus dem Ordner
herausführt, wird auf dem Computer abgelehnt, egal was der Server verlangt hat. Die
Wahl wird je Unterhaltung gespeichert, und ein neuer Chat beginnt in der Cloud.

**Nur Ihre eigenen Runs.** Ein Chat erreicht Ihren Computer nur, wenn er Ihr
eigener ist - nie ein API-Schlüssel, ein Widget-Besucher oder der Chat eines
anderen - und ein [Trigger](triggers.md) nur, wenn er als sein Ersteller handelt,
der ihm unter **Arbeiten auf** des Triggers einen Ordner seines Computers zuweist.

**Wenn der Computer weg ist.** Ein Run, der diesen Computer angefordert hat und die
App nicht verbunden vorfindet, wartet bis zu zehn Minuten auf sie, und der Chat
sagt es. Eine Operation, die die App mitten im Run getrennt vorfindet - Deckel zu,
Netz gewechselt -, wartet bis zu fünf Minuten auf ihre Rückkehr in derselben
Sitzung und macht dann weiter. Solange eine Operation eines Runs läuft, sagt der
Tray, dass ein Agent auf diesem Computer arbeitet.

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

Die eine Navigation, die das Konsolenfenster verweigert. Alles andere lädt im
Fenster; ein Klick auf **Continue with Google** öffnet sich stattdessen in Ihrem
eigenen Browser, und das Ergebnis kommt zur App zurück (#1532).

Was passiert, der Reihe nach:

1. Das eigene `/api/oauth/<provider>/login` der Konsole läuft **im Fenster**, wo es
   das httpOnly-Cookie mit einer vorgemerkten Einladung lesen und anhängen kann.
2. Das Fenster sieht dann eine Navigation zu `/api/v1/oauth/<provider>/login` des
   *Deployments*, übergibt sie mit angehängtem `client=desktop` und frisch
   erzeugtem `desktop_nonce` an den System-Browser und folgt ihr nicht.
3. Sie melden sich dort an, in einem echten Browser mit Ihren eigenen Passwörtern,
   Erweiterungen und welchem zweiten Faktor auch immer.
4. Der Callback des Deployments erkennt, dass dieser Versuch ein Desktop-Versuch
   war - zu *Beginn* in der Sitzung unter dem OAuth-`state` dieses Versuchs
   vermerkt, nie aus der Rückkehr gelesen - und leitet nach
   `agenticos://auth/callback?code=…` weiter, mit einem Einmal-Code, der nach einer
   Minute abläuft, und der erhaltenen Nonce.
5. Das Betriebssystem übergibt diesen Link der App. Die Shell schickt das
   Konsolenfenster nach `<your server>/auth/callback?code=…`, das den Code von
   Server zu Server gegen das Token-Paar tauscht; die Cookies des Fensters selbst
   werden gesetzt.

**Einen Deep Link kann jeder Prozess auf Ihrem Rechner auslösen**, also ist eng
gefasst, was einer hier darf: die Konsole an einen Pfad schicken, auf dem Server,
den *Sie* konfiguriert haben, mit einem Code, der genau einmal einlösbar ist - und
nur einer mit der Nonce, die diese App für diesen Versuch erzeugt hat. Auf Windows
und Linux gibt eine Einzelinstanz-Sperre die Argumente eines zweiten Starts an den
ersten weiter. Das Deployment muss beim Schema übereinstimmen -
`DESKTOP_DEEP_LINK_SCHEME`, `agenticos`, sofern niemand es geändert hat - und bei
seiner eigenen öffentlichen Adresse.

## Was sie bewusst nicht tut { #what-it-deliberately-does-not-do }

- **Kein Navigationswächter.** Ein Link, der den Origin des Servers verlässt,
  öffnet sich im Fenster, weil ein OAuth-Ablauf - das Verbinden eines MCP-Servers -
  zur selben Webview zurückkehren muss, damit sein Cookie ankommt. Der Fenstertitel
  nennt jeden anderen Host, den es zeigt.
- **Kein lokaler Run ohne Sandbox.** Arbeiten auf diesem Computer verlegt, wo die
  Sandbox-Werkzeuge eines Agents laufen; ein Agent ohne Sandbox hat keine solchen
  Werkzeuge zu verlegen.
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

`desktop-check` gehört nicht zu `make lint` oder `make check`: Die CI hat noch keine
Rust-Toolchain. Führen Sie es aus, bevor Sie eine Änderung unter `desktop/` pushen.

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
