---
source_sha: "186f40ff9e1d"
---

# Abteilungen und Gruppen { #departments-and-groups }

Unternehmen sind in Abteilungen organisiert: Vertrieb, Finanzen, Personal,
Support. In AgenticOS ist eine Abteilung eine [Gruppe](directory.md#groups), und
eine Gruppe entscheidet, wer was nutzen darf. Die Finanzabteilung kann eigene
Agents, Skills, Kontextdateien und Wissensdatenbanken haben, die der Vertrieb nie
sieht, während das, was alle brauchen, für die ganze Organisation offen bleibt.

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

## Wer etwas Neues nutzen darf { #who-can-use-a-new-thing }

Wer einen Agent, einen Skill, eine Wissensdatenbank oder eine Kontextdatei
anlegt, beantwortet eine Frage: **wer es nutzen darf**.

| Auswahl | Wen es erreicht | Gespeichert als |
|---|---|---|
| **Alle** - der Standard | Jedes Mitglied der Organisation | Sichtbarkeit `org` |
| **Nur ich** | Sie und alle, mit denen Sie es später teilen | Sichtbarkeit `private` (eine Wissensdatenbank wird persönlich) |
| **Ausgewählte Gruppen** | Die Mitglieder der gewählten Gruppen | Sichtbarkeit `private`, mit jeder Gruppe auf `use` geteilt |

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

## Die Seite einer Gruppe { #a-groups-page }

Eine Gruppe zu öffnen, zeigt ihre Personen und alles, was mit ihr geteilt ist,
nach Art gruppiert - Agents, Wissensdatenbanken, Skills, Kontext und Apps - mit
der Stufe, auf der jedes geteilt wurde. Wer liest, sieht nur, was er ohnehin
öffnen könnte; ein Mitglied des Vertriebs erfährt auf der Seite der
Finanzabteilung also nicht, was diese aufbewahrt.

## Woher das Wissen eines Agents kommt { #where-an-agents-knowledge-comes-from }

Ein Agent kann an eine Wissensdatenbank, einen Skill oder eine Kontextdatei
gebunden werden, die enger geteilt ist als der Agent selbst, und nichts verhindert
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

MCP-Verbindungen werden auf Ebene der Organisation geteilt oder bleiben
persönlich, nicht pro Gruppe. Budgets und Auswertungen pro Gruppe gehören noch
nicht dazu.
