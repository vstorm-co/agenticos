---
title: Projekte
seo_title: Projekte - gemeinsame Dateien und Anweisungen
description: Ein Projekt gibt laufender Arbeit einen Container mit Dateien und eine Reihe von Anweisungen, die jeder Chat darin teilt, egal welcher Agent antwortet.
source_sha: "a9d760cf0da1"
---

# Projekte { #projects }

Ein **Projekt** ist ein Zuhause für laufende Arbeit: einen Launch, einen
Monatsbericht, ein Kundenmandat. Es hält zwei Dinge, die jeder darin begonnene
Chat teilt:

- **Dateien** in einem Container. Lade ein Briefing, eine Tabelle oder einen
  ganzen Ordner einmal hoch, und jeder Chat im Projekt - der heutige und der
  nächste Woche - arbeitet mit derselben Kopie. Eine Datei, die ein Agent in einem
  Chat schreibt, ist im nächsten da.
- **Anweisungen**, die jeder im Projekt antwortende Agent nach seinen eigenen
  liest: der Ton, die Fristen, wo der Brand Guide liegt.

Ein Projekt hat außerdem einen **Standard-Agent**, mit dem ein neuer Chat darin
beginnt. Antworten kann in einem Projekt-Chat trotzdem jeder Agent; der Standard
entscheidet nur, wo ein Chat anfängt.

## Einen Chat im Projekt beginnen { #starting-a-chat-in-a-project }

Zwei Wege hinein:

- **Neuer Chat** auf der Seite des Projekts öffnet den Chat mit dem Projekt und
  seinem Standard-Agent bereits gewählt.
- Das **+**-Menü des Eingabefelds bietet vor der ersten Nachricht **In einem
  Projekt arbeiten** an. Der Chip neben der Agent-Auswahl zeigt das Projekt; sein
  **×** beginnt den Chat stattdessen außerhalb.

Ein Chat bleibt in dem Projekt, in dem er begonnen wurde. Der Chip in einem
bestehenden Chat führt zurück zum Projekt.

## Was ein Agent im Projekt bekommt { #what-an-agent-gets-in-a-project }

Egal welcher Agent antwortet: Ein Run in einem Projekt-Chat arbeitet im
**Container des Projekts** statt in einem eigenen Workspace:

- Ein Agent ohne Sandbox bekommt eine, die des Projekts, sodass auch ein einfacher
  Chat-Agent die Dateien des Projekts lesen und schreiben kann.
- Ein Agent mit eigener Sandbox-Bindung wird in den Container des Projekts
  verlegt. Die Freigabe-Einstellungen der Bindung gehen mit, sodass ein Autor, der
  für die Shell **Immer fragen** gesetzt hat, diese Sperre behält.
- Name, Beschreibung und Anweisungen des Projekts werden nach den eigenen
  Anweisungen des Agent angefügt. Der Agent bleibt, was er ist, und arbeitet
  hieran.

Der Container ist eine [Sandbox](sandbox.md)-Session, wenn die Installation einen
Sandbox-Dienst betreibt, sodass die Dateien des Projekts auch ausgeführt und nicht
nur gelesen werden können. Ohne ihn hält das Projekt seine Dateien als
gespeicherten Workspace, der genauso liest und schreibt, aber keine Shell hat.

## Dateien { #files }

Der Reiter **Dateien** des Projekts ist der Container zum Durchsuchen: ein Baum
neben einer Ansicht, die Markdown, PDFs, Bilder, Tabellen und Code direkt öffnet.

- **Dateien hochladen** und **Ordner hochladen** legen Dateien oben im Projekt
  ab, ein Ordner behält seinen Baum. Jede Datei unterliegt dem Upload-Limit der
  Installation.
- **Neuer Ordner** legt einen leeren Ordner an, den ein Agent füllen kann.
- Der Papierkorb neben einer Datei oder einem Ordner entfernt sie - einen Ordner
  mit allem darin - für jeden Chat und Agent im Projekt.

Das Verzeichnis `.agenticos` und die eigenen Ordner der Plattform sind hier nicht
beschreibbar; ein Pfad außerhalb des Projekts wird abgelehnt, bevor etwas
geschrieben wird.

Ein Projekt öffnet sich auf **Dateien**. Dateien lassen sich auch irgendwo auf
dem Tab ablegen, und jede zeigt beim Hochladen ihren Fortschritt; ein leeres
Projekt ist ein Ort, die ersten abzulegen. **Chats** listet die Chats des Projekts
wie die Chatliste, und **Apps** die Apps, die ein Run in einem davon
veröffentlicht hat - die, die der Leser öffnen darf.

## Teilen und Berechtigungen { #sharing-and-permissions }

Ein Projekt ist privat für seinen Ersteller, bis er es teilt - mit demselben
**Teilen**-Dialog, den ein Agent oder ein Skill nutzt: Personen,
[Abteilungen](departments.md) oder die ganze Organisation, jeweils auf einer
Stufe.

| Grant-Stufe | Berechtigung | Was sie erlaubt |
|---|---|---|
| `read` | `projects:view` | Das Projekt, seine Dateien und Anweisungen sehen |
| `use` | `projects:use` | Darin chatten, hochladen, Ordner anlegen, Dateien entfernen |
| `edit` | `projects:edit` | Anweisungen und Standard-Agent ändern, teilen, löschen |

Rollen halten diese in den üblichen Bereichen: Owner und Admin erreichen jedes
Projekt, ein Builder arbeitet in den mit ihm geteilten und bearbeitet sie, ein
Member bearbeitet seine eigenen und arbeitet in geteilten, und ein Viewer liest,
was mit ihm geteilt wurde. Ein Chat, dessen Autor `projects:use` verliert,
erreicht die Dateien des Projekts ab dem nächsten Zug nicht mehr.

**Chats bleiben bei ihren Autoren.** Ein geteiltes Projekt teilt seine Dateien
und Anweisungen, nicht die Unterhaltungen darin: Die Chats jeder Person in einem
Projekt sieht nur sie, wie überall sonst in der Konsole.

## Ein Projekt löschen { #deleting-a-project }

Das Löschen eines Projekts entfernt seinen Container und jede Datei darin. Seine
Chats bleiben als normale Chats außerhalb jedes Projekts erhalten.

## Wo Projekte erscheinen { #where-projects-show-up }

- **Projekte** in der Seitenleiste listet die fünf zuletzt genutzten über dem
  Link zu allen.
- Die Chat-Liste führt deine Chats in einem Projekt unter seinem Namen, über den
  Chats außerhalb von Projekten.
- Die Karte **Projekte** im Dashboard zeigt eine Reihe davon, mit deinen Chats in
  jedem.
- `GET /api/v1/projects` und seine Unterrouten gehören zur öffentlichen API, sodass
  ein Skript ein Projekt anlegen und mit Dateien füllen kann. Siehe [die
  API](api.md).
