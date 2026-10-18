---
source_sha: "27d973f8560b"
---

# Die Konsole { #the-console }

Die Konsole ist die Webanwendung, über die alles andere auf dieser Site
konfiguriert wird. Diese Seite ist die Landkarte: wofür jeder Bereich da ist,
und welche Seite ihn ausführlich erklärt.

Wenn Sie einen einzelnen Screen suchen, ist der schnellste Weg das **"?"** in
der Kopfzeile einer Seite — es spielt den Rundgang dieser Seite ab, und eine
Seite, deren Kopfzeile kein "?" trägt, hat keinen Rundgang abzuspielen.

## Das Dashboard { #the-dashboard }

Die Startseite ist ein **anordenbares Raster aus Widgets**, und sie ist die
Antwort auf die Frage "was passiert gerade", ohne fünf Seiten zu öffnen.

Es gibt achtunddreißig Karten. Sie werden nicht alle davon sehen: **eine Karte
hängt an der Berechtigung, die ihre Daten verlangen**, also wird ein Widget, das
Sie nicht lesen dürfen, nie eingehängt und seine Abfragen werden nie gestellt —
außer Ihren eigenen Benachrichtigungen weiter unten, die nur verlangen, dass Sie
angemeldet sind. Eine leere Gruppe verschwindet samt ihrer Überschrift, statt
leer dazustehen.

Ein Schalter oben sagt, wessen Dashboard es ist, und bietet nur die Ansichten
an, die Sie öffnen dürfen. Alle starten in der Ansicht **Ich**:

| Ansicht | Beantwortet |
|---|---|
| **Ich** | Eine Begrüßung und Ihr Zeitraum in einem Satz; Ihre Runs, wie viele fertig wurden, was auf Sie wartet und was es gekostet hat; dann die Aufrufe, die auf Sie warten, Ihre Unterhaltungen, Ihre Agents und was mit Ihnen geteilt wurde |
| **Organisation** | Die anordenbare Seite unten |
| **Gruppe** | Die Mitglieder einer [Gruppe](departments.md) - ihre Runs, Ausgaben, Modelle, wann sie arbeiten und wer es am meisten nutzt. Die Gruppe wählen Sie neben dem Schalter. Eine Gruppe, deren Mitglieder im Zeitraum nichts ausgeführt haben, sagt das einmal, mit einem Weg zur Gruppe, statt eine Seite leerer Karten zu zeigen |
| **Deployment** | Nur für einen [Deployment-Admin](permissions.md) — Plattformsummen, Health, aktivste Tenants, Bewertungen |

Die Ansicht der Organisation zeigt die Karten, die mit Daten antworten, in
Gruppen. Der Rest - Integrationen, Kanäle, Routinen, Wissens-Sync, Abteilungen,
Mitglieder, Sandboxes - wartet im Katalog, einen Klick entfernt unter **Customize**:

| Gruppe | Beantwortet |
|---|---|
| *(ohne Titel, ganz oben)* | Die Zusammenfassung, Runs im Zeitverlauf und wie sie ausgingen |
| **Needs attention** | Was wartet: [Freigaben](governance.md#approvals), jüngste Fehlschläge, Budget-Spielraum, Ihre jüngsten [Benachrichtigungen](#the-bell) |
| **Usage & cost** | Welche Agents genutzt werden, Ausgaben, wann gearbeitet wird, woher Runs kommen, Modellmix, Latenz, Antwortqualität, wer es nutzt |

Wer Agents baut, sieht über den Bändern außerdem **Erste Schritte**, bis jeder
Schritt erledigt ist: einen Agent anlegen, ihn veröffentlichen, ihm eine
Wissensbasis geben, Abteilungen hinzufügen, jemanden aus dem Team einladen und -
wer darf - einen Agent in eine Chat-App bringen. Jeder Schritt wird nach dem
abgehakt, was existiert, wo auch immer er erledigt wurde; wer die Karte schließt,
blendet sie in diesem Browser aus.

Ihre eigene Ansicht zeigt außerdem **AgenticOS entdecken**: je eine Kachel für das,
was leicht übersehen wird - den eigenen MCP-Server dieses Deployments für Claude
Code, Codex oder Cursor, Subagents, Sandboxes, Apps, Routines, Chat-Apps, den
Web-Browser, Wissensbasen und Skills -, jede führt dorthin, wo es eingeschaltet
wird, und nur die, die Sie nutzen können. Schließen Sie eine Kachel oder alle;
auch das bleibt im Browser.

Diagramme im Zeitverlauf wählen ihren Schritt selbst. Die Spanne vom ersten Run
des Zeitraums bis jetzt wird in höchstens 48 Punkten gezeichnet, im feinsten
Schritt, der passt - eine Minute, fünf, fünfzehn, eine Stunde, drei oder sechs
Stunden, ein Tag, eine Woche -, sodass ein Nachmittag in Minuten und ein Quartal
in Wochen lesbar ist statt als ein Ausschlag am rechten Rand.

### Sie neu anordnen { #rearranging-it }

Ziehen Sie eine Karte, ändern Sie ihre Größe, blenden Sie eine aus. Die
Anordnung gehört **Ihnen** — sie ist an Sie und an die Organisation gebunden, in
der Sie gerade sind, nicht an die Organisation allein —, also ändert eine
Änderung die Seite von niemandem sonst.

Speichern Sie eine Anordnung als benanntes **Preset**, um mehr als eine zu
behalten und zwischen ihnen zu wechseln. Ein doppelter Name wird abgelehnt,
statt still den Snapshot zu überschreiben, den Sie behalten wollten.

!!! info "Das Tor läuft zuletzt, über das, was ihm übergeben wird"

    Eine gespeicherte Anordnung kann umsortieren und ausblenden, aber sie kann
    nichts sichtbar machen. Die Berechtigungsprüfung läuft, nachdem das Layout
    aufgelöst wurde, ganz gleich ob es aus der Voreinstellung oder aus Ihrer
    eigenen gespeicherten Anordnung stammt.

## Die Glocke { #the-bell }

Neben der Suche, in der Seitenleiste: eine laufende Zählung dessen, was Sie
noch nicht gelesen haben, und ein Klick öffnet die Liste selbst. Anders als
das Widget oben holt das Öffnen die Seite, auf der Sie gerade stehen, keine
Fünf-Karten-Vorschau - **Load more** blättert immer weiter zurück durch die
Organisation, in der Sie gerade sind, plus alles, was an das gesamte
Deployment adressiert ist, bis es erreicht, was aus dem Aufbewahrungsfenster
gefallen ist.

Wechseln Sie die Organisation, gehört die Glocke dieser: eine
Benachrichtigung aus der verlassenen Organisation ist nicht weg, sie liegt
hinter dem Umschalter. Ein Deployment-Administrator ist die eine Ausnahme -
seine Glocke wird nicht durch die Organisation verengt, in der er gerade
handelt, denn ein „admins"-Publikum erreicht ihn ohne eine Mitgliedschaft,
nach der sich eingrenzen ließe.

Eine Zeile mit einem Ziel ist ein Link; eine ohne - meist die eigene
Ankündigung eines Admins - lässt sich immer nur als gelesen markieren. Eine
Zeile als gelesen zu markieren, oder alle auf einmal, aktualisiert die
Zählung sofort; nichts hier wartet auf ein Neuladen der Seite. **Mark all
read** räumt in Stapeln bis zu fünftausend ungelesene Zeilen auf und fragt
dann die Zählung erneut ab - bei einem größeren Rückstau zeigt das Badge
also weiter, was noch ungelesen ist, und ein weiterer Klick beendet den Rest,
statt dass das Badge einen Posteingang behauptet, den es nur teilweise
abgearbeitet hat.

Jeder Klick kommt weiter, selbst wenn der ganze Stapel aus Zeilen bestand, die
der Lesende nicht mehr sehen kann. Markiert werden sie nie: geprüft werden die
*aktuellen* Rechte, und wer eine Woche lang herabgestuft und dann wieder
eingesetzt wird, fände die Sicherheitshinweise dieser Woche sonst bereits
gelesen vor. Stattdessen sagt ein abgeschnittener Durchlauf, wo er aufgehört
hat, und der nächste Klick setzt dort an.

Sowohl die Zählung als auch der Durchlauf sagen, wenn sie an
dieser Grenze statt am Ende des Posteingangs aufgehört haben - `approximate` bei
`GET /notifications/unread-count`, `remaining` bei
`POST /notifications/mark-all-read` -, denn sonst sind eine Zählung genau an der
Grenze und eine echte Zählung derselben Größe dieselbe Zahl.

Gelesen ist nicht dasselbe wie weg, und beides wird angeboten. Fährt man über
eine Zeile, erscheint ein Kreuz, das sie aus der Liste nimmt; **Clear** in der
Kopfzeile nimmt alles heraus, was gerade gelistet ist - gelesen wie ungelesen.
Wird etwas Ungelesenes geleert, gilt es zugleich als gelesen, denn eine Zeile,
die nichts auf dem Bildschirm mehr erreicht, darf nicht weiter auf das Badge
zählen. Wie „Mark all read" ist ein Leeren begrenzt - tausend Zeilen - und ein
längerer Rückstau braucht einen zweiten Klick.

Was eine geleerte Zeile *nicht* tut, ist wiederkommen. Die Benachrichtigung
wird behalten und nur nicht mehr gelistet, statt gelöscht zu werden, und genau
das macht es wahr: der Posteingang erkennt eine Wiederholung an dem Sachverhalt,
den sie beschreibt, eine gelöschte Zeile wäre also eine, die die nächste
Budgetprüfung oder der nächste Versuch erneut schriebe. Einen Alarm zu
verwerfen, um den Sie sich gekümmert haben, ist damit endgültig - für dieses
Vorkommnis; ein *neuer*, über einen neuen Sachverhalt, kommt weiterhin an.
Zeilen fallen auch von selbst heraus: neunzig Tage nach dem Schreiben, wenn sie
gelesen wurden, und ein Jahr danach unabhängig davon.

Was hier landet und was sich abschalten lässt, zu erklären, ist Sache von
[Governance](governance.md#alerts) — diese Seite ist nur die beiden Stellen,
an denen Sie es lesen: die Glocke für das, was gerade passiert ist, die
Dashboard-Karte für eine Handvoll der neuesten, beim nächsten Öffnen der
Seite.

## Der Assistent { #the-assistant }

Unten rechts auf jeder Seite sitzt der **Architekt**: ein Agent, den jede
Organisation bekommt, ohne etwas zu installieren, gemeinsam für alle, die Agents
ausführen dürfen (`agents:run`). Er ist an
[den MCP-Server dieser Plattform](mcp.md#agenticos-as-an-mcp-server) gebunden.
Fragen Sie ihn, welche Agents Erstattungsfragen beantworten, warum der Run von
letzter Nacht fehlschlug oder was in einer Wissensbasis steht.

Lassen Sie ihn einen
Agent entwerfen oder jemanden einladen, und er zeigt Ihnen zuerst, was Sie freigeben: einen
Agent-Entwurf als den Entwurf selbst - wo er angelegt wird, sein Name, was er tun
darf und seine Anweisungen - und alles andere als den genauen Aufruf. Er handelt mit Ihren Berechtigungen, findet und tut also, was
Sie könnten, und nicht mehr. Seine Kosten zählen wie die jedes Agents.

Eine Sprechblase über ihm spricht an, was auf Sie wartet — Freigaben, eine
Organisation ohne Agents — oder die Seite, auf der Sie sind, und bietet ab und zu
einen Tipp an. Ein Klick auf die Sprechblase fragt ihn; × schaltet die Seite
stumm, und die Glocke in seinem Fenster schaltet die Sprechblasen ganz ab. Eine
unbeantwortete Sprechblase verschwindet nach ein paar Sekunden. Bleibt die
Schaltfläche knapp eine Minute unberührt, schiebt sie sich in den rechten
Bildschirmrand und lässt einen schmalen Streifen stehen, an dem man sie
herauszieht - mit einem Punkt, wenn etwas wartet - und bleibt dort von Seite zu
Seite, bis sie geöffnet wird.

Auf einem Smartphone gibt es keine Sprechblase - sie würde die Seite verdecken,
über die sie spricht -, und die Schaltfläche trägt stattdessen den Punkt.
Freigaben, die sie schon genannt hat, bleiben für den Rest des Browser-Tabs
genannt, auch wenn ein Link die Konsole neu lädt.

Sein Fenster ist der Chat der Konsole selbst, keine Seite in der Seite, und öffnet
sich mit vier Kacheln, sodass die erste Nachricht ein Klick ist; es führt einen
eigenen Verlauf. Auf dem Telefon füllt es den Bildschirm.

Nennt er eine Seite, öffnet der Link sie in der Konsole hinter dem Fenster und
zeigt auf das gemeinte Bedienelement — die Schaltfläche, die einen Agent anlegt,
den Reiter mit den Freigaben. Die Kamera in seiner Kopfzeile zeigt ihm die Seite,
auf der Sie sind: Der Browser fragt, welchen Tab Sie teilen, und ein Bild hängt
an Ihrer nächsten Nachricht.

Längere Aufgaben plant er als Checkliste, die Sie
verfolgen können, er merkt sich Notizen über Sie zwischen Unterhaltungen, sagt
Ihnen, was Ihre Agents kosten, und kann einen versehentlich angelegten
Agent-Entwurf rückgängig machen — sonst nichts. Neben Freigaben und einer leeren
Organisation meldet sich seine Sprechblase, wenn ein Run von Ihnen gerade
fehlgeschlagen ist und wenn ein Formular seit einer Minute unfertig offen ist.

Solange die Organisation kein Modell hat, kann er nicht antworten. Geöffnet tippt
er dann ein kurzes Gespräch darüber, wie man eins verbindet: einen API-Schlüssel
beim Provider besorgen, den Architect im Agent Builder öffnen, unter **Modell**
den Provider wählen und den Schlüssel einfügen, dann ein Modell auswählen. Die
Schaltfläche bekommt nur, wer die Einstellungen der Organisation ändern darf;
alle anderen erfahren, wer das kann.

Der Architect ist ein Agent wie jeder andere, also werden Name, Modell, Wissen
und der Rest seiner Spec im Agent Builder bearbeitet - von jemandem, der die
Einstellungen der Organisation ändern darf, weil ihn alle in der Organisation
ausführen. Auf der Seite der Organisation schaltet eine Karte ihn für alle ab und
legt seine Begrüßung fest. **Einstellungen → Assistent** enthält nur noch Ihre
eigenen Tipps.

## Änderungen von anderswo { #changes-made-elsewhere }

Eine offene Seite hält mit Änderungen Schritt, die anderswo gemacht werden: in
der Konsole eines Kollegen, durch ein Skript mit einem [API-Schlüssel](api.md),
durch Claude Code über den [MCP-Server der Plattform](mcp.md#agenticos-as-an-mcp-server)
oder durch den Architekten. Jeder erfolgreiche Schreibvorgang wird den offenen
Konsolen der Organisation gemeldet, sobald er festgeschrieben ist, auch die, die
nur die Konsole macht — Freigaben, Routinen, Kanal-Bots, Gruppenfreigaben,
Benachrichtigungseinstellungen —, und eine Liste oder Detailseite ohne
ungespeicherte Änderungen lädt an Ort und Stelle neu. Ein mit einem Schlüssel
erstellter Agent erscheint auf der Seite Agents, ohne dass Sie neu laden, und ein
in einem Tab freigegebener Agent zeigt sein neues Publikum in einem anderen.

Auch Runs werden gemeldet, wenn sie starten, bei einer Freigabe oder einer Frage
anhalten und enden: Ein Run, den ein Zeitplan auslöst, erscheint auf einer
offenen Activity-Seite und ändert dort seinen Status, ohne dass eine Anfrage von
Ihnen dahintersteht.

Die Ausnahme ist der Builder, weil er Ihren Entwurf beim Tippen speichert. Ändert
sich der Agent, den Sie bearbeiten, anderswo, hört er auf zu speichern und holt
die neue Version. Ohne ungespeicherte Änderungen übernimmt er sie einfach; mit
ungespeicherten Änderungen sagt er, wer ihn worüber geändert hat, und wartet auf
Ihre Wahl: **Neu laden** (deren Version) oder **Meine Änderungen behalten** (Ihre,
über deren gespeichert).

Sie erfahren nur, was Sie lesen dürfen: Eine Änderung an einem Agent, einem
Skill, einer Wissensbasis, einer Kontextdatei, einer Seite, einem Schlüssel oder
einem MCP-Server, die Sie nicht sehen, erreicht Ihre Konsole nie, und eine
Löschung erreicht nur Rollen, die jede Zeile dieser Art sehen. Runs erreichen die
Rollen, die den Run-Verlauf lesen oder über Freigaben entscheiden, Kanal-Bots die
Rollen, die sie verwalten, und Ihre Benachrichtigungen nur Sie. Bricht die Verbindung ab, arbeitet die Konsole wie
bisher und verbindet sich selbst wieder.

## Chat { #chat }

Hier sprechen Sie mit einem veröffentlichten Agent. Die Auswahl entscheidet,
welcher Agent antwortet, und der Run verhält sich genau so, wie er es in Slack
oder hinter der API täte — dasselbe Budget, dasselbe Tor für Freigaben, dieselbe
Audit-Spur, weil [jede Oberfläche durch einen einzigen Runner
läuft](channels.md).

**Die Liste der Unterhaltungen** zeigt, mit wem jeder Thread ist und wann er
sich zuletzt bewegt hat. Einer, dessen Run noch arbeitet, zeigt einen Spinner und
wie lange er schon läuft; einer mit einer Antwort, die Sie seit dem letzten Öffnen
nicht gesehen haben, trägt einen Punkt, den das Öffnen löscht - nur für Sie, denn
einen geteilten Thread liest jeder seiner Leser für sich.

Drei Dinge im Eingabefeld sind wissenswert.

**Ihre eigenen Konten.** Ein Agent, der an [das eigene Konto jeder
Person](mcp.md#whose-account-a-binding-speaks-through) bei einem Dienst gebunden
ist, spricht mit diesem Dienst als Sie. Die Steuerelemente des Chats führen auf,
welche Dienste des Agents ein Konto von Ihnen brauchen und ob es jeweils bereit
ist, mit einer Schaltfläche, die die Zustimmungsseite des Providers in einem
neuen Tab öffnet. Fragen Sie, bevor Sie sich verbunden haben, erscheint nichts,
bis der Agent den Dienst tatsächlich braucht: Dann hält die Antwort an einer
Karte mit dieser Schaltfläche an, und sobald das Konto verbunden ist, geht
dieselbe Antwort damit weiter. **Überspringen** lässt sie ohne ihn weitergehen.

**Anhänge** werden geparst und nur dieser einen Unterhaltung übergeben; sie
werden keiner [Knowledge-Collection](file-processing.md) hinzugefügt. Siehe
[Dateiverarbeitung](file-processing.md#chat-file-uploads).

**Slash commands** werden zu einem Prompt expandiert, bevor die Nachricht
gesendet wird. Die eingebauten liefert das Produkt mit; eigene schreiben Sie
unter **Settings → Slash commands**, und jeden eingebauten, den Sie nie nutzen,
können Sie ausblenden. Sie gehören Ihnen, nicht der Organisation.

**`@` zeigt dem Agent, was er nutzen soll.** Tippen Sie `@`, und ein Menü bietet in
dieser Reihenfolge, was der Agent nutzen kann: seine MCP-Server, die Agents, an die
er Arbeit übergibt (wenn die Delegations-Capability an ist), seine Capabilities -
**Sandbox**, **Web research** - seine Skills, dann seine Wissensbasen und
Kontextdateien. Die Auswahl bleibt als `@Name` in Ihrem Text, mit ihrem Logo
markiert, und der Agent wird angewiesen, sie zu nutzen - die Werkzeuge eines
Servers oder einer Capability, die Suche einer Wissensbasis, einen Skill -, ohne
dass ihr Inhalt eingefügt wird. Einen Agent zu nennen übergibt ihm die Arbeit; wer
antwortet, ändert es nie. Löschen Sie `@Name`, und die Auswahl ist weg. Ein
eingefügter Link zeigt das Symbol seiner Website über dem Feld und in der
gesendeten Nachricht. Eine Erwähnung erweitert nie, was der Agent erreicht: Der
Server prüft jede erneut als Sie, gegen das, was der Agent bereits hat. Im
Testpanel des Builders liest das Menü den Entwurf, den Sie testen. Solange ein Gespräch leer ist, zeigt das Feld nacheinander
Beispiele aus dem, was der Agent nutzen kann - seinem Server, einer Capability,
einem Delegierten, einem Skill - und `/`; sie verschwinden, sobald Sie
hineinklicken.

**Während der Agent arbeitet**, wartet das, was Sie senden, auf seine Antwort, wie
in jedem Chat: Es steht in einer Warteschlange über dem Eingabefeld und geht
hinaus, wenn der Run endet. Ziehen Sie eine Nachricht in der Warteschlange oder
nutzen Sie ihre Pfeile, um die Reihenfolge zu ändern. **Send now** gibt sie
stattdessen in die laufende Aufgabe - der Agent liest sie beim nächsten Schritt und
ändert den Kurs, ohne neu anzufangen, und sie erscheint im Gespräch dort, wo sie
ankam. Eine Nachricht mit Dateien wartet immer auf die Antwort. Slack, Telegram und
Mattermost behalten ihr eigenes Verhalten, beschrieben unter [Kanäle](channels.md).

**Gehen, während er antwortet.** Sie müssen nicht warten. Schließen Sie den Tab,
beenden Sie die App oder öffnen Sie eine andere Unterhaltung, und der Agent
beendet die Antwort selbst: Sie landet in der Unterhaltung, und die Glocke - und
eine E-Mail, wenn Sie sie für fertige oder gescheiterte Runs eingeschaltet lassen
- sagt Ihnen, dass sie da ist, mit einem Link dorthin. Ein Turn, der nach einer
Stunde ohne Zuschauer noch läuft, wird gestoppt, und Sie erfahren das
([`CHAT_DETACHED_TURN_MINUTES`](configuration.md#a-chat-turn-left-running)). Einer,
der auf eine Freigabe oder auf Ihre Antwort auf eine Frage wartet, meldet sich
über diese.

**Auf dem Telefon** verhält sich der Chat wie eine Messenger-App: Das
Eingabefeld bleibt über der Tastatur und die Unterhaltung bei ihrer letzten
Nachricht, wenn sie aufgeht, Enter
beginnt eine neue Zeile, und Anhängen oder Diktieren liegen hinter einem **+**.
Felder sind nie so klein, dass iOS hineinzoomt.

**Zeichnungen.** Ein Agent mit [Visuals](reference/capabilities.md#visuals)
zeichnet unter seiner Nachricht - ein Diagramm, eine Erklärung mit Schiebereglern, eine
3D-Szene - und Sie sehen sie entstehen, während sie geschrieben wird; ihre Skripte
starten, wenn sie vollständig ist. Das Panel zeigt die ganze Zeichnung, passend zum
Gespräch, mit Schaltflächen für Vollbild, Code, Herunterladen, Kopieren eines SVG als
Bild, Zoomen und Speichern als [App](artifacts.md#visuals) mit einem Link zum
Teilen. Meldet eine Zeichnung einen Fehler, weiß der Agent schon davon; **Beheben**
fragt erneut. Auf einem Telefon öffnet ein Tippen sie im Vollbild.
Die Karte **Neueste Visuals** auf dem Dashboard zeigt die zuletzt für Sie
gezeichneten, jede öffnet das Gespräch, in dem sie entstand.

**Einem Durchlauf zusehen.** Beginnt ein Agent mit dem
[Webbrowser](reference/capabilities.md#browser-automation) auf einer Seite, erscheint
sein Browser live unter der Nachricht des Agents: ein Fenster mit der Adresse und der
Seite, wie der Agent sie sieht, einer Zeile über der Seite dazu, was er gerade tut, und
seinem Cursor, der zu dem wandert, was er anklickt oder ausfüllt. Das Fenster behält
seine Form und wächst und schrumpft mit der Unterhaltung; mehrere Durchläufe zugleich
stehen nebeneinander, zwei pro Reihe, wo Platz ist. Die Maximieren-Schaltfläche öffnet
einen im Vollbild, Wiederherstellen legt ihn zurück unter die Nachricht. Die vollständige
Liste der Schritte, jeder mit seinem Zweck, liegt hinter der Schritte-Schaltfläche.

**Einen Durchlauf übernehmen.** Während ein Durchlauf läuft, pausiert **Übernehmen** in
der Symbolleiste des Browsers den Agent nach seinem laufenden Schritt und gibt Ihnen die
Seite, im selben Fenster: klicken, tippen, scrollen, einfügen. **Zurückgeben**, und der
Agent macht dort weiter, wo Sie aufgehört haben. Kommt der Agent allein nicht über eine
Seite hinweg - eine Anmeldung, ein Captcha -, sagt der Browser *Der Agent
braucht Sie* und wofür. Wer Runs sehen, aber den Agent nicht bearbeiten darf, kann
zusehen, nicht steuern. Dasselbe Fenster öffnet sich über den Link eines Kanals auf
einer eigenen Seite. Siehe [Webbrowser](reference/capabilities.md#browser-automation).

**Auf die Seite zeigen.** Mit der Sprechblase in der Werkzeugleiste des Browsers
klickst du auf eine Stelle der Seite und schreibst eine Notiz dazu - *dieser Knopf,
nicht der andere*. **Add to message** legt die Seite als Bild mit markierter Stelle in
deine Nachricht, mit deiner Notiz und der Adresse der Seite, zum Senden oder
Weiterschreiben. Das geht auch bei einem beendeten Browse, auf seinem letzten Bild.

**Angemeldet bleiben.** Wenn der Browse für dich handelt - dein eigener Chat, deine
Direktnachricht, dein eigener Zeitplan -, bietet **Zurückgeben** *Anmeldung bei …
behalten* für die Seite an, auf der du bist. Hake es nach der Anmeldung an, und
spätere Browses für dich starten dort angemeldet: Cookies und Speicher der Seite
liegen versiegelt im Vault, nur für dich, werden nie angezeigt und nie für einen
Widget-Besucher, einen geteilten Raum, einen API-Schlüssel oder einen Ereignis-Trigger
genutzt. **Einstellungen → Anmeldungen** listet die behaltenen Seiten, und
**Vergessen** lässt den nächsten Browse abgemeldet starten. **Bei einer Website
anmelden** öffnet dort einen Browser auf einer beliebigen Seite, nur für dich, bevor ein
Agent ihn braucht: anmelden, mit angehaktem Feld zurückgeben, und die Anmeldung wird
genauso behalten. Dafür braucht das Deployment seinen Anmelde-Browser
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

## Wofür jeder Bereich da ist { #what-each-area-is-for }

Die Seitenleiste gruppiert sie. **Build** enthält Agents, Routines, Apps und
Activity; **Knowledge** enthält Knowledge bases, Documents, Skills und Context.
Zwei Gruppen sind bis zum Öffnen auf ihre Überschrift eingeklappt, weil man sie
einmal einrichtet und selten besucht: **Connections** (MCP servers, Channels,
Vault, Sandboxes) und **Organization** (Organizations, Groups). Eine eingeklappte
Gruppe öffnet sich auf jeder Seite in ihr von selbst und bleibt, wie Sie sie
verlassen haben.

| Bereich | Er hält | Lesen Sie |
|---|---|---|
| **Agents** | Den Katalog, den Builder, Versionen, Teilen, Testen, Aktivität | [Ihr erster Agent](first-agent.md) |
| **Chat** | Das Gespräch mit einem veröffentlichten Agent | [Oberflächen](channels.md) |
| **Knowledge** | Collections, Dokumente, Sync-Quellen, Ingestion-Einstellungen | [Dateiverarbeitung](file-processing.md) |
| **Skills** | Geschriebene Abläufe, die ein Agent bei Bedarf lädt | [Skills](skills.md) |
| **Context** | Dauerhaftes Wissen, das an viele Agents gebunden ist | [Context-Dateien](context.md) |
| **Routines** | Zeitpläne und Ereignis-Trigger | [Trigger](triggers.md) |
| **Runs** | Was lief, was es kostete, was es berührte, ob es fehlschlug | [Governance](governance.md#audit) |
| **Documents** | Alle Dateien, die Agents für Sie aufbewahren - Angehängtes und Geschriebenes | [Die Sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Wo Agents Code ausführen: Hosts, laufende Sessions, Policy | [Die Sandbox](sandbox.md) |
| **MCP servers** | Verbindungen zu externen Werkzeugen, persönlich und organisationsweit | [MCP](mcp.md) |
| **Channels** | Slack-, Telegram- und Mattermost-Bots, Widgets, gehostete Seiten | [Oberflächen](channels.md) |
| **Vault** | Zugangsdaten, pro Organisation versiegelt | [Secrets](secrets.md) |
| **Organizations** | Mitglieder, Rollen, Einladungen | [Berechtigungen](permissions.md) |
| **Settings** | Provider, Ingestion-Vorgaben, Benachrichtigungen, Ihr eigenes Profil | [Konfiguration](configuration.md) |
| **Admin** | Das Deployment selbst: Nutzer, Tenants, System, Deployment-Einstellungen | [Das Deployment](deployment.md) |

Der **Agents**-Katalog lässt sich nach **Category** und **Tag** filtern — den
editierbaren, organisationslokalen Labels, die auf der Karte jedes Agents
erscheinen. Jeder Filter ist ein Menü der Labels auf den Agents, die Sie sehen;
kreuzen Sie mehrere an, um ihn zu erweitern. Die Categories und Tags eines Agents pflegen Sie auf seiner
Detailseite, neben den Avatar-Steuerelementen, und die Änderung wirkt sofort,
ohne dass eine neue Version veröffentlicht wird.

## Sprachen { #languages }

Die Konsole spricht Englisch, Polnisch und Deutsch, vollständig bis auf die
rechtlichen Seiten, die Englisch bleiben. Die erste Karte des Rundgangs bietet die
drei an, und das Kontomenü wechselt die Sprache jederzeit; die Wahl wird im Browser
gespeichert. Produktwörter - Agent, Skill, Run, Budget, MCP und der Rest der Liste
unter [Übersetzen](howto/translate.md) - bleiben in jeder Sprache Englisch.

## Der nächste Schritt { #the-next-step }

Eine Seite, die leer ist, weil noch nichts existiert, bietet den Weg zum ersten
Eintrag an - einem Agent, einer Routine, etwas für eine Abteilung. Wer einen
Skill, eine Kontextdatei oder eine Wissensbasis anlegt, bekommt einen Toast mit
**Einem Agent hinzufügen**, sofern er Agents bearbeiten darf, sodass das Neue
ohne Umweg über den Builder bei einem Agent ankommt.

## Wenn eine Seite leer aussieht { #when-a-page-looks-empty }

**Ein leerer Zustand und eine fehlgeschlagene Anfrage sehen gleich aus.** Jede
Seite hier fächert in mehrere Abfragen auf und rendert "noch nichts da", wenn
eine davon fehlschlägt.

Prüfen Sie also den Netzwerk-Tab, bevor Sie schließen, dass eine Collection leer
ist oder ein Agent keine Runs hat. Das ist der mit Abstand häufigste Weg, auf
dem ein echtes Problem als ein stilles gelesen wird.

## Zusammenfassung { #recap }

- Das Dashboard besteht aus **sechsunddreißig Widgets**, die Sie selbst
  anordnen, gespeichert pro Person und pro Organisation — alle außer Ihren
  eigenen Benachrichtigungen hängen an der Berechtigung, die ihre Daten
  verlangen.
- Eine gespeicherte Anordnung **kann ausblenden und umsortieren, aber niemals
  etwas sichtbar machen** — das Tor läuft zuletzt.
- **Die Glocke** ist eine laufende Zählung ungelesener Einträge mit der
  vollständigen Liste einen Klick entfernt, unabhängig davon, auf welcher
  Seite Sie gerade sind.
- **Chat, Slack und die API sind derselbe Runner**, also ist das, was Sie in der
  Konsole sehen, das, was ein Kunde bekommt.
- **Änderungen von anderswo kommen von selbst an** — über die API, MCP oder den
  Assistenten —, und der Builder fragt, bevor er ungespeicherte Änderungen ersetzt.
- **Slash commands gehören Ihnen**, die eingebauten eingeschlossen, und Sie
  können die ausblenden, die Sie nicht nutzen.
- Eine Seite, die "noch nichts da" zeigt, kann **eine fehlgeschlagene Anfrage**
  sein und keine leere Ressource.
