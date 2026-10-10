---
source_sha: "b7c15e4f4e04"
---

# Abteilungen und Gruppen { #departments-and-groups }

Unternehmen sind in Abteilungen organisiert: Vertrieb, Finanzen, Personal,
Support. In AgenticOS ist eine Abteilung eine [Gruppe](directory.md#groups), und
eine Gruppe entscheidet, wer was nutzen darf. Die Finanzabteilung kann eigene
Agents, Skills, Kontextdateien, Wissensdatenbanken und MCP-Server haben, die der
Vertrieb nie sieht, während das, was alle brauchen, für die ganze Organisation
offen bleibt.

## Abteilungen hinzufügen { #adding-your-departments }

**Gruppen** in der Hauptnavigation listet die Gruppen der Organisation. Ein
Mitglied mit `members:manage` legt sie einzeln mit **Neue Gruppe** an oder
mehrere auf einmal mit **Abteilungen hinzufügen**, das Vertrieb, Finanzen,
Personal, Support, Entwicklung, Marketing, Recht und Betrieb anbietet, jeweils
mit Symbol und kurzer Beschreibung. Umbenennen, Symbol ändern oder löschen geht
danach wie bei jeder anderen Gruppe.

Personen kommen auf der Seite der Gruppe hinzu, von Hand oder über eine
[Zuordnung einer Verzeichnisgruppe](directory.md#directory-group-mappings), wenn
Ihr Unternehmen seine Teams bereits in einem Verzeichnis führt.

### Die Leitung einer Gruppe { #a-groups-lead }

Ein Admin kann ein Mitglied zur **Leitung** der Gruppe machen - die Krone neben
ihm in der Mitgliederliste. Die Leitung fügt Personen ihrer Gruppe hinzu und
entfernt sie, ohne die Organisation zu verwalten, sodass eine Abteilungsleitung
eine neue Kollegin aufnehmen kann, ohne die IT zu fragen. Nur wer
`members:manage` hat, bestimmt oder entfernt eine Leitung, denn sie vergibt
Zugriff auf alles, was mit der Gruppe geteilt ist.

## Wer etwas Neues nutzen darf { #who-can-use-a-new-thing }

Wer einen Agent, einen Skill, eine Wissensdatenbank, eine Kontextdatei oder einen
gemeinsamen MCP-Server anlegt, beantwortet eine Frage: **wer es nutzen darf**.

| Auswahl | Wen es erreicht | Gespeichert als |
|---|---|---|
| **Alle** - der Standard | Jedes Mitglied der Organisation | Sichtbarkeit `org` |
| **Nur ich** | Sie und alle, mit denen Sie es später teilen | Sichtbarkeit `private` (eine Wissensdatenbank wird persönlich) |
| **Ausgewählte Gruppen oder Personen** | Die Mitglieder der gewählten Gruppen und die Personen, die Sie nennen | Sichtbarkeit `private`, mit jeder davon auf `use` geteilt |

Gruppen werden angeboten, sobald Sie die dritte Option wählen; Personen findet
man, indem man einen Namen oder eine E-Mail-Adresse eintippt. Jede Auswahl bleibt
als Chip stehen, bis Sie sie entfernen.

Die Mitglieder einer Gruppe finden, was mit ihr geteilt ist, nutzen es und binden
es an ihre eigenen Agents. Personen außerhalb der Gruppe sehen es weder in
Listen, in der Suche, in den Auswahlen des Builders, über die API noch über den AI
Architect, der mit den Berechtigungen der fragenden Person handelt. Mitglieder,
deren Rolle jede Ressource erreicht - standardmäßig Owner, Admin und Builder -,
sehen weiterhin alles; siehe [Berechtigungen](permissions.md).

Apps veröffentlichen Agents, und sie sind zunächst privat für die Person, für die
der Run lief; mit einer Gruppe teilt man eine im Bereich **Share**. Der Bereich
**Sharing** jeder Ressource fügt Gruppen auch nach dem Anlegen hinzu oder
entfernt sie.

## Die MCP-Server einer Abteilung { #a-departments-mcp-servers }

Ein MCP-Server der Organisation - ein gemeinsames Konto, einmal verbunden - lässt
sich genauso einschränken, damit der Buchhaltungsserver der Finanzabteilung ihr
gehört. Mitglieder, die MCP-Server verwalten, sehen die Server der ganzen
Organisation, die, die sie selbst verbunden haben, und die, die mit ihren Gruppen
oder mit ihnen geteilt sind; Owner und Admins sehen alle. Ein Builder außerhalb
der Finanzabteilung findet ihren Server nicht in der Liste, öffnet ihn nicht über
seine ID und veröffentlicht keinen Agent, der ihn nutzt. Siehe
[MCP](mcp.md#personal-or-organization-wide).

Ein Agent, der ihn bereits nutzt, funktioniert weiter für alle, die ihn ausführen
dürfen. Die Auswahl entscheidet, wer den Server wählen darf, nicht, wer über ihn
Antworten bekommt; deshalb zeigt der Builder ihn dort, wo das Wissen des Agents
herkommt.

## Die Seite einer Gruppe { #a-groups-page }

Eine Gruppe zu öffnen, zeigt ihre Personen und alles, was mit ihr geteilt ist,
nach Art gruppiert - Agents, Wissensdatenbanken, Skills, Kontext, Apps und
MCP-Server - mit der Stufe, auf der jedes geteilt wurde. Wer liest, sieht nur, was er ohnehin
öffnen könnte; ein Mitglied des Vertriebs erfährt auf der Seite der
Finanzabteilung also nicht, was diese aufbewahrt.

**Zu dieser Gruppe hinzufügen** teilt mehreres auf einmal: Es listet alles, was
die lesende Person bearbeiten darf und die Gruppe noch nicht hat, mit Suche,
einem Häkchen je Eintrag und der Stufe, auf der geteilt wird. Jedes ist dieselbe
Freigabe, die der Bereich Share schreibt, und braucht dasselbe Recht zu
bearbeiten.

Mitglieder werden benachrichtigt, wenn etwas mit ihrer Gruppe geteilt wird - im
Posteingang und, wenn gewünscht, per E-Mail; *Shared with your group* in den
Benachrichtigungseinstellungen schaltet das ab. Karten in der ganzen Konsole
sagen, für wen etwas ist: *Alle*, seine Abteilungen mit Namen oder *Privat*.

## Woher das Wissen eines Agents kommt { #where-an-agents-knowledge-comes-from }

Ein Agent kann an eine Wissensdatenbank, einen Skill, eine Kontextdatei oder einen
MCP-Server gebunden werden, die enger geteilt sind als der Agent selbst, und nichts verhindert
das. Alle, die der Agent erreicht, bekommen dann Antworten aus dieser Quelle,
auch Personen, die sie selbst nicht öffnen könnten.

Der Tab **Toolbox** im Builder zeigt, woher das Wissen des Agents kommt: wen der
Agent erreicht und bei jeder Quelle, ob sie der ganzen Organisation gehört oder
welchen Gruppen. Eine Quelle, die mit weniger Personen geteilt ist als der Agent,
ist markiert, mit einer Warnung über der Liste. Wenn das nicht gewollt ist,
schränken Sie den Agent auf dieselben Gruppen ein oder erweitern Sie die Quelle.

## Die Gruppen der Person in Anweisungen { #the-persons-groups-in-instructions }

Anweisungen können mit `{{groups}}` die Gruppen der Person nennen, mit der der
Agent spricht - zum Beispiel *„Du hilfst jemandem aus {{groups}}.“* Daraus werden
ihre Gruppennamen, durch Kommas getrennt, oder nichts für einen Besucher. Siehe
[Variablen](reference/spec.md#variables).

## Was noch nicht abgedeckt ist { #what-is-not-covered-yet }

Budgets und Auswertungen pro Gruppe gehören noch nicht dazu.
