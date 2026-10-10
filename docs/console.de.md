---
source_sha: "cb8a35a07876"
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

Sie kommen in Gruppen an:

| Gruppe | Beantwortet |
|---|---|
| *(ohne Titel, ganz oben)* | Die Zusammenfassung, deren Details der Rest der Seite ist |
| **Deployment** | Nur für einen [Deployment-Admin](permissions.md) — Plattformsummen, Health, aktivste Tenants, Bewertungen |
| **Attention** | Was wartet: [Freigaben](governance.md#approvals), jüngste Fehlschläge, Budget-Spielraum, [Ausgaben nach Abteilung](departments.md#a-departments-budget), MCP-Health, veraltetes Wissen, Ihre jüngsten [Benachrichtigungen](#the-bell) |
| **Usage** | Runs, Ergebnisse, Oberflächen, Latenz, Ausgaben, Modellmix, Versionsvergleich |
| **People** | Mitglieder, aktive Nutzer, Bewertungen, wer was tut |
| **Sandboxes** | [Kapazität, laufende Sessions, Policy](sandbox.md) |
| **Workspace** | Ihrer: Ihre Agents, Ihre Unterhaltungen, Ihre Aktivität, was mit Ihnen geteilt wurde |

Wer Agents baut, sieht über den Bändern außerdem **Erste Schritte**, bis jeder
Schritt erledigt ist: einen Agent anlegen, ihn veröffentlichen, ihm eine
Wissensbasis geben, Abteilungen hinzufügen, jemanden aus dem Team einladen und -
wer darf - einen Agent in eine Chat-App bringen. Jeder Schritt wird nach dem
abgehakt, was existiert, wo auch immer er erledigt wurde; wer die Karte schließt,
blendet sie in diesem Browser aus.

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

Unten rechts auf jeder Seite sitzt der **AI Architect**: ein Agent, den jede
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
stumm, und die Glocke in seinem Fenster schaltet die Sprechblasen ganz ab. Sein
Fenster öffnet sich mit vier Kacheln, sodass die erste Nachricht ein Klick ist, und
führt einen eigenen Verlauf. Auf dem Telefon füllt es den Bildschirm.

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
beim Provider besorgen, **Einstellungen → Assistent** öffnen, den Provider wählen
und den Schlüssel einfügen, dann ein Modell auswählen. Die Schaltfläche bekommt
nur, wer die Einstellungen der Organisation ändern darf; alle anderen erfahren,
wer das kann.

**Einstellungen → Assistent** enthält Ihre eigenen Tipps und, für alle, die die
Einstellungen der Organisation ändern dürfen, Namen, Begrüßung und Modell des
Assistenten sowie einen Schalter, der ihn für alle abschaltet.

## Änderungen von anderswo { #changes-made-elsewhere }

Eine offene Seite hält mit Änderungen Schritt, die anderswo gemacht werden: in
der Konsole eines Kollegen, durch ein Skript mit einem [API-Schlüssel](api.md),
durch Claude Code über den [MCP-Server der Plattform](mcp.md#agenticos-as-an-mcp-server)
oder durch den Assistenten. Jeder erfolgreiche Schreibvorgang über die öffentliche
API wird den offenen Konsolen der Organisation gemeldet, sobald er festgeschrieben
ist, und eine Liste oder Detailseite ohne ungespeicherte Änderungen lädt an Ort
und Stelle neu — ein mit einem Schlüssel erstellter Agent erscheint auf der Seite
Agents, ohne dass Sie neu laden.

Die Ausnahme ist der Builder, weil er Ihren Entwurf beim Tippen speichert. Ändert
sich der Agent, den Sie bearbeiten, anderswo, hört er auf zu speichern und holt
die neue Version. Ohne ungespeicherte Änderungen übernimmt er sie einfach; mit
ungespeicherten Änderungen sagt er, wer ihn worüber geändert hat, und wartet auf
Ihre Wahl: **Neu laden** (deren Version) oder **Meine Änderungen behalten** (Ihre,
über deren gespeichert).

Sie erfahren nur, was Sie lesen dürfen: Eine Änderung an einem Agent, einem
Skill, einer Wissensbasis, einer Kontextdatei oder einer Seite, die Sie nicht
sehen, erreicht Ihre Konsole nie, und eine Löschung erreicht nur Rollen, die
jede Zeile dieser Art sehen. Bricht die Verbindung ab, arbeitet die Konsole wie
bisher und verbindet sich selbst wieder.

## Chat { #chat }

Hier sprechen Sie mit einem veröffentlichten Agent. Die Auswahl entscheidet,
welcher Agent antwortet, und der Run verhält sich genau so, wie er es in Slack
oder hinter der API täte — dasselbe Budget, dasselbe Tor für Freigaben, dieselbe
Audit-Spur, weil [jede Oberfläche durch einen einzigen Runner
läuft](channels.md).

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

**Auf dem Telefon** verhält sich der Chat wie eine Messenger-App: Das
Eingabefeld bleibt über der Tastatur und die Unterhaltung bei ihrer letzten
Nachricht, wenn sie aufgeht, die Tab-Leiste tritt beim Tippen zur Seite, Enter
beginnt eine neue Zeile, und Anhängen oder Diktieren liegen hinter einem **+**.
Felder sind nie so klein, dass iOS hineinzoomt.

**Einem Durchlauf zusehen.** Ein Agent mit
[Webbrowser](reference/capabilities.md#browser-automation-choose) öffnet
ein Panel neben dem Transkript, sobald er eine Seite durchzuarbeiten beginnt: das
Sichtfenster im Verlauf, die Seite, auf der er ist, und jeden Schritt mit der
Wahrscheinlichkeit, mit der die Engine ihn gewählt hat. Diese Zahl ist der Grund,
warum es das Panel statt eines Spinners gibt — ein Durchlauf, der auf einer Auswahl
von 0,31 gehandelt hat, ist einen Blick wert. Es bleibt stehen, wenn der Durchlauf
endet, denn *von der Seite blockiert* ist eine Antwort über die Seite. Schließen Sie
es, bleibt es für diesen Durchlauf geschlossen.

## Wofür jeder Bereich da ist { #what-each-area-is-for }

| Bereich | Er hält | Lesen Sie |
|---|---|---|
| **Agents** | Den Katalog, den Builder, Versionen, Teilen, Testen, Aktivität | [Ihr erster Agent](first-agent.md) |
| **Chat** | Das Gespräch mit einem veröffentlichten Agent | [Oberflächen](channels.md) |
| **Knowledge** | Collections, Dokumente, Sync-Quellen, Ingestion-Einstellungen | [Dateiverarbeitung](file-processing.md) |
| **Skills** | Geschriebene Abläufe, die ein Agent bei Bedarf lädt | [Skills](skills.md) |
| **Context** | Dauerhaftes Wissen, das an viele Agents gebunden ist | [Context-Dateien](context.md) |
| **Routines** | Zeitpläne und Ereignis-Trigger | [Trigger](triggers.md) |
| **Runs** | Was lief, was es kostete, was es berührte, ob es fehlschlug | [Governance](governance.md#audit) |
| **Sandboxes / Workspaces** | Isolierte Datei- und Shell-Sessions, in denen ein Agent gearbeitet hat | [Die Sandbox](sandbox.md) |
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
