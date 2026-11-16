---
source_sha: "1d738a8f00d6"
---

# Die Konsole { #the-console }

Das persönliche Dashboard liest Onboarding und Briefing gemeinsam, bevor es die erste Zeile anzeigt. Ein reservierter Ladebereich verhindert wechselnde Platzhalterlayouts; andere Widgets laden unabhängig. Fehlgeschlagene Lesevorgänge können erneut versucht werden. Arbeitsbereiche lassen sich auf Smartphones erweitern; beim Wechsel zum Desktop kehrt die Navigation zurück und ungespeicherte Felder bleiben erhalten.

Die Kontexteinstellungen zeigen kompakte Dateizeilen mit Einstellungen für die Nutzung durch den Agenten. Lange Beschreibungen strecken benachbarte Dateien nicht mehr; ausschließlich eingefügter Kontext erhält einen neutralen Hinweis. Availability zeigt das Plattformlogo neben dem Botnamen. Beim Teilen einer App stehen Seitenlink und Personen mit Zugriff zuerst. Ablaufdatum, Versionsbindung, Einbettung und Passwort sind zunächst unter Link-Einstellungen eingeklappt. Aktive Einschränkungen bleiben als Kennzeichnungen sichtbar; Einklappen erhält die Bearbeitung.

Auf Telefonen verwendet die Kanalregistrierung eine kompakte Plattformauswahl. Abbrechen eines neuen Kanals, eines neuen Tresorschlüssels oder einer Schlüsselrotation löscht die eingegebenen Zugangsdaten. Kanal- und Tresorformulare sperren Bearbeitung und Schließen während des Schreibvorgangs; eine Ablehnung erhält die Werte zur Korrektur und Wiederholung. Kanalbearbeitung und Schlüsselrotation halten ihre Aktionsleiste auch in niedrigen Fenstern sichtbar.

Auf Telefonen zeigt eine neue Kontextdatei den Quelltexteditor vor optionalen Details. Details nennt den wirksamen Zugriff auch im eingeklappten Zustand; öffne den Bereich, um Beschreibung oder Zugriff zu ändern. Eine abgelehnte Beschreibung öffnet den Bereich automatisch zur Korrektur.

Formulare für neue Projekte, Kontextdateien und Datasets fragen vor dem Verwerfen eines Entwurfs. Bleiben erhält ihn, Verwerfen setzt ihn zurück. Beim Anlegen sind Felder, Abbrechen, Schließen und Escape bis zum Ende des Schreibvorgangs gesperrt. Eine Ablehnung erhält die Werte und erlaubt wieder die Bearbeitung. Der Kontextquelltext ist währenddessen schreibgeschützt.

Bei mehreren abgelegten Kontextdateien bietet das Schließen nur Bleiben oder Verwerfen; mit Erstellen werden sie der Reihe nach verarbeitet. Dataset-Details und Fallformulare sperren beim Speichern ebenfalls Felder und Schließen, einschließlich des Formular/JSON-Wechsels. Speichern bleibt in kurzen Telefonfenstern erreichbar.

Beim Start der MCP-Anmeldung bleibt das Formular offen, bis das Zustimmungsziel bereitsteht. Ein abgelehnter Start erhält die Werte für Korrektur und Wiederholung.

Beim Bearbeiten eigener Slash-Befehle fragt die Konsole vor dem Verwerfen eines Entwurfs. Während des Speicherns sind Felder und Schließen gesperrt; eine Ablehnung erhält den Entwurf. Auf Telefonen stehen die Aktionen in einer eigenen Zeile mit Touch-Zielen. Ein laufender Umschaltvorgang sperrt konkurrierende Aktionen; Löschen verlangt Bestätigung. Auch MCP-Verbindungsformulare sperren Felder und Schließen beim Speichern.

Die Konsole ist die Webanwendung, über die alles andere auf dieser Site
konfiguriert wird. Diese Seite ist die Landkarte: wofür jeder Bereich da ist,
und welche Seite ihn ausführlich erklärt.

Wenn du Projekteinstellungen, den Organisationsnamen, das Ausgabenlimit, die Sprachvorgaben, die Aufbewahrungszeiten, einen Skill oder eine Kontextdatei bearbeitest, fragt die Konsole vor dem Verlassen, ob du speichern, verwerfen oder bleiben möchtest. Das gilt auch beim Wechsel von einer bearbeiteten Skill-Ressource zu einer anderen Datei. Ein abgelehnter Speichervorgang lässt den Entwurf offen; **Save file** verwirft ihn erst nach der Bestätigung des Servers. Während dieses Speichervorgangs ergänzter Text bleibt ungespeichert.

Auf dem Telefon zeigen Wissensbasis-Dokumente und Organisationsmitglieder beschriftete Zeilen mit sichtbaren Aktionen. Das Entfernen eines Mitglieds erfordert eine Bestätigung; bei Ablehnung bleibt sie offen. Dialoge zum Erstellen einer Wissensbasis, zur Verarbeitung und zum Embedding-Anbieter sperren während des Speicherns ihre Felder und bleiben offen; nach einer Ablehnung lassen sie sich wieder bearbeiten und schließen. Ein fehlgeschlagener Dokumentdownload zeigt einen Fehler und kann erneut versucht werden.

Wenn du die Frage oder den Suchbereich der Wissenssuche änderst, werden bisherige Ergebnisse entfernt und die laufende Anfrage abgebrochen. Eine verspätete Antwort kann die Ergebnisse einer neueren Suche nicht ersetzen.

Im öffentlichen Chat kannst du während des Verbindungsaufbaus schreiben. Send wird erst aktiviert, wenn der aktuelle WebSocket geöffnet ist. Eine neue Unterhaltung wartet auf ihre eigene Verbindung; ein früher Klick kann die erste Frage nicht unbemerkt verlieren.

Wenn Sie einen einzelnen Screen suchen, ist der schnellste Weg das **"?"** in
der Kopfzeile einer Seite — es spielt den Rundgang dieser Seite ab, und eine
Seite, deren Kopfzeile kein "?" trägt, hat keinen Rundgang abzuspielen. Der Chat
hat keine Kopfzeile: Seine Tipps stehen in den Chat-Einstellungen, den Reglern
neben dem Mikrofon.

Ressourcenlisten, darunter Inbox und Routines, füllen auch im leeren Zustand die verbleibende Seitenhöhe. Routines bietet Vorlagen im Erstellungsformular statt in einem eigenen Ideenbereich an.

Im Chat sind Agentenporträts größer und ohne Ringe. Der Files-Schalter bleibt beim Öffnen und Schließen des Bereichs im Eingabefeld; reduzierte Bewegung wird berücksichtigt. Die Chat-Einstellungen zeigen zuerst das aktuelle Modell. Unter **Modell ändern** lassen sich vorausgefüllter Anbieter und Modell bearbeiten; erst die Bestätigung übernimmt die Änderung. Anhangskarten stehen ohne zusätzliches Schattenpanel über dem Eingabefeld.

Seiteneinführungen und Erläuterungen zu Einstellungen sind über das Informationssymbol neben der Überschrift erreichbar. Aktuelle Zusammenfassungen und Warnungen vor destruktiven Aktionen bleiben sichtbar.

Bei Agenten, Skills, Context und im Ausführungsverlauf öffnet **Filter** zusätzliche Optionen auf jeder Bildschirmgröße und zeigt die Anzahl aktiver Filter.

Agentenkarten zeigen Status, Zugriff und Bearbeitungsdatum direkt. Skills- und Context-Karten behalten Dokumentvorschau, Zusammenfassung, **Used by** mit Agentenporträts und **Add to an agent** sichtbar. Kategorie und Zielgruppe stehen in einer kompakten Zeile neben der Aktion. Es gibt keine aufklappbaren Details. Zum Löschen eines Skills oder einer Kontextdatei öffnet man den Editor und das Drei-Punkte-Menü neben **Share**; das Löschen erfordert weiterhin eine Bestätigung und Bearbeitungsrechte.

Namen, Navigation und Formularwerte verwenden kräftigen Vordergrundtext; Metadaten
bleiben nachgeordnet. Hauptaktionen haben eine kontrastreiche neutrale Fläche. Glass
behält das native Material, gibt Inhalten, Karten und Menüs aber deckendere
Leseflächen.

Organisations-, Agenten- und Projektregister haben passende Symbole. Budgetzeilen
zeigen Agentenporträts.

Generierte Porträts verwenden ausgewählte Blobatar-2.7-Formen und hellere Farbtöne; ruhende Gesichter bewegen sich beim Darüberfahren, arbeitende Agenten behalten ihre Denkanimation. Hochgeladene Bilder bleiben erhalten. Neue Starteragentenbilder gehören zur gleichen Familie; vorhandene gespeicherte Bilder werden nicht automatisch ersetzt.

Die Chat-Einstellungen zeigen Browser und Work on vor Permissions.
Gesprächsbenachrichtigungen und Kontoverbindungen bleiben unter den
Freigabeeinstellungen.

Die Chat-Einstellungen haben eine feste Überschrift und Schließen-Schaltfläche über dem scrollbaren Inhalt. Informationssymbole erklären Modell, Browser, Work on und Berechtigungsmodi bei Bedarf; die Erklärung des ausgewählten Modus bleibt sichtbar. Unter **Knowledge bases → Integrations** passen sich kompakte Panels für Integrationen und lokale Dienste ihrem Inhalt an; Erläuterungen stehen hinter Informationssymbolen.

Die Agenten einer Unterhaltung sind nach ihrer letzten Nachricht oder ihrem letzten übergeordneten Lauf sortiert, die neuesten zuerst. Die eingeklappte Chat-Leiste behält die volle Avatargröße bei, überlagert bis zu drei Bilder und blendet ältere Teilnehmer aus; die vollständige Liste bleibt im Tooltip verfügbar.

Ist **Approve everything** nicht verfügbar, unterscheiden die Chat-Einstellungen zwischen fehlender Entscheidungsberechtigung und einer Organisationsrichtlinie, die pauschale Zustimmung deaktiviert. Wer Genehmigungen entscheiden darf, erhält einen Link zu **Budget und Genehmigungen**, um die Richtlinie ausdrücklich zu ändern. Der Chat ändert die Organisationsrichtlinie niemals automatisch.

Dialoge behalten auf dem Smartphone an allen Rändern 12 px Abstand. Kompakte Seitenköpfe zeigen Titel und Aktionen in einer Zeile, wenn genug Platz ist. Die Context-Beschreibung öffnet sich über die Editorleiste.

Auf dem Smartphone bleiben die Hauptaktionen sichtbar; weitere Befehle öffnet **Weitere Seitenaktionen**. Inbox-Filter und Tabellenformat werden über Auswahllisten gewählt. Einstellungen mit vielen Bereichen haben ein Bereichsmenü; der MCP-Client wird aus einer Liste gewählt. Projekt- und Workspace-Dateien öffnen sich im Vollbildleser; der Zurück-Pfeil führt zu den Ordnern. Im Workflow-Schritteditor wählst du Einstellungen, Eingabe oder Ausgabe. Beim Wechsel bleiben Änderungen erhalten; auf dem Desktop stehen die Bereiche weiterhin nebeneinander.

Jede ausdrückliche Aktion **New chat** fokussiert den Editor erneut, auch bei einem leeren Entwurf; die Vergabe einer Gesprächs-ID während des Schreibens fordert keinen Fokus an.

Markdown-Felder und Dateieditoren bieten ebenfalls eine Schaltfläche zum Vergrößern, ohne den aktuellen Entwurf zu verwerfen. Beschreibung und Kategorie eines Skills lassen sich über dem Editor aufklappen. Das Chat-Eingabefeld benötigt weniger Platz und begrenzt lange Entwürfe anhand der verfügbaren Bildschirmhöhe. Beim Öffnen der Navigation erhält das Panel den Fokus; mit Tab sind dessen Bedienelemente weiterhin erreichbar. Auf Telefonen bietet der Workflow-Canvas eine schwebende Vollbild-Schaltfläche, öffnet sich mit dem ganzen Ablauf im Blick und startet mit ausgeblendeter Minimap.

Auf Telefonen bleiben Beschreibung, Kategorie und Dateiverwaltung in Skill- und Kontexteditoren beim Schreiben eingeklappt. Eine Schaltfläche wechselt zwischen Quelltext und Vorschau. Apps bietet schwebende Zurück- und Optionsschaltflächen; die Optionen zeigen Titel, Version, Design und Freigabe.

Seitenüberschriften verwenden die Abstände des umgebenden Layouts ohne Verdopplung. Karten, Seitenleistenzeilen, Tabs und leere Zustände haben auf dem Desktop kompaktere Abstände; Bedienelemente behalten größere Touchflächen.

Sekundäre Schaltflächen und Filter teilen eine deutlichere Füllfläche, kontrastreiche Beschriftungen und klare Zustände bei Hover, Betätigung und geöffnetem Menü. Die Modellauswahl im Chat verwendet denselben Stil.

Persönliche Einstellungen behalten horizontale Tabs am oberen Rand, einschließlich der Desktop-Seiten innerhalb der App. Beschreibungen stehen direkt im Panel; Formulare passen sich ihrem Inhalt an. Konto enthält Passwortänderung und aktive Sitzungen; die Passwortaktion steht unter den Feldern.

Profilfelder stehen bei genügend Platz nebeneinander; **Änderungen speichern** ist erst nach einer Bearbeitung verfügbar. Eine Fähigkeitskarte hat einen Bereich zum Öffnen der Einstellungen und einen separaten Schalter zum Aktivieren. Beispiele stehen im Einstellungsbereich hinter dem Informationssymbol; die Illustration der Galerie wird dort nicht wiederholt.

Dialoge für Vorlagenkategorien passen sich ihrem Inhalt an; die Auswahl einer Branche für Agenten oder Skills öffnet die größere Bibliothek. Auf dem Telefon erscheinen die Stile als kompakte Zeilen mit Miniaturen.

Anweisungen für Agenten und Projekte haben eine kompakte gemeinsame Leiste für Titel, Hilfe, Quelltext/Vorschau und Vergrößern. Vergrößerte Markdown-Ansichten behalten den gewählten Modus. Ungenutzte Prompt-Variablen sind zunächst eingeklappt; vorhandene eigene Variablen oder eine eigene Zeitzone halten den Bereich offen. Vergrößerte Text- und Dateieditoren behalten auf dem Telefon gleichmäßige Außenabstände. Texteingaben nutzen dort größere Schrift, ohne Desktop-Felder zu vergrößern.

Auf dem Telefon wechselt das Nachrichtenfeld beim Fokussieren in eine kompakte Schreibzeile mit Anhängen und Senden. Agentenauswahl und Spracheingabe bleiben unter **+** erreichbar. Begrüßung und Verbindungsvorschläge treten beim Schreiben zurück; Ergänzungsmenüs passen sich der verfügbaren Höhe an. Beim Fokuswechsel zum Senden bleibt das Layout stabil.

Beim Öffnen des Hauptchats erhält das Eingabefeld den Fokus, sobald es beschreibbar ist, auch wenn während des Verbindungsaufbaus noch die Navigationsschaltfläche fokussiert war. Ein währenddessen bewusst verwendetes Bedienelement behält den Fokus.

Auf dem Smartphone sind die Aktionen unter Nachrichten von Nutzern und Agenten zunächst ausgeblendet. Die Schaltfläche **Mehr** neben dem Absender blendet Kopieren, Antworten, Bewertungen und weitere verfügbare Aktionen ein oder aus. Am Desktop erscheinen die Bedienelemente weiterhin beim Darüberfahren.

CSS-Importe, Bilder und Fonts werden relativ zum Stylesheet über dieselbe autorisierte Dateiquelle aufgelöst. Vorschauen erlauben vier verschachtelte Ebenen, 64 Ressourcen, 8 MiB Eingabedaten und 16 MiB expandierte Ausgabe. Dateilinks behalten ihre ursprüngliche Konversation oder ihren lokalen Ordner, gespeichert mit dem Verlauf des Turns. Eine Änderung von Work on leitet sie nicht um. Ältere Turns ohne gespeicherte Herkunft erhalten keine geratenen Links. Lokale Dateien benötigen weiterhin eine aktuelle native Ordnerfreigabe.

Dateilink-Metadaten speichern für lokale Schritte nur eine opake Herkunftskennung. Die Ordnerzuordnung bleibt auf dem initiierenden Desktop und ist auf Konto und Organisation begrenzt; andere Teilnehmer und Computer können diese Links nicht auflösen. Ältere Herkunftsangaben mit einem lokalen Pfad werden beim Lesen gespeicherter Schritte weggelassen.

Die **Visual map** im Agenten-Builder passt die gesamte Konfiguration beim Öffnen und bei Größenänderungen ein. **Reset view** passt sie nach Verschieben oder Zoomen erneut ein. Große Gruppen zeigen sechs Einträge und die verbleibende Anzahl; wählen Sie eine Gruppe für die vollständige, scrollbare Liste. Die Workflow-Minimap zeigt den gesamten Graphen und wechselt den Ausschnitt, ohne den Zoom zu ändern.

Das Testpanel im Builder lässt sich auf den ganzen Arbeitsbereich erweitern, ohne Unterhaltung oder ungesendeten Text zurückzusetzen. Der Vergleich zweier Versionen öffnet diesen Bereich automatisch; die Vollbild-Schaltfläche oder Escape führt zum Builder zurück. Die Versionsauswahl hat eine eigene Zeile, damit die Teststeuerung auch in schmalen Panels nutzbar bleibt. Auf dem Telefon wechseln die Versionsschaltflächen zwischen den verglichenen Chats; beide Gespräche laufen weiter und behalten ihre Entwürfe. Der gemeinsame Prompt erreicht weiterhin beide gleichzeitig.

Die Navigation erhält gemeinsame Seitenlayouts beim Wechsel zwischen Bereichen und blendet kurz über, statt den Rahmen neu aufzubauen. Reduzierte Bewegung deaktiviert den Effekt. Dashboard-Karten warten auf die gespeicherte Anordnung, berechtigungsabhängige Seiten auf deren Prüfung und die Benutzerliste der Administration beginnt mit einem Ladezustand statt einer vermeintlich leeren Liste. Gruppen- und App-Autorenfilter reservieren ihren Platz beim Laden. Quellenmarkierungen im Inbox warten auf Katalogmetadaten; Links zur Arbeitskonversation öffnen dieselbe Chat-Route wie die Seitenleiste.

Auf dem Smartphone halten gesendete Nachrichten unterhalb der schwebenden Chat-Schaltflächen an, damit das Benutzerbild sichtbar bleibt. Der Gesprächsanfang und der reservierte Platz für eine Antwort berücksichtigen denselben Abstand zur Werkzeugleiste; Desktop und eingebettete Chats behalten ihren kleineren Abstand.

Standardagenten schließen einmalige Anfragen ab, ohne die Antwort durch eine optionale Automatisierungsfrage offen zu halten. Fragen klären notwendige Entscheidungen zur aktuellen Aufgabe oder zu einer angefragten beziehungsweise akzeptierten Automatisierung. Optionale Einrichtungskarten bleiben unverbindliche Vorschläge und blockieren den Abschluss nicht.

Die kompakte Quellen-Schaltfläche unter einer Antwort öffnet Sources neben dem Gespräch, auf dem Smartphone als vollbreites Panel. Files und Sources teilen sich den Seitenbereich: Das Öffnen eines Panels ersetzt das andere. Webquellen zeigen das ohne Referrer geladene Favicon oder ein bekanntes Dienstlogo; bei fehlendem Symbol bleibt der Globus. Wissensquellen behalten ihre Dateisymbole und die Originaldokumentansicht.

Weblinks in Antworten verwenden dieselbe Favicon-Regel unabhängig von MCP-Verbindungen. Symbole unbekannter Seiten werden über den Proxy unter derselben Origin wie die Konsole und den festen Symboldienst von DuckDuckGo geladen. Dieser erhält nur den Hostnamen, keine Cookies oder IP-Adresse des Lesers, URL-Pfade oder Abfrageparameter. Der Proxy verweigert Weiterleitungen, nicht-rasterbasierte Inhalte und Symbole über 64 KiB; das Zeitlimit beträgt drei Sekunden. Bei fehlenden oder nicht erreichbaren Symbolen erscheint ein Globus. Inaktive Transkriptansichten laden weder entfernte Bilder noch Symbole unbekannter Seiten.

Ein fehlgeschlagener Chat-Run zeigt seinen Fehler getrennt von der Antwort und außerhalb der eingeklappten Tool-Schritte, auch nach dem Neuladen. Inhaltsfilter des Anbieters erhalten eine ausdrückliche Erklärung; rohe Anbieterantworten und unbekannte historische Fehlermeldungen werden nicht in geteilte Transkripte kopiert. Teilergebnisse bleiben sichtbar, und fehlgeschlagene Arbeit erscheint nicht als abgeschlossen.

## Das Dashboard { #the-dashboard }

Die Startseite ist ein **anordenbares Raster aus Widgets**, und sie ist die
Antwort auf die Frage "was passiert gerade", ohne fünf Seiten zu öffnen.

Es gibt siebenundfünfzig Karten. Sie werden nicht alle davon sehen: **eine Karte
hängt an der Berechtigung, die ihre Daten verlangen**, also wird ein Widget, das
Sie nicht lesen dürfen, nie eingehängt und seine Abfragen werden nie gestellt —
außer Ihren eigenen Benachrichtigungen weiter unten, die nur verlangen, dass Sie
angemeldet sind. Eine leere Gruppe verschwindet samt ihrer Überschrift, statt
leer dazustehen.

Ein Schalter oben sagt, wessen Dashboard es ist, und bietet nur die Ansichten
an, die Sie öffnen dürfen. Alle starten in der Ansicht **Ich**:

| Ansicht | Beantwortet |
| --- | --- |
| **Ich** | Eine Begrüßung, Ihr Zeitraum und alles, was auf Sie wartet, in zwei Sätzen - Aufrufe, Antworten zur Prüfung, durchgefallene Suites, Vorschläge des Assistenten; Ihre Runs, wie viele fertig wurden, was auf Sie wartet (gleich gezählt) und was es gekostet hat; dann die Aufrufe, die auf Sie warten, Ihre Unterhaltungen, die Agents, die Aufmerksamkeit brauchen, die Verbesserungen, die auf Sie warten, Ihre Agents, was mit Ihnen geteilt wurde, Ihre [Datasets](datasets.md) mit dem, woran ihre Fälle die Antwort messen, die neuesten Eval-Runs und Suites, die Vorschläge des Assistenten nach Agent, Skill und Datei und die Wissenslücken |
| **Ich** | Eine Begrüßung und Ihr Zeitraum in einem Satz; Ihre Runs, wie viele fertig wurden, was auf Sie wartet und was es gekostet hat; dann die Aufrufe, die auf Sie warten, Ihre Unterhaltungen, Ihre Agents und was mit Ihnen geteilt wurde |
| **Organisation** | Die anordenbare Seite unten |
| **Gruppe** | Die Mitglieder einer [Gruppe](departments.md) - ihre Runs, Ausgaben, Modelle, wann sie arbeiten und wer es am meisten nutzt. Die Gruppe wählen Sie neben dem Schalter. Eine Gruppe, deren Mitglieder im Zeitraum nichts ausgeführt haben, sagt das einmal, mit einem Weg zur Gruppe, statt eine Seite leerer Karten zu zeigen |
| **Deployment** | Nur für einen [Deployment-Admin](permissions.md) — Plattformsummen, Health, aktivste Tenants, Bewertungen |

In **Ich** listet **Agents, die Aufmerksamkeit brauchen** die Agents, die Sie
sehen dürfen, mit negativ bewerteten Antworten, fehlgeschlagenen Runs oder einer
durchgefallenen Eval-Suite im Zeitraum - nur Zahlen, nie das Gesagte - mit
**Verbessern** bei denen, die Sie bearbeiten dürfen. Die Agent-Galerie markiert
dieselben Agents der letzten dreißig Tage mit dem Abzeichen **Braucht
Aufmerksamkeit**, das beim Überfahren sagt, warum. Antworten und Runs zählen
nur für die Version, die der Agent jetzt in seiner Standardumgebung ausliefert:
Das Veröffentlichen einer Korrektur löscht das Signal, bis die neue Version
eigene sammelt. Beides erfordert `runs:view`.

Darunter listet **Verbesserungen, die auf Sie warten** die
[Verbessern](authoring.md#the-improve-wizard)-Sitzungen, die für Ihren nächsten
Schritt oder Ihre Entscheidung angehalten haben, jede an ihrem Halt geöffnet, und
die [Prüfungen einer Skill-Änderung](skills.md#when-an-agent-got-worse), über die
Sie entscheiden können und die noch laufen oder auf eine Entscheidung warten.
Danach folgen die von Agents vorgeschlagenen Skill-Änderungen, dann die
festgesetzten Agents und die Forks, an denen main
[vorbeigezogen ist](skills.md#which-version-an-agent-reads). Ein Fork wird von
dort nachgezogen, ein festgesetzter Agent auf der Seite seines Skills verschoben.

Die Ansicht der Organisation zeigt die Karten, die mit Daten antworten, in
Gruppen. Der Rest - Integrationen, Kanäle, Routinen, Wissens-Sync, Abteilungen,
Mitglieder, Sandboxes - wartet im Katalog, einen Klick entfernt unter **Customize**:

| Gruppe | Beantwortet |
| --- | --- |
| _(ohne Titel, ganz oben)_ | Die Zusammenfassung, Runs im Zeitverlauf und wie sie ausgingen |
| **Needs attention** | Was wartet: [Freigaben](governance.md#approvals), jüngste Fehlschläge, Budget-Spielraum, Ihre jüngsten [Benachrichtigungen](#the-bell) |
| **Usage & cost** | Welche Agents genutzt werden, Ausgaben, [Anrufminuten](#voice-calls), wann gearbeitet wird, woher Runs kommen, Modellmix, Latenz, Antwortqualität, wer es nutzt |

Die Karte **Freigabe-Ergebnisse (Approval outcomes)** wartet im Katalog, für alle, die
Workflows ansehen dürfen. Sie zeigt, wie Personen die [Freigabeschritte](workflows.md#running-a-workflow)
entschieden haben, nach denen die Workflows im Zeitraum fragten. Sie zeigt den Anteil
der wie vorgeschlagen Freigegebenen, die Bearbeitungen und ihre mediane Änderung, die
Zeit bis zur Entscheidung und die fünf Workflows mit den meisten Anfragen. Sie bleibt
leer, wenn im Zeitraum des Dashboards keine Anfrage gestellt wurde.

Die Karte **Workflow-Protokolle (Workflow logs)** wartet ebenfalls im Katalog, für alle,
die Workflows ansehen dürfen. Sie zeigt die neuesten Zeilen, die die
[Quick Logs](workflows.md#the-logs-page) der Workflows, die Sie ansehen dürfen, in echten Runs
geschrieben haben, und wie viele Zeilen die letzten 24 Stunden brachten, darunter
Fehler. Eine Zeile verlinkt ihren Run, der Workflow-Name die Logs-Seite des Workflows.
Sie bleibt leer, bis ein Schritt mit Quick Log gelaufen ist, und ignoriert den Zeitraum
des Dashboards.

Das Dashboard öffnet mit **Erste Schritte**, bis jeder Schritt erledigt ist:
Agents etwas über sich erzählen, ein Gespräch beginnen, einen Dienst mit dem
eigenen Konto verbinden, eine Routine einrichten und einen Agent bauen -
Letzteres ist eine Frage an den Architect, der ihn mit Ihnen baut. Wer Agents
baut, hat danach die Schritte der Organisation: einen Agent veröffentlichen, ihm
eine Wissensbasis geben, Abteilungen hinzufügen, jemanden aus dem Team einladen
und - wer darf - einen Agent in eine Chat-App bringen. Jeder Schritt wird nach dem
abgehakt, was existiert, wo auch immer er erledigt wurde, nicht nach einem Klick
auf die Karte; wer die Karte schließt, blendet sie in diesem Browser aus.

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

## Routinen und Beobachtungen { #routines-and-watches }

Routinennamen werden auf Telefonen umgebrochen. Ohne Suchtreffer erscheint **Suche löschen**; **Erneut versuchen** lädt Aufgaben und Beobachtungen nach einem Lesefehler neu. Zeitpläne und Ereignisauslöser werden zwischen festem Kopf und Aktionsleiste bearbeitet. Schreibvorgänge sperren Felder und Schließen bis zum Abschluss; eine Ablehnung erhält den Entwurf.

Routines hat zwei Tabs. **Agentenaufgaben** startet einen gewählten Agenten nach
Zeitplan oder Ereignis mit seinen Werkzeugen; die Läufe erscheinen in Activity.
**Meine Beobachtungen** liest nur persönliche verbundene Konten und sendet
Ergebnisse in den privaten Posteingang. Jeder Tab hat eigene Erstellungsaktionen.
`/routines?tab=watches` öffnet die Beobachtungen. Eine Prüfung stellt höchstens
30 Modellanfragen, lange Ergebnisse werden gekürzt; so bleibt eine Beobachtung
eines großen Workspace günstig.

Organisation → Proaktivität trennt Vorschläge, Überwachung, gemeinsame Limits, Zustellungszeiten und Begrüßungen. Ungespeicherte Änderungen lassen sich verwerfen. Hintergrunddienste zeigen Status und Verbrauch; Modell- und Budgeteinstellungen werden pro Dienst aufgeklappt.

Zeitgesteuerte, ereignisgesteuerte und überwachende Routinen verwenden denselben Dialograhmen mit festem Kopfbereich und Navigation sowie einem scrollbaren Formular. Das Erstellen einer Überwachung führt durch Konfiguration, Nachricht und Zeitplan; Zurück erhält den Entwurf. Die Agentenauswahl zeigt dieselben Avatare wie der Chat. Ausführungs- und Zustelloptionen einer Überwachung stehen gemeinsam in einem Bereich für erweiterte Optionen.

Discover beginnt auf dem Dashboard mit illustrierten Fähigkeiten. Beim Überfahren
einer Kurve in _Your period_ erscheinen Zeitabschnitt und Wert; Ausgaben werden
als Geldbetrag formatiert. Projekte zeigen Beschreibungen, Agentenzeilen dieselben
Avatare wie im Chat.

Dashboard-Karten verwenden einheitliche kompakte Zeilen, Dienstsymbole und Statusbezeichnungen. Kennzahlen und Diagramme passen sich der Kartenbreite an, auch in eigenen Anordnungen. Ladeplatzhalter entsprechen dem Inhaltstyp; ein nicht verfügbares Briefing bietet einen erneuten Versuch an, statt fälschlich keine Vorschläge zu melden.

Ein leerer Chat begrüßt nach lokaler Tageszeit und zeigt zuerst das Eingabefeld, darunter bis zu vier Nachrichtenvorschläge. Veröffentlichte Agentenvorschläge haben Vorrang; AgenticOS kann persönliche Vorschläge nutzen, die fünf Minuten im Cache der aktuellen Kontositzung bleiben. Platzhalter reservieren den Raum, bis die Quelle feststeht. Posteingangs- und Hintergrundvorschauen sowie Tastenkürzel bleiben vom Startbildschirm entfernt; öffne dafür Inbox oder Background work über die Navigation.

Gespeicherte Chats zeigen sofort Verlaufsplatzhalter, ohne Begrüßungsblitz; Seitenleiste und Verlauf laden unabhängig. Manuell gesendete Nachrichten gleiten nach oben, Nachrichten aus der Warteschlange verschieben den Leser nicht. Scrollen, Berührung und Tastatur brechen die Bewegung ab. Gemeinsame Menüs und Dialoge verwenden kleine, sanfte Übergänge; die Motion-Einstellung deaktiviert Bewegung.

## Der Posteingang { #the-inbox }

Der **Posteingang**, unter dem Chat in der Seitenleiste, ist, was die Plattform
Ihnen aus eigener Initiative gebracht hat: was Ihre
[Beobachtungen](governance.md#proactive-work) in Ihren Verbindungen gefunden und
was der nächtliche Blick vorgeschlagen hat. Die Zahl daneben sagt, wie viel
wartet. Er liest sich wie ein Postfach: eine Zeile je Eintrag, Dringendes
zuerst, woher und wann, und die Antworten in der Zeile.

Filtern Sie nach Herkunft, oder öffnen Sie **Erledigt** für das, was Sie schon
angenommen oder abgelehnt haben, und holen Sie Abgelehntes zurück. **Was sie
gefunden haben** auf der Karte Beobachtungen unter Routinen öffnet ihn auf
Beobachtungen eingegrenzt. Kürzere Zeilen stehen oben auf Ihrem Dashboard als
**Briefing**, und der leere Chat mit dem Start-Agent zeigt den ersten davon als
Karte, mit einem Link zum Rest.

Was eine Beobachtung findet und nicht sofort gemeldet werden muss, wartet auf
Ihren Morgen: zu der Stunde, die die Proaktivität der Organisation hält, nennen
eine Benachrichtigung und eine Direktnachricht von jedem ihrer Slack-, Teams-
und Mattermost-Bots, der Sie kennt, was neu ist. Jeder Fund steht nur in einem
Briefing.

Der Organisationswechsler steht unter dem Logo oben in der Seitenleiste und zeigt
den Namen und Avatar der aktiven Organisation. Öffnen Sie ihn, um die
Organisation zu wechseln, Organisationen zu verwalten oder eine neue anzulegen.
In der eingeklappten Seitenleiste bleibt der Avatar als Wechsler erhalten; das
Menü auf dem Smartphone bietet dasselbe Bedienelement. Die Kontoeinstellungen
bleiben im Kontomenü unten.

Die Suche steht oberhalb der Navigationsziele; am Computer ist ihr Tastenkürzel
sichtbar. Benachrichtigungen und Kontomenü bleiben unterhalb der scrollbaren Liste.
Auf Touchgeräten haben gemeinsame Schaltflächen, Felder, Tabs und Menüeinträge
größere Berührungsflächen. Dialoge nutzen die sichtbare Höhe oberhalb der
Bildschirmtastatur. Seitenpanels halten den Tastaturfokus im Panel und geben ihn
beim Schließen an den Auslöser zurück. Im Suchfeld einer Liste löscht Escape
zuerst die Suche; ein weiterer Druck schließt den Dialog.

## Die Glocke { #the-bell }

Am unteren Ende der Seitenleiste: eine laufende Zählung dessen, was Sie
noch nicht gelesen haben, und ein Klick öffnet die Liste selbst. Anders als
das Widget oben holt das Öffnen die Seite, auf der Sie gerade stehen, keine
Fünf-Karten-Vorschau - **Load more** blättert immer weiter zurück durch die
Organisation, in der Sie gerade sind, plus alles, was an das gesamte
Deployment adressiert ist, bis es erreicht, was aus dem Aufbewahrungsfenster
gefallen ist.

Jede Zeile beginnt mit dem, worum es geht: dem Gesicht des Agents mit einem
Abzeichen dafür, wie sein Run lief, oder einem Symbol für die Art des
Ereignisses - grün für einen beendeten Run oder einen wieder erreichbaren
MCP-Server, rot für einen Fehlschlag oder ein aufgebrauchtes Budget, bernsteinfarben
für eine Freigabe oder eine Budgetwarnung.

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
_aktuellen_ Rechte, und wer eine Woche lang herabgestuft und dann wieder
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

Was eine geleerte Zeile _nicht_ tut, ist wiederkommen. Die Benachrichtigung
wird behalten und nur nicht mehr gelistet, statt gelöscht zu werden, und genau
das macht es wahr: der Posteingang erkennt eine Wiederholung an dem Sachverhalt,
den sie beschreibt, eine gelöschte Zeile wäre also eine, die die nächste
Budgetprüfung oder der nächste Versuch erneut schriebe. Einen Alarm zu
verwerfen, um den Sie sich gekümmert haben, ist damit endgültig - für dieses
Vorkommnis; ein _neuer_, über einen neuen Sachverhalt, kommt weiterhin an.
Zeilen fallen auch von selbst heraus: neunzig Tage nach dem Schreiben, wenn sie
gelesen wurden, und ein Jahr danach unabhängig davon.

Was hier landet und was sich abschalten lässt, zu erklären, ist Sache von
[Governance](governance.md#alerts) — diese Seite ist nur die beiden Stellen,
an denen Sie es lesen: die Glocke für das, was gerade passiert ist, die
Dashboard-Karte für eine Handvoll der neuesten, beim nächsten Öffnen der
Seite.

## Der Assistent { #the-assistant }

Auf dem Smartphone sitzt der **Architekt** oben neben den Benachrichtigungen,
auf dem Desktop unten rechts: ein Agent, den jede
Organisation bekommt, ohne etwas zu installieren, gemeinsam für alle, die Agents
ausführen dürfen (`agents:run`). Er ist an
[den MCP-Server dieser Plattform](mcp.md#agenticos-as-an-mcp-server) gebunden.
Fragen Sie ihn, welche Agents Erstattungsfragen beantworten, warum der Run von
letzter Nacht fehlschlug oder was in einer Wissensbasis steht.

Sagen Sie ihm, was ein Agent tun soll, und er baut ihn mit Ihnen, eine Frage nach
der anderen, jede mit vorgeschlagenen Antworten: Er wählt die Capabilities, die
Wissensbasis und das Modell, sagt in einem Satz, warum, entwirft den Agent,
probiert ihn als unveröffentlichten Entwurf an Ihren eigenen Fragen aus, korrigiert,
was falsch war, und veröffentlicht ihn, wenn Sie zustimmen. Eine Routine richtet er
genauso ein.

Bevor sich etwas ändert, zeigt er Ihnen, was Sie freigeben: einen Agent-Entwurf
als den Entwurf selbst - wo er angelegt wird, sein Name, was er tun darf und
seine Anweisungen - und alles andere als den genauen Aufruf. Er handelt mit
Ihren Berechtigungen, findet und tut also, was Sie könnten, und nicht mehr.
Seine Kosten zählen wie die jedes Agents.

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
Ihnen, was Ihre Agents kosten, und löscht nur einen versehentlich angelegten
Agent-Entwurf und eine Routine, deren Entfernen Sie verlangen. Neben Freigaben und einer leeren
Organisation meldet sich seine Sprechblase, wenn ein Run von Ihnen gerade
fehlgeschlagen ist und wenn ein Formular seit einer Minute unfertig offen ist.

Vor dem Verbinden eines Modells öffnet der Architect denselben Chat mit einer grafischen Einrichtungskarte, einer kurzen Checkliste und dem Link zu den Modelleinstellungen. Eine Nachricht im Widget oder im Chat mit dem Architect-Entwurf erhält eine gespeicherte Einrichtungsantwort samt Karte, ohne Modellaufruf und ohne KI-Run. Die Antwort verwendet den Namen des gewählten Agents. Konfigurationsaktionen beachten Berechtigungen; andere Mitglieder erhalten Hinweise zum Administrator. Nach der Veröffentlichung bleibt das Widget für die normale Unterhaltung geöffnet.

Der Architect ist ein Agent wie jeder andere, also werden Name, Modell, Wissen
und der Rest seiner Spec im Agent Builder bearbeitet - von jemandem, der die
Einstellungen der Organisation ändern darf, weil ihn alle in der Organisation
ausführen. Auf der Seite der Organisation schaltet eine Karte ihn für alle ab und
legt seine Begrüßung fest. **Einstellungen → Assistent** enthält nur noch Ihre
eigenen Tipps.

## Mitgelieferte Agenten { #shipped-agent-defaults }

AgenticOS, Architect und die Vorgaben für neue Agenten enthalten keine Werkzeuge für vorläufige Arbeitspläne. Agenten melden ihren Fortschritt im Chat und verwenden verwaltete Tasks über AgenticOS MCP für dauerhaft zu speichernde Arbeit.

Beide Startagenten und neue Konsolenagenten enthalten Watch a command, Background topics, Work while tools run, begrenzte Suche in früheren Gesprächen und lokale BM25-Werkzeugsuche mit fünf Ergebnissen. Sie erhalten research-, explore- und review-Spezialisten, dynamische Spezialisten und automatische sync/async-Delegation. Monitore benötigen eine dauerhafte Shell und enden mit dem Turn; Hintergrundthemen bleiben danach bestehen. Frühere Gespräche werden nur bei Bedarf durchsucht: zuerst Ausschnitte, dann begrenzte Transkriptfenster. Gruppen und unbeaufsichtigte Läufe können keine private Historie durchsuchen.

Nur der mitgelieferte AgenticOS enthält Computer use, Webbrowser und Coding agent. Desktop-Steuerung und Programmierung verwenden standardmäßig den genehmigten Desktop; Sandbox-Programmierung benötigt konfigurierte Zugangsdaten. Auch der mitgelieferte Browser verwendet den gekoppelten Desktop; alternativ kann ein Administrator einen Browser-Endpunkt des Deployments konfigurieren. Neue Agenten erben die gemeinsame Einrichtung ohne diese drei Werkzeuge. AgenticOS beantwortet Plattformfragen direkt mit seinem Leitfaden und AgenticOS MCP. Die Vorgaben pinnen Architect nicht mehr; die Aktualisierung entfernt den unveränderten mitgelieferten Pin und behält eigene Delegierte.

Jede Organisation erhält **AgenticOS** für allgemeine Aufgaben und **Architect**
für die Einrichtung der Plattform. Beide haben Gedächtnis. Neue Agenten in der
Konsole beginnen mit der aktuellen AgenticOS-Vorlage; anschließend lassen sich
Prompt und Werkzeuge anpassen. AgenticOS kann den veröffentlichten Architect
über AgenticOS MCP um Hilfe bitten. Berechtigungen, Budgets und Genehmigungen
gelten weiterhin.

Beim Öffnen der Konsole werden mitgelieferte Einstellungen geprüft. Unveränderte
Anweisungen, Capabilities, MCP-Bindungen, Skills und Gesprächseinstiege erhalten
Updates. Ein anderes Modell oder Budget blockiert diese Updates nicht; die
gewählten Werte bleiben erhalten. Eigene Prompts und Werkzeugeinstellungen
werden geschützt. Unveröffentlichte Änderungen bleiben Entwürfe und werden beim
Update des laufenden Agenten nicht mitveröffentlicht. Archivierte Agenten bleiben
archiviert. Ältere Installationen werden anhand ihrer Herkunft oder bekannter
historischer Vorgaben erkannt, nicht allein am Namen.

Der Chat zeigt bestätigte Gedächtnisspeicherungen und Korrekturen mit einem Link
zu **Your memory**. Ablehnungen und strittige Angaben gelten nicht als erfolgreiche
Speicherung. Vorschläge für Routinen und Beobachtungen erscheinen als Karten zur
Prüfung vor der Aktivierung. Ausführungs- und Zustelloptionen stehen unter
**Erweiterte Optionen**; ihre bisherigen Standardwerte bleiben erhalten.

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

Ebenso Datasets: ein hinzugefügter oder entfernter Fall, eine Änderung an der
Bewertung, ein Score oder eine Review-Entscheidung und Entwürfe, die der
[Fallgenerator](datasets.md#generating-cases) im Hintergrund fertigstellt - sie
erscheinen ohne Neuladen im Tab Generated eines offenen Datasets.

Wissenslücken werden ebenso gemeldet: Ein Thema, das in einem Tab verworfen oder
entworfen wurde, und die Fragen, die ein Gruppierungslauf alle 15 Minuten
einordnet, erscheinen auf einem offenen Tab Wissenslücken ohne Neuladen.

Die Ausnahme ist der Builder, weil er Ihren Entwurf beim Tippen speichert. Ändert
sich der Agent, den Sie bearbeiten, anderswo, hört er auf zu speichern und holt
die neue Version. Ohne ungespeicherte Änderungen übernimmt er sie einfach; mit
ungespeicherten Änderungen sagt er, wer ihn worüber geändert hat, und wartet auf
Ihre Wahl: **Neu laden** (deren Version) oder **Meine Änderungen behalten** (Ihre,
über deren gespeichert).

Sie erfahren nur, was Sie lesen dürfen: Eine Änderung an einem Agent, einem
Skill, einer Wissensbasis, einer Kontextdatei, einer Seite, einem Schlüssel,
einem MCP-Server oder einem Dataset, die Sie nicht sehen, erreicht Ihre Konsole nie, und eine
Löschung erreicht nur Rollen, die jede Zeile dieser Art sehen. Runs erreichen die
Rollen, die den Run-Verlauf lesen oder über Freigaben entscheiden, Wissenslücken
die Rollen, die jeden Run lesen, Kanal-Bots die
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

Unterhaltungen, die andere mit Ihnen geteilt haben, stehen unter **Mit Ihnen
geteilt**, unter Ihren Favoriten. Umbenennen, Teilen, Archivieren und Löschen
liegen bei ihren Besitzern. Im Menü können Sie Favoriten setzen oder entfernen und **Aus meinen Chats entfernen** wählen,
das Ihren Zugriff beendet und die Unterhaltung für alle anderen unverändert
lässt. Eine zum Lesen mit Ihnen geteilte Unterhaltung hat kein Eingabefeld.
Teilt jemand eine Unterhaltung mit Ihnen, erhalten Sie eine Benachrichtigung,
die sie öffnet. Ungelesene und favorisierte geteilte Unterhaltungen stehen in ihren üblichen Bereichen.

Unter **Teilen** hat jede Person, mit der die Unterhaltung geteilt ist, neben
ihrem Namen eine Auswahl **Ansehen** oder **Bearbeiten**, um zu ändern, was sie
darf, ohne den Zugriff zu entziehen und neu zu teilen. Ein Freigabelink bleibt
schreibgeschützt.

Direkte Freigaben sind pro Minute auf 100 Versuche je Organisation, 20 je Absender, 20 je Empfänger und fünf je Absender–Empfänger-Paar innerhalb der Organisation begrenzt. Neue Unterhaltungen setzen diese Grenzen nicht zurück. Eine Ablehnung liefert `429` mit einer Wartezeit und erstellt weder Freigabe noch Benachrichtigung. Freigabelisten und tatsächlicher Zugriff werden bei aktiver Seite alle 15 Sekunden aktualisiert.

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
hineinklicken. Darüber sind die Karten die eigenen **ersten Nachrichten** des
Agents, im Builder unter seinen Instruktionen gesetzt; ein Agent ohne sie bietet
die vier des Chats an, darunter eine, die fragt, was er kann, und eine, die eine
Routine einrichtet.

Unterhaltungslisten behalten den Hauptagenten bei und nennen zusätzlich Claude Code oder Codex, wenn gespeicherte Aufgabenberichte ihre Mitarbeit belegen. Sidebar, Projektchats, Dashboard und Quick-Ask-Verlauf verwenden dieselben Symbole und Beschriftungen. Jeder Coding-Harness erscheint einmal, bleibt nach dem Aktualisieren sichtbar und ist unabhängig von aktuellen Chat-Einstellungen. Die Auswahl ohne Ausführung fügt ihn nicht zum Verlauf hinzu.

Das Files-Panel gruppiert Dateien nach Ordnern und unterscheidet gleiche Namen in verschiedenen Verzeichnissen. HTML-Vorschauen laden lokale Stylesheets und ihre verschachtelten Ressourcen über denselben Dateizugriff wie die Seite. Vorschau und Quelltext bleiben getrennt; Skripte sind deaktiviert. Ist ein Stylesheet nicht lesbar, nennt die Vorschau die betroffene Datei.

Unter einer Antwort stehen Links zu den in diesem Turn geänderten Dateien. Programmieraufgaben verwenden ihren gespeicherten Änderungssatz einschließlich Shell-Änderungen; ohne Änderungssatz nutzen sie den Harness-Bericht. Das Aufgabenpanel bietet **Diese Aufgabe rückgängig machen** an, wenn du den ursprünglichen Workspace bearbeiten darfst und der Snapshot vollständig ist. Die Links öffnen aktuelle Workspace-Dateien, keine versionierte Kopie.

Die Rücknahme läuft als dauerhafter Job in einem isolierten Unterhaltungs-Workspace. Snapshots geteilter Bereiche bleiben schreibgeschützt. Das Panel zeigt den Fortschritt; ein unbekanntes Ergebnis reserviert den Workspace, bis Erneut versuchen seine Dateien prüft.

Snapshots für Rücknahmen sind auf 2 MiB pro Datei und insgesamt 16 MiB für die Daten vor und nach der Änderung begrenzt; größere Änderungen bleiben ohne Rücknahme einsehbar. Die Prüfung begrenzt auch das Lesen älterer Snapshots. Pro Minute sind sechs Anfragen pro Person und zwanzig pro Organisation zulässig, mit einer lokalen Grenze bei Redis-Ausfällen. Jede Organisation führt höchstens einen Rücknahme-Job gleichzeitig aus.

Während der Arbeit erscheinen Fortschrittsmeldungen und die jeweils folgenden Tool-Aufrufe in ihrer Eingangsreihenfolge in einem aufgeklappten Verlauf. Erst nach Abschluss wird der Verlauf unter einem „Worked for…“- oder „Thought for…“-Schalter eingeklappt; darunter bleibt nur die finale Antwort. Aufklappen zeigt dieselben Nachrichten und Tool-Gruppen wieder chronologisch. Begründungen bleiben separat aufklappbar; ihre Überschriften erzeugen keine Prozessphasen. Fragen und Freigaben behalten ihren Wartestatus bis zur Entscheidung, auch bei delegierten Anfragen. Aktive Freigabekarten und visuelle Ergebnisse bleiben außerhalb des abgeschlossenen Verlaufs sichtbar.

Aufeinanderfolgende Tool-Aufrufe zwischen Nachrichten bilden eine eingeklappte Gruppe; öffnen Sie diese für einzelne Aufrufe.

Chat-Freigaben bleiben eine kompakte Karte neben dem Eingabefeld: Operation, Symbol und Aufgaben- oder Objekttitel, weitere Argumente unter Details. Approve und Reject stehen daneben, auf schmalen Bildschirmen darunter. Abgeschlossene Aktivität erhält ein dezentes Abschlusszeichen, wartende Schritte einen eigenen Status. Laufende Schritte behalten ihr Operationssymbol statt einer animierten Kugel pro Aufruf.

Beim erneuten Öffnen eines Chats werden auch Freigaben und Fragen delegierter Werkzeuge wiederhergestellt, die in der Zeitleiste des übergeordneten Agenten fehlen. Während seiner genehmigten HTTP-Fortsetzung wird ein pausierter Subagent als arbeitend angezeigt. Ein abgeschlossener veröffentlichter Unteragent behält sein eigenes Ergebnis, wenn der übergeordnete Agent auf eine weitere Entscheidung wartet.

Eingehender Text bleibt lesbar, während das Markdown-Modul lädt. Das Eingabefeld hat eine undurchsichtige Fläche und einen dezenten Fokuszustand, ohne bewegten Rahmen oder Hintergrundunschärfe.

Der laufende Verlauf folgt dem Seitenfluss; der aufgeklappte abgeschlossene Verlauf hat eine begrenzte Höhe und einen eigenen Scrollbereich. Aufeinanderfolgende Segmente desselben Agentenlaufs teilen Zusammenfassung und Startzeit, einschließlich Fortschrittsmeldungen zwischen Tools und Fortsetzungen nach Freigaben. Ein anderer Agent oder eine dazwischenliegende Nutzernachricht beginnt einen eigenen Turn. Abgeschlossene und verschachtelte Agentenaustausche bleiben verfügbar, einschließlich Coding-Agent-Berichten; öffnen Sie einen Austausch für Anweisungen, Antwort und eingeklappte Begründung.

Erfolgreiche MCP-Schreibvorgänge zeigen verlinkte Karten für Projekte, Tabellen, Aufgaben, Datensätze, Agenten, Workflows, Skills und Context. Fehler erzeugen keine Erfolgskarten. Gesendete Nachrichten stehen nahe am oberen Rand mit Platz für die Antwort; manuelles Scrollen behält Ihre Position bei. Person- und Agent-Listen scrollen im Datensatzdialog. Fragen funktionieren auch nach genehmigten HTTP-Fortsetzungen.

Auch Ergebnisbenachrichtigungen stehen neben dem Eingabefeld. Solange ein Entscheidungspanel sichtbar ist oder der Chat arbeitet, werden Freigabebenachrichtigungen auch älterer Läufe ausgeblendet. Andernfalls führen sie zur Freigabewarteschlange. Sie bieten niemals Gesehen, Erledigt oder Nicht mehr fragen: Nur die eigentliche Genehmigung oder Ablehnung entscheidet über die Operation. Inbox und Glocke behalten ihre Benachrichtigungen.

**Unter einer Antwort.** Ein Agent mit
[Nächsten Schritten](reference/capabilities.md#follow-ups) bietet unter seiner
neuesten Antwort bis zu drei nächste Schritte als Schaltflächen an, und ein Klick
sendet einen. Eine Zeile sagt, was er sich über Sie notiert oder vergessen hat,
mit **Verwalten (Manage)** zu [den Notizen selbst](reference/capabilities.md#memory-files)

- bitten Sie ihn, etwas zu vergessen, und er tut es. Braucht eine Anfrage eine
  Capability, die dem Agent fehlt, bietet eine Karte an, sie einzuschalten oder den
  Besitzer des Agents darum zu bitten ([wie](reference/capabilities.md)).

**Eine Anfrage behalten, die funktioniert hat.** Fahren Sie über Ihre eigene
Nachricht: Der Kalender macht daraus eine Routine - derselbe Prompt, standardmäßig
wöchentlich, auf dem Agent, der geantwortet hat -, und der Roboter bittet den
Architect, einen Agent zu bauen, der das erledigt. Fahren Sie über die Antwort,
und das Lesezeichen bittet den Architect, einen [Skill](skills.md) daraus zu
machen, wie es erledigt wurde, damit jeder Agent es beim nächsten Mal genauso
macht; er bekommt Ihre Anfrage und die Antwort, und angeboten wird es, wer Skills
schreiben darf.

**Links, die zeigen.** Ein Konsolenlink, den ein Agent in seine Antwort schreibt -
„hier ist der Button, der Ihr Gmail verbindet“ - öffnet diese Seite, ohne die
Konsole neu zu laden, und ein `?highlight=` darin zeigt auf das Bedienelement, das
er nennt, wie die Links des Architect.

**Der AgenticOS-Agent lernt Sie kennen.** Solange Ihr Konto nichts über Ihre
Rolle oder Ihre Arbeit sagt, beginnt eine Begrüßung ein kurzes Gespräch: was Sie
tun, was Ihre Woche füllt, mit welchen Werkzeugen Sie arbeiten - eine Frage nach
der anderen, jede mit Antworten zur Auswahl. Was Sie sagen, wird in Ihrem Profil
gespeichert, sodass es von da an jeder Agent weiß, und das Gespräch endet mit bis
zu drei Karten zum Einrichten - einer Routine, einem Dienst zum Verbinden, einem
eigenen Agent - jede mit einem Klick. Überspringen Sie eine Frage oder bitten Sie
um etwas Echtes, und er erledigt stattdessen die Arbeit.

**Was über Nacht auffiel.** Wo Ihre Organisation es eingeschaltet hat, liest die
Plattform einmal am Tag, früh an Ihrem Morgen, in einem Hintergrundjob Ihre
letzten Unterhaltungen: Eine Anfrage, die
Sie immer wiederholen, wird eine vorgeschlagene Routine, was ein Agent über Ihre
Rolle erfahren hat, ein vorgeschlagenes Profil, und Ihr leerer AgenticOS-Chat
bekommt erste Nachrichten, die für Ihre Arbeit geschrieben sind. Vorschläge
warten als Karten in diesem leeren Chat, auf Ihrem Dashboard und in der Glocke,
und **Einstellungen → Assistent** listet sie alle - dort holen Sie einen
verworfenen zurück oder nehmen sich aus; nehmen Sie einen an,
wird er eingerichtet, verwerfen Sie ihn, wird derselbe Vorschlag nie wieder
gemacht. Nichts läuft, wenn nichts Neues passiert ist, und was das kosten darf,
ist [pro Person begrenzt](governance.md#proactive-work). Ein Chat-Link mit
`?agent=<slug>` öffnet den Chat auf diesem Agent.

**Arbeitszeiten** unter **Settings → Profile** sagen Agents, wann Sie arbeiten,
sodass eine Routine, die sie vorschlagen, in Ihren Tag fällt. Nichts wartet auf
sie: Sie sind Wissen für den Agent, kein Zeitplan.

Beim erneuten Öffnen eines Gesprächs sehen Sie die neuesten Nachrichten. Mit **Ältere Nachrichten laden** über dem Verlauf lesen Sie frühere Beiträge. Laufende Antworten und ungespeicherte Ergebnisse bleiben sichtbar, während der gespeicherte Verlauf aktualisiert wird.

Wenn eine Antwort des Assistenten nicht gespeichert werden kann, fordert der Chat Sie auf, benötigten Text vor dem Verlassen des Gesprächs zu kopieren. Das gilt auch für Teilantworten aus unterbrochenen Ausführungen. Der live übertragene Text bleibt sichtbar, kann aber beim erneuten Öffnen des Gesprächs fehlen.

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
  Kommen Sie zurück, solange er noch antwortet - in die Unterhaltung, aus einem
  anderen Tab, nach dem Neuladen -, nimmt der Chat die Antwort dort auf, wo sie
  steht, mit allem, was der Agent bis dahin getan hat, und zeichnet sie weiter, wie
  sie ankommt.

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

**Entwürfe.** Ein Agent mit [Entwürfen](reference/capabilities.md#drafts) zeigt Text,
den Sie anderswo versenden oder einfügen - eine E-Mail, eine Antwort, einen Beitrag -
als Karte in seiner Antwort. Jeder Teil hat ein eigenes Kopiersymbol, das reinen Text
kopiert; mehrere Varianten eines Entwurfs sind Tabs in derselben Karte. Das eigene
**Kopieren** einer Nachricht enthält auch ihre Entwürfe.

**Einem Durchlauf zusehen.** Der [Webbrowser](reference/capabilities.md#browser-automation)
öffnet sich automatisch in einem Panel in voller Höhe neben dem Gespräch.
Auf schmalen Bildschirmen nutzt er das Vollbild. Nach dem Schließen bleibt
ein kompakter Link im Gespräch, um das Panel erneut zu öffnen. Karten besuchter
Seiten zeigen das Website-Symbol, die Domain und den Seitentitel, auch nach dem
erneuten Öffnen des Gesprächs. Jede Antwort behält eine Karte pro Browser-Tab;
Klicks, erneutes Lesen und Zurückgehen aktualisieren diese Karte.
Die Tableiste im Panel wechselt zwischen den Seiten. Nach dem Lauf bleibt das letzte Bild. **Sitzung fortsetzen** bittet den
Agent, den privaten Sitzungsstand wiederherzustellen, bis zu einer Stunde lang.
Remote-Seiten schließen nach jedem Lauf. Fortsetzen lädt URLs, Cookies und Local
Storage neu, aber keine ungespeicherten Formulare oder JavaScript-Zustände. Der Agent
liest die Elementnummern erneut.

**Einen Durchlauf übernehmen.** Während ein Durchlauf läuft, pausiert **Übernehmen** in
der Symbolleiste des Browsers den Agent nach seinem laufenden Schritt und gibt Ihnen die
Seite, im selben Fenster: klicken, tippen, scrollen, einfügen. **Zurückgeben**, und der
Agent macht dort weiter, wo Sie aufgehört haben. Kommt der Agent allein nicht über eine
Seite hinweg - eine Anmeldung, ein Captcha -, sagt der Browser _Der Agent
braucht Sie_ und wofür. Wer Runs sehen, aber den Agent nicht bearbeiten darf, kann
zusehen, nicht steuern. Dasselbe Fenster öffnet sich über den Link eines Kanals auf
einer eigenen Seite. Siehe [Webbrowser](reference/capabilities.md#browser-automation).

**Auf die Seite zeigen.** Mit der Sprechblase in der Werkzeugleiste des Browsers
klickst du auf eine Stelle der Seite und schreibst eine Notiz dazu - _dieser Knopf,
nicht der andere_. **Add to message** legt die Seite als Bild mit markierter Stelle in
deine Nachricht, mit deiner Notiz und der Adresse der Seite, zum Senden oder
Weiterschreiben. Das geht auch bei einem beendeten Browse, auf seinem letzten Bild.

**Angemeldet bleiben.** Wenn der Browse für dich handelt - dein eigener Chat, deine
Direktnachricht, dein eigener Zeitplan -, bietet **Zurückgeben** _Anmeldung bei …
behalten_ für die Seite an, auf der du bist. Hake es nach der Anmeldung an, und
spätere Browses für dich starten dort angemeldet: Cookies und Speicher der Seite
liegen versiegelt im Vault, nur für dich, werden nie angezeigt und nie für einen
Widget-Besucher, einen geteilten Raum, einen API-Schlüssel oder einen Ereignis-Trigger
genutzt. **Einstellungen → Anmeldungen** listet die behaltenen Seiten, und
**Vergessen** lässt den nächsten Browse abgemeldet starten. **Bei einer Website
anmelden** öffnet dort einen Browser auf einer beliebigen Seite, nur für dich, bevor ein
Agent ihn braucht: anmelden, mit angehaktem Feld zurückgeben, und die Anmeldung wird
genauso behalten. Dafür braucht das Deployment seinen Anmelde-Browser
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

**Einen wartenden Lauf stoppen.** Im Eingabefeld bleibt **Stop** verfügbar, während der
Agent auf eine Antwort, eine Genehmigung oder eine Kontoverbindung wartet. Das gilt auch
nach dem Neuladen einer ausstehenden Frage oder Genehmigung. Das Stoppen schließt
ausstehende Aufrufe, ohne das Modell fortzusetzen, und erhält die bereits erfassten
Kosten. Sie können eigene Läufe stoppen; Genehmigungsberechtigte können außerdem Läufe
stoppen, die auf eine Genehmigung warten. Verhindert ein vorübergehender Fehler das
Stoppen, bleibt die Karte für einen erneuten Versuch verfügbar.

### Diktieren { #dictation }

Das Mikrofon steht bei jedem Agent neben Senden und im Menü `+`. Es macht aus
Sprache Text im Feld und sendet ihn nie: Was Sie gesagt haben, landet dort, wo
der Cursor stand, als Sie das Mikrofon gedrückt haben, bereit zum Bearbeiten, und
geht nirgendwohin, bis Sie Senden drücken. Wie transkribiert wird, entscheidet
der Agent, auf dem Reiter Diktieren [seiner Karte Stimme (Voice)](#an-agents-voice-card):

- **Mit einem Anbieter transkribieren** an — der Browser nimmt auf, und dieses
  Deployment schickt die Aufnahme an den Anbieter des Agents oder den Standard
  der Organisation. Das funktioniert in jedem Browser, der aufnehmen kann.
  Endpunkt, Limits und was festgehalten wird, stehen unter
  [Diktieren im Chat](ml-services.md#dictation-in-chat).
- Aus, oder ohne Schlüssel, mit dem gesendet werden kann — die eigene
  Spracherkennung des Browsers, sodass der Ton an den Browserhersteller geht
  (Google, Apple) und nichts kostet. Firefox hat keine: Sein Mikrofon sagt das,
  wenn man es drückt. Während er zuhört, sagt ein Hinweis über dem Eingabefeld,
  dass Diktieren für den Agent aus ist, und verlinkt für alle, die den Agent
  bearbeiten dürfen, seinen Reiter Diktieren.

Mit einem Anbieter schwebt nach dem Drücken des Mikrofons eine
**Aufnahme-Pille** über dem Eingabefeld, das sich nicht ändert: Abbrechen, der
Pegel, ein Timer und Stopp. **Enter** stoppt und transkribiert, **Escape** bricht
ab, und nichts, was während einer laufenden oder transkribierten Aufnahme
getippt oder gedrückt wird, wird gesendet. Die Aufnahme stoppt von selbst beim
längsten Diktat der Organisation und wird transkribiert, und ein mittendrin
abgestecktes Mikrofon beendet sie genauso, statt sie zu verwerfen. Dauert das
Hochladen länger als eine Sekunde, zeigt die Pille, wie viel schon oben ist;
danach sagt sie **Wird transkribiert**, bis der Text da ist. Die Erkennung im
Browser hat eine eigene Pille, mit **Diktieren beenden**.

Alles, was das Diktieren zu sagen hat, erscheint in einem Streifen über dem
Eingabefeld, neben der Pille: die Berechtigungsabfrage, ein blockiertes oder
fehlendes Mikrofon, die letzten 30 Sekunden, fünf Sekunden ohne Ton, eine
Aufnahme unter einer Sekunde (nicht gesendet), eine am Limit gestoppte Aufnahme
und jeder Fehler. Wie viele Wörter eingefügt wurden, wird einem Screenreader
angesagt statt angezeigt, denn die Wörter stehen im Feld. Eine Aufnahme, deren
Transkription fehlschlug, bleibt, bis Sie **Erneut versuchen** oder
**Verwerfen** drücken.

Das Leuchten um das Feld einer Hosted Page, während Sie sprechen, folgt
**Diktieranimation (Voice glow)** unter **Einstellungen → Profil → Darstellung
(Settings → Profile → Appearance)**, neben Design und **Bewegung (Motion)**:
**Kräftig (Vivid)**, **Dezent (Subtle)** (der Standard) oder **Aus (Off)**. Es
wird pro Browser gespeichert. **Bewegung** bestimmt, wie viel Bewegung die ganze
Konsole zeigt: **System** (der Standard) folgt der Einstellung für reduzierte
Bewegung im Betriebssystem, **Reduziert (Reduce)** reduziert die Bewegung auch
ohne sie, und **Voll (Full)** behält sie, was auch immer das Betriebssystem
sagt. Solange die Bewegung
reduziert ist, gibt es gar kein Leuchten, der Streifen erscheint ohne Gleiten,
und der Pegel ist eine fünfstufige Anzeige.

**Workflow-Schritte** in derselben Karte wählt, wie die Workflow-Canvas einen Schritt
zeichnet: **Farbig (In colour)** (der Standard) zeichnet jeden Schritt in seiner
Familie, **Schlicht (Simple)** lässt die Kacheln neutral und die Minikarte grau. Die
Einstellung wird pro Browser gespeichert; denselben Schalter hat die Werkzeugleiste der
Canvas. Siehe [Wie ein Schritt gezeichnet wird](workflows.md#how-a-step-is-drawn).

### Die Karte Stimme (Voice) { #the-voice-card }

Auf der Seite **Mitglieder (Members)** der Organisation, für jemanden mit
`org:settings`. Sie hält den Speech-to-Text-**Standard**, den Agents und
Channel-Bots erben, und wie lange ein Diktat dauern darf; ob ein Agent mit einem
Anbieter diktiert oder Anrufe annimmt, wird auf seiner eigenen Karte Stimme
(Voice) eingeschaltet. **Maximale Aufnahmelänge** reicht von 10 Sekunden bis 10
Minuten. **Standardanbieter** ist Anbieter und Modell aus dem
Speech-to-Text-Katalog und eine Sprache (automatisch erkennen oder eine feste
Sprache, was genauer ist). Er ist auch das, wohin
[Channel-Bots](channels.md#what-every-channel-shares), die erben, ihre
Sprachnachrichten schicken; **Keiner (None)** löscht ihn.

**Schlüssel**, neben dem Anbieter, ist der Vault-Schlüssel, mit dem der Standard
gesendet wird. Aufgeführt sind die API-Schlüssel, deren Zweck dieser Anbieter
ist und die die ganze Organisation sehen kann - die Plattform gibt diesen
Schlüssel für das Diktat jedes Mitglieds und jeden erbenden Bot aus, also wird
der private Schlüssel eines Mitglieds nicht angeboten und abgelehnt, wenn er
gesendet wird. Mit genau einem solchen Schlüssel wird er für Sie gewählt und in
jedem Fall mit Namen gespeichert; nichts wählt zur Laufzeit einen Schlüssel. Ein
Anbieter ohne Schlüssel ist als **kein Schlüssel für diesen Anbieter**
markiert, und die Auswahl verlinkt in den Vault, um einen hinzuzufügen. Kann der
Standard nicht laufen - das Modell wurde aus dem Katalog zurückgezogen, oder der
Schlüssel wurde gelöscht oder privat gemacht -, sagt die Karte das und bittet,
**einen Schlüssel zu wählen**, wo genau das fehlt.

Für jemanden, der auch `runs:view` hält, beginnt die Karte mit einer Zeile dazu,
was die Organisation in den letzten 30 Tagen transkribiert hat — „42 Min · 118
Aufnahmen (30 ohne Länge)“ — über Diktat, Sprachnachrichten der Channels und die
API. **Aufschlüsselung anzeigen** listet es nach Agent und nach Channel-Bot. Die
Minuten zählen nur Aufnahmen, deren Länge gemeldet wurde, also sagt die Zeile,
wie viele es nicht wurden; sie ist verborgen, solange nichts transkribiert
wurde. Die Zahlen kommen aus
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### Die Karte Stimme (Voice) eines Agents { #an-agents-voice-card }

Der Reiter **Build** eines Agents hat nach den Modelleinstellungen eine Karte
**Stimme (Voice)** mit zwei Reitern: **Sprachanrufe** und **Diktieren**.

**Diktieren** hält **Mit einem Anbieter transkribieren**. An, schickt das
Mikrofon im Chat die Aufnahme an einen Anbieter: **Eigener dieses Agents** (der
Standard) wählt ein Paar aus dem Katalog und den Schlüssel, mit dem es gesendet
wird - einen API-Schlüssel für diesen Anbieter, den Sie sehen dürfen, weil das
Veröffentlichen ihn allen leiht, die den Agent ausführen dürfen -, und bis Sie
einen wählen, wird der Standard der Organisation verwendet und genannt. **Der
Organisation** behält Anbieter, Modell und Schlüssel der Organisation. Aus, oder
ohne Schlüssel, mit dem gesendet werden kann, transkribiert stattdessen der
Browser, was nichts kostet.

Die Sprache wird eigens gewählt: die der Organisation erben oder eine festlegen

- so kann ein polnischer Agent Anbieter und Schlüssel der Organisation behalten.
  Die Karte ist Teil der Spec, wird mit dem Entwurf gespeichert und ist live,
  sobald der Agent veröffentlicht ist, und sie gilt für das
  [Diktieren](#dictation) an diesen Agent und für Sprachnachrichten, die seine
  Channel-Bots erben. [Die Reihenfolge](ml-services.md#which-engine-a-recording-reaches)
  hat den Rest.

### Sprachanrufe { #voice-calls }

Ein [Sprachanruf](voice.md) ist ein gesprochenes Gespräch mit einem
veröffentlichten Agent: Sie sprechen, er antwortet laut, und Sie können ihn
unterbrechen. Anrufe werden im Agent eingeschaltet; die Organisation hat keine
Anrufeinstellungen.

- **Die Karte Stimme (Voice) des Agents**, auf ihrem Reiter **Sprachanrufe**:
  Anbieter und Modell des Anrufs (für Azure der Deployment-Name und sein
  Basismodell), der Schlüssel, die Stimme mit einer **Abspielen**-Taste, um sie
  zu hören, die gesprochene Sprache (oder **Dem Anrufer folgen**), der
  **Längste Anruf** (10 Minuten, wenn nicht gesetzt, höchstens 50) und
  **Anweisungen für Anrufe**. Die Karte listet, was der Agent in Anrufen
  [an sein Textmodell übergibt](voice.md#handing-work-off), sagt, dass
  Guardrails gesprochene Wörter nicht filtern können, bevor sie zu hören sind,
  und dass Anrufe als Text ohne gespeicherten Ton festgehalten werden. Sie gilt,
  sobald der Agent veröffentlicht ist.
- **Der Schalter Sprachanrufe eines Embeds**, in den Formularen für Widget und
  Hosted Page - siehe [Channels](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Bevor sie einen Anruf anbietet, fragt die Konsole, ob dieser Agent einen
annehmen kann (`GET /agents/{id}/voice`), damit niemand das Mikrofon freigibt,
nur um abgelehnt zu werden. Die Antwort nennt, was fehlt: keine Stimme am Agent
eingerichtet, das Modell nicht mehr angeboten, oder kein Schlüssel.

Die **Anruftaste** steht im Eingabefeld des Chats an der Stelle von Senden,
solange das Feld leer ist - ist etwas getippt, kommt Senden zurück -, bei jedem
Agent. Kann dieser Agent keinen Anruf annehmen, ist sie durchgestrichen, und
Hovern, Fokussieren oder Drücken sagt, warum. Wer den Agent bearbeiten darf,
bekommt **Im Agent Builder öffnen**, was seine Karte Stimme (Voice) auf dem
Reiter Anrufe öffnet; allen anderen wird gesagt, jemanden zu fragen, der das
darf.

Während eines Anrufs schwebt eine **Pille** über dem Eingabefeld, das bleibt, wie
es war, Entwurf und Anhänge eingeschlossen: was der Anruf gerade tut, seine
Zeit, eine Wellenform beider Stimmen, Push-to-Talk, Stummschalten und **Anruf
beenden**. Nur Anruf beenden beendet einen Anruf; eine andere Unterhaltung oder
einen neuen Chat zu öffnen, legt ihn auf. Gesprochen wird standardmäßig
freihändig; **Push-to-Talk** (die Taste oder die Leertaste halten) ist eine Wahl,
die Ihr Browser sich merkt. Bei reduzierter Bewegung ersetzt eine gestufte
Pegelanzeige die Wellenform.

Ein Anruf durchläuft Zustände, die die Pille benennt: Verbinden, Zuhören, Sie
sprechen, Denken, der Agent spricht, unterbrochen, arbeitet an einem Tool,
wartet auf Ihre Freigabe, eine Freigabe, die Sie nicht erteilen können, fast
keine Zeit mehr und beendet - von Ihnen, durch ein Limit, eine abgebrochene
Verbindung oder einen Fehler.

Der Anruf findet in der Unterhaltung statt: Jeder Turn wird als die Nachricht
gezeichnet, die er wird, und wächst Wort für Wort, während er gesprochen wird,
ein Screenreader hört jede Zeile, sobald sie endgültig ist, und die gespeicherte
Nachricht tritt an ihre Stelle, ohne dass sich etwas bewegt, sodass der Anruf
danach in Ihrem Verlauf steht und Sie weitertippen können. Während der Agent
nachdenkt oder ein Tool ausführt, sagt die Unterhaltung das dort, wo seine
Antwort erscheinen wird.

**Freigaben** werden im Anruf entschieden: Eine Karte in der Unterhaltung zeigt
das Tool, seine genauen Argumente und was Sie gesagt haben sollen, mit einem
60-Sekunden-Countdown. Nur ihre Tasten entscheiden; „ja" zu sagen, gibt nichts
frei. Ohne `approvals:decide` sagt die Karte, dass das Tool eine Freigabe
braucht, die Sie per Stimme nicht erteilen können, und bietet an, den Anruf zu
beenden und im Text weiterzumachen. **Fragen**, die der Agent stellt, erscheinen
als Fragekarte des Chats und werden auch vorgelesen: Tippen Sie eine Antwort an
oder sagen Sie sie einfach. Arbeit, die der Agent
[an sein Textmodell übergibt](voice.md#handing-work-off), zeigt jeden Schritt,
während er läuft, und die Schritte bleiben danach am Turn. **Limits** werden
gesprochen: Eine Minute vor dem Ende des längsten Anrufs werden Sie gewarnt, und
wenn die Zeit oder das Budget ausgeht, sagt der Agent einen Satz, und der Anruf
endet.

Ein **Streifen über dem Eingabefeld** zeigt auf das, was Sie braucht: die
Mikrofonabfrage, eine wartende Freigabe (mit **Karte zeigen**), die letzte
Minute, ein Limit, das den Anruf beendet, eine Wiederverbindung oder wie
Push-to-Talk funktioniert. Endet der Anruf, sagt eine Karte in der Unterhaltung,
wie lange er lief und wie viele Turns gespeichert wurden, oder welches Limit ihn
beendet hat, mit **Erneut anrufen**. Ein Anruf, der nie begann, sagt über dem
Eingabefeld, warum, mit **Erneut versuchen**.

In **Aktivität (Activity)** ist ein Anruf eine Zeile mit einem Mikrofon-Abzeichen,
und der Art-Filter (**Text** oder **Sprachanrufe**) grenzt auf Anrufe ein; ein
Anruf, der sich neu verbunden hat, ist weiterhin eine Zeile, mit Zeit und Kosten
aller Verbindungen summiert. Die Dashboard-Karte **Sprachminuten (Voice
minutes)**, im Nutzungsband für jemanden mit `runs:view`, zeigt die
Anrufminuten und Anrufe des Zeitraums und die drei häufigsten Agents.

### Ein Gespräch abzweigen { #forking }

Um einen anderen Ansatz zu probieren oder eine Nebenfrage dort zu klären, wo sie den Hauptfaden nicht überfrachtet, wählen Sie unter einer Antwort des Agenten **In neue Unterhaltung abzweigen**. Sie erhalten ein neues, eigenes Gespräch im selben Projekt, mit allem bis einschließlich dieser Antwort. Die nächste Nachricht macht dort mit demselben Verlauf weiter; das Original bleibt unverändert.

Abzweigen kann nur, wem das Gespräch gehört: Wer es zum Ansehen oder Bearbeiten freigegeben bekommen hat, sieht die Aktion nicht. Eine Abzweigung kopiert die Nachrichten und die Tool-Aufrufe, nicht die Dateien der Anhänge, die Dateien, die der Agent in seinen Workspace geschrieben hat, die von Agenten erzeugten Bilder, die Kosten oder die Run-Datensätze. Der Agent kennt den Text eines Anhangs weiterhin, aber die Abzweigung zeigt keine Karte dafür; ein von einem Agenten erzeugtes Bild gehört dem Original und lädt nicht mehr, sobald das Original gelöscht ist. Solange ein Run in diesem Verlauf noch schreibt oder auf eine Freigabe oder eine Frage wartet, lässt sich das Gespräch nicht abzweigen.

Oben in einer Abzweigung steht **Abgezweigt aus** mit einem Link zum Original. Diese Zeile sehen nur Sie: Geben Sie die Abzweigung frei, sieht die andere Person ein gewöhnliches Gespräch.

Eine Abzweigung ist auf 2.000 Nachrichten, 10.000 Werkzeugaufrufe und 20 MiB kopierten Text und strukturierte Daten begrenzt. Pro Mitglied und Organisation sind höchstens zehn Anfragen pro Minute erlaubt. Eine gerade aktualisierte Unterhaltung kann die Abzweigung kurzzeitig ablehnen; versuchen Sie es nach der Aktualisierung erneut. Zu große Verläufe müssen vor dem Kopieren gekürzt werden.

Gespeicherte Abzweigungen haben ein eigenes Kontingent von 100 MiB pro Mitglied innerhalb einer Organisation und 1 GiB für die gesamte Organisation. Jede Kopie reserviert ihre Nutzdaten sowie 4 KiB für die Unterhaltung und 1 KiB je Nachricht oder Werkzeugaufruf. PostgreSQL serialisiert die Zulassung, sodass parallele Anfragen das Kontingent nicht überschreiten. Erst das Löschen der Kopie gibt die Reservierung frei; Archivierung oder Löschen des Originals tun dies nicht. Zeichnungen mit gespeicherten Bilddateien lassen sich derzeit nicht abzweigen. Wählen Sie eine frühere Antwort; die Anfrage wird vor dem Erstellen einer beschädigten Kopie abgelehnt.

Ausgelagerter Text und Medien einer übernommenen Zusammenfassung werden in die Kopie eingebettet. Das Löschen des Originals entfernt diesen Kontext daher nicht. Die wiederhergestellten Inhalte zählen zum Limit von 20 MiB. Die Wiederherstellung ist auf 100 externe Verweise und zehn Sekunden begrenzt. Fehlende Inhalte oder überschrittene Grenzen führen zur Ablehnung ohne unvollständige Kopie.

Eine Unterhaltung mit einer gespeicherten Checkliste kann nur an ihrer neuesten Nachricht abgezweigt werden, wenn diese eine Antwort des Assistenten ist. Die Kopie behält diese Checkliste einschließlich Aufgaben-IDs und Abhängigkeiten. Frühere Checklistenstände werden nicht gespeichert; eine frühere Abzweigung wird daher abgelehnt, statt spätere Aufgaben in einen älteren Verlauf zu kopieren.

### Hintergrundthemen { #background-topics }

Aktiviere **Hintergrundthemen** bei einem veröffentlichten Agenten und bitte etwa: „Untersuche den Exportfehler in einem neuen Thema, während wir den Release planen“ oder „Lass den Finanzagenten diese Zahlen prüfen, während wir das Angebot besprechen“. Der Agent verwendet seine eigene festgelegte Version oder einen im Spec festgelegten veröffentlichten Delegaten. Starte aus einem eigenen Gespräch; das neue Thema gehört zum selben Projekt und enthält den Auftrag des Agenten und einen Rücklink, ohne das ursprüngliche Protokoll zu kopieren.

Die Leiste **Hintergrundthemen** über dem Eingabefeld zeigt wartende, arbeitende und pausierte Aufgaben. Öffne das eigene Thema, um die Arbeit zu prüfen oder eine gewöhnliche Freigabe bzw. Frage zu beantworten. **Stoppen** beendet weitere Arbeit, macht aber bereits erfolgte Dateiänderungen oder externe Aktionen nicht rückgängig. Dieselben Aufgaben stehen im Dashboard. Pro Person sind vier aktive Aufgaben möglich; Aufgaben und ihre Ergebnisantworten können keine weiteren Hintergrundthemen starten.

Nach Abschluss antwortet der ursprüngliche Agent mit der aktuellen Gesprächshistorie. Er wartet laufende Antworten ab und fasst ohne Werkzeuge zusammen: Aufgabenausgaben erteilen keine neue Handlungserlaubnis. Gewähltes Hauptmodell und Denktiefe bleiben erhalten; lokale Inferenz bleibt lokal. Lokale Coding-Arbeit bleibt auf dem konkreten gekoppelten Computer und im freigegebenen Ordner. Budgets und Freigaben des Kindes gelten weiter. Das Schließen des Chats beendet die Aufgabe nicht. Ein Worker-Abbruch wird gemeldet; externe Aktionen werden nicht automatisch wiederholt. Freigaben setzen pausierte Aufgaben fort; verlorene Mitgliedschaft oder Projektberechtigung stoppt neue Arbeit und Ergebnisübermittlung.

Das ist ausdrückliche Delegation, getrennt von Gedächtnis, Überwachungen und Routinen. Vorhandene asynchrone Subagenten und Werkzeuge bleiben an einen Lauf gebunden; für Arbeit über dessen Antwort hinaus nutze **Hintergrundthemen**.

### Auf ein anderes Gespräch verweisen { #conversation-references }

Ein Agent mit **Frühere Gespräche** bietet im `@`-Menü die dreißig jüngsten zugänglichen Gespräche an. Wähle eines und stelle eine konkrete Frage dazu. Die Erwähnung benennt das Thema, kopiert aber kein Protokoll und wechselt den antwortenden Agenten nicht. Der Agent liest passende Ausschnitte mit dem bestehenden Gesprächswerkzeug und dessen Zugriffs- und Empfängerprüfung. Einschränkungen für Gruppenchats bleiben bestehen. Für ältere Themen füge Link oder ID ein und bitte den Agenten, sie zu lesen.

## Aktivität { #activity }

**Aktivität** (Activity) zeigt Inhabern von `runs:view` jeden Run der
Organisation: Unterhaltungen, die Agents der Organisation beim Beantworten von
Eval-Fällen und die plattformeigenen Agents bei ihrer Arbeit. Wer einen Run und
sein Protokoll lesen darf, hängt nicht von der Art des Runs ab.

Der Run eines Plattform-Agents zeigt dessen Namen in der Spalte Agent und neben
seiner Oberfläche eine Beschriftung: **Improve** für den Assistenten,
**Bewerter** für den Bewerter, **Wissenslücken** für Klassifizierer und
Entwurfsschreiber und **Testfragen** für den Fallgenerator. Ein Agent, der einen
Eval-Fall beantwortet, trägt **Eval**. Neben der Beschriftung steht ein Link
dorthin, wo diese Arbeit gelesen wird: die Improve-Sitzung, der Eval-Run, das
Wissenslücken-Thema oder das Dataset.

Der Filter **Herkunft** grenzt die Liste auf **Unterhaltungen**, **Improve und
Evals** oder **System-Agents** ein. Er beginnt bei jeder Herkunft, damit ein
Link aus einem Entwurf oder einer Sitzung zu ihrem Run auf einer Zeile landet,
die die Liste zeigt.

## Wofür jeder Bereich da ist { #what-each-area-is-for }

**Overview** (Dashboard), **Chat** und **Inbox** stehen oben in der Seitenleiste.
**Build & manage** zeigt Agents, Workflows, Routines und Apps ohne Aufklappen;
danach folgen Projects.

**Knowledge** ist standardmäßig geöffnet und enthält Knowledge bases, Tables,
Skills, Context und Documents. Die manuelle Wahl zwischen geöffnet und geschlossen
wird gespeichert. **Monitoring** enthält Activity und Background work und ist
standardmäßig eingeklappt.

**Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) und
**Organization** (Organizations, Groups) bleiben einklappbar und speichern Ihre
Wahl. Eine Gruppe mit der aktuellen Seite öffnet sich immer, damit diese sichtbar bleibt.

| Bereich | Er hält | Lesen Sie |
| --- | --- | --- |
| **Agents** | Den Katalog, den Builder, Versionen, Teilen, Testen, Aktivität | [Ihr erster Agent](first-agent.md) |
| **Chat** | Das Gespräch mit einem veröffentlichten Agent | [Oberflächen](channels.md) |
| **Knowledge** | Collections, Dokumente, Sync-Quellen, Ingestion-Einstellungen | [Dateiverarbeitung](file-processing.md) |
| **Skills** | Geschriebene Abläufe, die ein Agent bei Bedarf lädt | [Skills](skills.md) |
| **Context** | Dauerhaftes Wissen, das an viele Agents gebunden ist | [Context-Dateien](context.md) |
| **Tables** | Typisierte Datensätze und ihre Spalten, als Tabelle, Kanban-Board oder Liste | [Virtual Tables](virtual-tables.md) |
| **Workflows** | Mehrstufige Automatisierungen, die Ihre Agents ausführen, auf einer Zeichenfläche gebaut | [Workflows](workflows.md) |
| **Datasets** | Versionierte Testfälle, importiert, exportiert oder aus einer bewerteten Antwort übernommen | [Datasets](datasets.md) |
| **Routines** | Zeitpläne und Ereignis-Trigger | [Trigger](triggers.md) |
| **Runs** | Was lief, was es kostete, was es berührte, ob es fehlschlug | [Governance](governance.md#audit) |
| **Documents** | Alle Dateien, die Agents für Sie aufbewahren - Angehängtes und Geschriebenes | [Die Sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Wo Agents Code ausführen: Hosts, laufende Sessions, Policy | [Die Sandbox](sandbox.md) |
| **MCP servers** | Verbindungen zu externen Werkzeugen, persönlich und organisationsweit | [MCP](mcp.md) |
| **Channels** | Slack-, Teams-, Telegram- und Mattermost-Bots, Widgets, gehostete Seiten | [Oberflächen](channels.md) |
| **Remote agents** | Agents anderer Anbieter, über ihre A2A Agent Card registriert, an die Agents delegieren | [Capabilities](reference/capabilities.md#remote-agents) |
| **Vault** | Zugangsdaten, pro Organisation versiegelt | [Secrets](secrets.md) |
| **Organizations** | Mitglieder, Rollen, Einladungen | [Berechtigungen](permissions.md) |
| **Settings** | Provider, Ingestion-Vorgaben, Benachrichtigungen, Ihr eigenes Profil | [Konfiguration](configuration.md) |
| **Admin** | Das Deployment selbst: Nutzer, Tenants, System, Hintergrund-Jobs, Deployment-Einstellungen | [Das Deployment](deployment.md) |

Der **Agents**-Katalog lässt sich nach **Category** und **Tag** filtern — den
editierbaren, organisationslokalen Labels, die auf der Karte jedes Agents
erscheinen. Jeder Filter ist ein Menü der Labels auf den Agents, die Sie sehen;
kreuzen Sie mehrere an, um ihn zu erweitern. Die Categories und Tags eines Agents pflegen Sie auf seiner
Detailseite, neben den Avatar-Steuerelementen, und die Änderung wirkt sofort,
ohne dass eine neue Version veröffentlicht wird.

Der Tab **Historie** eines Agents enthält seine veröffentlichten Versionen und
benannten Umgebungen und für alle, die seine Runs lesen dürfen, seinen
**Verbesserungsverlauf**: jede Verbessern-Sitzung, was sie gemessen hat, was
entschieden wurde und was sie gekostet hat. Eine abgeschlossene Sitzung öffnet
ihren Assistenten nur zum Lesen, mit der Entscheidung im letzten Schritt; siehe
[Verbesserungsverlauf](authoring.md#improvement-history).

Die Organisationsdetails haben fünf Registerkarten: **Mitglieder** für Personen und Einladungen; **Arbeitsbereich** für Profil und Standard-Spracheinstellungen; **Budget und Freigaben** für Ausgaben und Zugriffsregeln; **Proaktivität** für Vorschläge, Überwachung und Zustellung; **KI und Dienste** für Architect und Systemdienste. Jedes Formular behält seine Berechtigungsprüfung. Budgetverantwortliche erreichen KI und Dienste auch ohne Architect-Konfiguration. Die Auswahl steht in der URL, Entwürfe bleiben beim Wechsel erhalten, und bisherige `?tab=voice`-Links öffnen Arbeitsbereich.

Nach der Anmeldung erscheinen an die Konto-E-Mail adressierte Einladungen auch in Konsole und Onboarding, ohne den E-Mail-Link zu öffnen. Der Empfänger wählt eine Organisation und nimmt ausdrücklich an; Später lässt die Verknüpfung Einladungen verfügbar. Angezeigt werden nur gültige Einladungen an die aktuelle Konto-Adresse, ohne geteilte Links und bereits beigetretene Organisationen. Die Annahme wechselt zur gewählten Organisation und öffnet deren Begrüßung. Der Server gibt in diesem Posteingang keine Einladungstokens zurück.

Der Posteingang erfordert einen Nachweis der E-Mail-Adresse in der aktuellen Sitzung: eine neue OAuth-Anmeldung mit verifizierter Adresse oder einen an die Adresse gebundenen E-Mail-Anmeldelink. Passwort- und ältere Sitzungen zeigen keine Aufforderung zur Bestätigung des Postfachs oder zur Einrichtung des E-Mail-Versands. Einladungen können über ihren ursprünglichen Link angenommen werden, auch bei Installationen ohne E-Mail-Anbieter. Der Nachweis gilt weder für andere Sitzungen noch für eine geänderte Adresse. **Weitere Einladungen anzeigen** lädt weitere Seiten; der Logoabruf prüft die konkrete Einladung unabhängig von deren Listenseite.

Bernsteinfarbene Punkte markieren Organisationstabs und die zugehörigen Karten für Sprache, nächtliche Vorschläge, Gedächtnispflege und Architect bei unvollständiger Konfiguration oder ausgeschalteten Vorschlägen. Hover oder Tastaturfokus zeigt die Erklärung; Klicken oder Tippen hält sie geöffnet. Die Hinweise verwenden gespeicherte Einstellungen, verschwinden nach der Einrichtung und beachten Bearbeitungsrechte. Ausgeschaltete Vorschläge gelten als optionale Einrichtung, nicht als Fehler. Auch die iPhone-Push-Karte markiert einen fehlenden Apple-Schlüssel. Bei reduzierter Bewegung entfällt das Pulsieren.

Gespeicherte Browser-Anmeldungen stehen in einem kompakten Einstellungsbereich über die volle Breite, statt einen Eintrag auf die ganze Seite zu strecken. Bekannte Dienste verwenden mitgelieferte Markenlogos; andere Seiten ihr eigenes Favicon ohne Referrer und bei fehlendem Bild ein Globussymbol.

## Sprachen { #languages }

Die Konsole spricht Englisch, Polnisch, Deutsch und Türkisch. Die erste Karte des
Rundgangs bietet die vier an, und das Kontomenü wechselt die Sprache jederzeit;
die Wahl wird in Ihrem
Konto gespeichert, sodass die Konsole auf jedem Gerät, auf dem Sie sich anmelden,
in ihr öffnet. Sie können auch einen Agent bitten - "auf Englisch umstellen" -, und
die Seite wechselt, während er antwortet, ohne Neuladen. Jeder Agent antwortet in
ihr, außer Sie schreiben in einer anderen Sprache. Produktwörter - Agent, Skill, Run, Budget, MCP und der Rest der Liste
unter [Übersetzen](howto/translate.md) - bleiben in jeder Sprache Englisch.

Dieselbe Karte fragt, was Sie tun, und **Einstellungen → Profil (Settings →
Profile)** hält den Rest dessen, was Agents über Sie wissen: Ihre Rolle, woran Sie
arbeiten und Ihre Zeitzone. Jeder Agent liest sie zu Beginn eines Runs, sodass Sie
sie in keinem Chat wiederholen; „jeden Montag um 9“ ist Ihre 9. Die Zeitzone wird
bei der ersten Anmeldung aus Ihrem Browser übernommen, bis Sie eine wählen.

Die Profileinstellungen verbinden Porträt, Anzeigename und E-Mail in einem
Formular; Ersatzfarben stehen unter einer aufklappbaren Zeile. Speichern steht
unter den Feldern, Enter sendet das Namens- oder Rollenformular. Während eines
Profilzugriffs zum Speichern bleiben Identität und Kontext gesperrt; eine
Ablehnung behält den Entwurf. Arbeitstage haben größere Touch-Ziele; Beginn
und Ende stehen auch auf dem Smartphone in getrennten Feldern.

**Einstellungen → Benachrichtigungen** durchsucht Ereignisnamen und Beschreibungen,
mit sechs Ereignissen pro Seite. Die Chatauswahl ändert den zusätzlichen Kanal,
ohne andere Einstellungen zu verändern. Verknüpfte private Chatziele stehen
zuerst; weitere Plattformen sind eingeklappt. Fehlgeschlagene Lesevorgänge für
Einstellungen, Ziele oder Konten bieten einen neuen Versuch statt erfundener
Standardwerte oder einer scheinbar leeren Kontenliste.

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

- Das Dashboard besteht aus **siebenundfünfzig Widgets**, die Sie selbst
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

Die Seitenleistenfußzeile zeigt die Build-Version der Konsole neben Suche und Benachrichtigungen, auch in der eingeklappten Leiste und im mobilen Menü. Sie stammt aus der im Build eingebetteten Frontend-Paketversion und benötigt keine Netzwerkanfrage. Der Tooltip kennzeichnet sie als Konsolenversion; ein separat aktualisierter API-Prozess kann eine andere Version ausführen.

Eine neuere stabile AgenticOS-Version hebt die Versionsnummer mit einem grünen Punkt hervor. Ein Klick zeigt die laufende und verfügbare Version sowie einen Link zum offiziellen Release. Die Hintergrundprüfung läuft beim Öffnen der Konsole, während der Nutzung alle 30 Minuten und bei veralteten Daten nach erneutem Fokus oder Wiederherstellung der Verbindung. Der Server teilt öffentliche Prüfergebnisse fünf Minuten lang und sendet keine Konto-, Organisations- oder Bereitstellungsdaten an GitHub. Bei Netzwerkfehlern bleibt die laufende Version sichtbar, ohne als aktuell bezeichnet zu werden. Der Hinweis lädt die Seite nicht neu und installiert kein Update automatisch.

Nach der Anmeldung zeigt **Was ist neu** einmal pro Konto auf diesem Gerät die öffentlichen GitHub-Versionshinweise der installierten Version. Das Fenster wartet, bis das Onboarding geschlossen ist. Schließen markiert die Version als gelesen; fehlende Hinweise oder Netzwerkfehler unterbrechen die Sitzung nicht. Funktionen einer neueren, noch nicht installierten Version stehen nur hinter dem Update-Hinweis. Die Abschnitte **Upgrading** und **Notes for operators** mit Migrationen und Upgrade-Schritten sehen nur Administratoren des Deployments; eine Version, die nichts anderes enthält, öffnet für alle anderen kein Fenster.

Chat controls merkt sich Modell, Freigabemodus und lokale Werkzeuge pro Konto und Organisation über Chats hinweg. Projektdateieinstellungen haben Vorrang. Die Zustimmung zum gesamten Computer gilt für eine Unterhaltung oder für einen Agenten, wenn dieser auf Ihrem Computer arbeitet. Das Überspringen von Freigaben benötigt weiterhin die aktuelle Berechtigung und Organisationsrichtlinie. Agent setting (oder Cloud für Dateien) ist deaktiviert, wenn dem veröffentlichten Agenten diese Fähigkeit fehlt; lokale Alternativen werden nicht automatisch aktiviert. Ein Klick auf die ausgewählte lokale Option schaltet sie aus.

Die Benachrichtigungsstummschaltung hat ein Glockensymbol; das Eingabefeld wiederholt die Ordner- und Zugriffsanzeige nicht mehr. Agentenporträts überlappen in voller Größe und spreizen sich in der erweiterten Chatliste beim Darüberfahren leicht auf.

Listenfußzeilen bleiben am unteren Rand ihres Panels mit einheitlichen Abständen und deckendem Hintergrund. Paginierte Verwaltungstabellen scrollen ihre Zeilen unabhängig, während Spaltenüberschriften und Seitennavigation sichtbar bleiben. Leere Ergebnisse und Fehler bleiben im selben Scrollbereich.

Das Organisationsverzeichnis der Administration zeigt das hochgeladene Bild oder Initialen in der gewählten Farbe, wenn kein Bild hinterlegt ist. Der Bildzugriff in diesem Bereich bleibt auf Deployment-Administratoren beschränkt; der reguläre Avatar-Endpunkt verlangt weiterhin eine Mitgliedschaft.

**Chat controls → Tools & files** zeigt das Coding-Konto, das ein Agent braucht, wenn sein Coding agent als **Private cloud task with my account** läuft: nur diesen Harness, mit Logo und Zustimmungsstatus. Verbinde oder verwalte es direkt im Chat; alle Konten stehen unter **Settings → Profile**. Das Verbinden ändert den Ausführungsmodus des Agenten nicht: Private Cloud-Aufgaben benötigen weiterhin **Private cloud task with my account**, während Desktop-Coding eine separate lokale Anmeldung verwendet.

## Ihre erste Aufgabe { #your-first-task }

In einem neuen Workspace ist der mitgelieferte **AgenticOS** bereits vor der Veröffentlichung ausgewählt, sofern Sie keinen anderen Standard festgelegt haben. Auf die erste Nachricht kann er die Modelleinrichtung erklären und eine Konfigurationskarte zeigen, ohne den Entwurf auszuführen oder einen KI-Anbieter aufzurufen. Antwort und Karte bleiben im Chatverlauf. Berechtigte Personen öffnen die Modelleinstellungen des Agenten; andere Mitglieder sehen einen Administratorhinweis und den Supportkontakt der Instanz, falls konfiguriert. Wählen Sie ein Modell, ergänzen Sie bei Bedarf einen Schlüssel und veröffentlichen Sie den Agenten, bevor normale KI-Antworten ausgeführt werden können. Gewöhnliche Entwürfe und archivierte Agenten bleiben von der Ausführung ausgeschlossen.

Wenn kein veröffentlichter Agent verfügbar ist, bietet das Onboarding auch einen zugänglichen Entwurf des mitgelieferten AgenticOS als Einrichtungs-Chat an. Mitglieder können ihn ohne Berechtigung zur Modellverwaltung öffnen; er liefert Einrichtungshinweise statt eines KI-Aufgabenergebnisses. Nicht zugängliche Entwürfe bleiben gesperrt, und ein zugänglicher veröffentlichter Agent hat Vorrang.

Das Schließen des Startbanners oder **Für 24 Stunden ausblenden** pausiert das Angebot für
24 Stunden nach Serverzeit. Danach kann es wieder erscheinen, wenn die Einrichtung nicht
abgeschlossen ist und der Workspace weiterhin einen ersten Einstieg benötigt. Nach den
Fragen speichert **Einrichtung abschließen und App öffnen** den Abschluss für diese
Mitgliedschaft. Optionale Felder, Einladungen, ein Modell, ein Agent oder ein KI-Lauf sind
nicht erforderlich. Der Abschluss der Einrichtung und eine erfolgreiche Aufgabe sind
getrennte Zustände.

Öffnen Sie **Erste Schritte** über das Dashboard, den Startvorschlag oder die
Seitenhilfe. Auf dem Desktop liegt der Starthinweis als halbtransparente Ebene über
der Konsole. Beide Navigationsspalten behalten ihre volle Höhe. Er bietet Administratoren die
Einrichtung und Mitgliedern ein Beispiel und lässt sich schließen. Eine angenommene Einladung öffnet denselben Start in der beigetretenen
Organisation. Die Registrierung versucht, Sie direkt anzumelden; schlägt die Sitzung
fehl, bleiben das erstellte Konto und das Ziel im Anmeldeweg erhalten.

Der Einstieg berücksichtigt Berechtigungen und bestehende Arbeit:

| Person | Geführter Einstieg |
| --- | --- |
| Anwendungsadministrator | Firmen-Workspace erstellen oder wählen, Identität und Einladungen vorbereiten, dann den Beitritt zukünftiger Konten festlegen. |
| Organisationsadministrator | Workspace und Ausgabenlimit vorbereiten, ohne Deployment-Steuerung. |
| Neues Mitgliedskonto | Begrüßung, optionales persönliches Profil und Arbeitskontext, dann erste Aufgabe. |
| Bestehendes Konto in einer weiteren Organisation | Begrüßung im Workspace; gespeichertes Profil verwenden oder bewusst überprüfen. |

Ein AgenticOS-Begleiter erklärt Entscheidungen mit vorbereiteten Oberflächentexten.
Das sind keine Modellantworten und keine KI-Aufrufe. Profil und Arbeitskontext gelten
in allen Workspaces des Kontos. Optionale Angaben lassen sich überspringen.
**Speichern und weiter** wechselt nach erfolgreichem Speichern zur nächsten Frage;
bei einem Fehler bleibt die aktuelle Frage erhalten.

Das Deployment fragt nach Registrierung, Startziel zukünftiger Konten und einer
optionalen Mitteilung mit Vorschau. Nur bearbeitete Felder werden gesendet.
**Aktuelle Einstellungen behalten** verwirft den Entwurf dieser Frage ohne Schreiben.
Die Firmenwahl behält die eingestellte Standardrolle und verschiebt keine bestehenden
Konten. App-Erscheinungsbild, Sprache, iOS-Push-Zugangsdaten und Wartung sind optionale
Karten, die den passenden Administrationsbereich in einem neuen Tab öffnen. Der
Ablauf aktiviert weder Wartung noch hinterlegt er automatisch Zugangsdaten.

Für das Organisationsbudget gibt es Vorschläge und einen Regler. Ein bestehendes Dezimallimit bleibt erhalten. Ohne Limit ist eine eigene
Auswahl; bei null wird vor möglichen blockierten Läufen gewarnt. Das begrenzt erfasste
Nutzung und ist kein Abo oder Guthaben. Erweiterte Freigaben, Assistenten und Sprache
bleiben eingeklappt, mit ihren üblichen Rechten und Speicheraktionen.

Die URL erhält Schritt, Einrichtungsfrage und Workspace für ein Neuladen. Ungespeicherte Änderungen,
Zugriff oder Abschluss werden dadurch nicht gespeichert. Organisationswechsel und
entzogene Rechte verhindern das Wiederherstellen eines privilegierten Schritts.
Der Abschluss des letzten Schritts wird für die Mitgliedschaft gespeichert, auch
wenn optionale Angaben und KI-Einrichtung übersprungen wurden.

Ein früherer Kontoabschluss gilt für Mitgliedschaften, die zu diesem Zeitpunkt bereits
bestanden. Spätere Mitgliedschaften beginnen separat. Eigene Chats und abgeschlossene
Abläufe verhindern automatische Neustarts; veröffentlichte Agenten blenden gewöhnliche
Startangebote aus. Links nach Registrierung oder Einladung begrüßen Mitglieder ohne
eigene Aktivität oder Abschluss auch in Workspaces mit fertigen Agenten. Ältere und
fehlgeschlagene Chats zählen als Aktivität, ohne erfolgreiche Läufe zu behaupten.
Manueller Einstieg und Fortsetzung bleiben verfügbar. Normale Anmeldung öffnet Chat
oder den gewünschten Link.

Der Workspace-Name aktualisiert vor dem Erstellen eine gekennzeichnete Vorschau.
Bestehende Organisationen zeigen ihr Logo oder den eingestellten Ersatzavatar.
Benachbarte Desktop-Karten sind gleich hoch. Übergänge und Feldhervorhebungen
beachten die Bewegungseinstellungen.
Mitglieder wählen aufgezeichnete Beispiele mit getrennten Antwort- und Quell-Tabs.
Beim Wechsel bleibt die Vorschau auf der Seite. Die KI-Einrichtung öffnet einen
schließbaren Dialog mit Escape und Fokuswiederherstellung. Die Beispielwahl ruft
kein Modell auf.

Wählen Sie eine fiktive Besprechungsnotiz, eine Richtlinienfrage oder einen
Angebotsvergleich. Prüfen oder bearbeiten Sie den Text vor **Aufgabe starten**.
Die Ausführung verwendet das Modell und die Ausgabenlimits des gewählten Agenten
und kann Anbieterkosten verursachen. Diese Textbeispiele benötigen weder Bildschirm,
Mikrofon, Sandbox noch ein externes Konto.

Die Beispielvorschau bleibt auch ohne Agenten verfügbar.
Es ruft kein Modell auf, verarbeitet keine Änderungen und zählt nicht als
erfolgreicher Lauf. Berechtigte Builder können einen gemeinsamen Textassistenten
auf einem bewusst gewählten gemeinsamen Chatmodell vorbereiten. Sein monatliches
Limit beträgt 5 USD innerhalb des Arbeitsbereichsbudgets. Bestehende Entwürfe werden
nicht geändert; nutzen Sie dafür den Builder. Andere Mitglieder sehen den Kontakt
des Eigentümers.

Beispielwahl und Ausblenden werden pro Mitgliedschaft auch für andere Geräte
gespeichert. Der Start verlinkt den letzten abgeschlossenen eigenen Webchat.
Ein abgeschlossener Lauf belegt die Ausführung, nicht die Nützlichkeit. Touren
sind optionale Hilfe; ihr Schließen erzeugt keinen erfolgreichen Lauf.
Integrationen, Dateien, Agentenbau, Einladungen und Routinen sind optionale Folgeschritte.

Mitgliederverwalter können prüfen, ob sie und ein bestehendes Mitglied einen gemeinsamen veröffentlichten Agenten ausführen können. Die Vorschau liefert nur diese Antwort, keine privaten Agentennamen, und ruft kein Modell auf. Sie bestätigt nicht die Erreichbarkeit des Anbieters. Einladungen von einer Loopback-Adresse sind in diesem Start gesperrt; verwenden Sie eine für den Empfänger erreichbare Serveradresse.

Abgeschlossene Chat-Turns zeigen den vor einer Agentenfrage gelieferten Text neben der abschließenden Antwort, auch nach Ablehnung der Frage oder Fortsetzung des Runs. Tool-Ergebnisse und Überlegungen bleiben im aufklappbaren Arbeitsverlauf. Dies gilt für gespeicherte und geteilte Chats; die Textlänge entscheidet nicht über die Einordnung.

Der Run-Verlauf unterscheidet die anfragende Person vom Herausgeber, dessen Berechtigung eine externe Anfrage zulässt. Nicht verknüpfte Kanalabsender erscheinen auf Desktop und Mobilgeräten als ausdrücklich unbestätigte Chat-Konten; anonyme Anfragen erhalten keine erfundene Mitgliedsidentität. Die Run-API behält `user_id` als Berechtigungskontext und ergänzt `initiated_by_publisher_fallback` und `asked_in_chat` für eine korrekte Zuordnung. Die Anzeige verknüpft keine Konten und gewährt keinen Zugriff auf persönliche Verbindungen des Herausgebers.
