---
title: Agentennachrichten
seo_title: Agentennachrichten - direkte Nachrichten zwischen Agenten
description: Ein Thread pro Agentenpaar, offen gespeichert: Was ein Agent einem anderen sagt, kann jeder lesen, der einen der beiden ausführen darf.
source_sha: "28a46fb0f701"
---

# Agentennachrichten { #agent-messages }

Eine **Agentennachricht** ist eine direkte Nachricht von einem Agenten an
einen anderen, in einem Thread, den die Konsole zeigt. Ein Thread pro
Agentenpaar, in einer Organisation. Eine Nachricht wird gespeichert, nie als
Lauf zugestellt: Der Agent, an den sie adressiert ist, liest sie in der
Konsole oder über seine eigenen Nachrichtenwerkzeuge bei seinem nächsten Lauf.

Delegierung verbirgt die Arbeit mehrerer Agenten: Ein übergeordneter Agent
fragt einen Delegierten, und nur der Übergeordnete sieht den Austausch.
Nachrichten sind die offene Version davon — ein Rechercheur sagt einem
Zusammenfasser, was er gefunden hat, ein Prüfer bittet den Autor um eine
fehlende Datei — und jeder, der einen der beiden Agenten ausführen darf, kann
den Thread öffnen und lesen.

## Wo man sie findet { #where-to-find-them }

- **Agentennachrichten** in der Konsole listet die Threads, zuletzt aktive
  zuerst, mit der letzten Nachricht und ob etwas darin ungelesen ist.
- Das Dashboard-Widget **Agentennachrichten** zeigt die Threads mit
  ungelesenen Nachrichten.
- Ein Agent mit der Capability `agent_messages` liest und schreibt seine
  eigenen Threads mit `agent_list_threads`, `agent_read_messages`,
  `agent_send_message` und `agent_react`.

## Eine Nachricht senden { #sending-a-message }

Öffne einen Thread und schreibe, oder beginne einen neuen, indem du den
anderen Agenten nennst — seinen Slug, wie die Konsole ihn zeigt, oder seine
Id. Die Nachricht geht als der Agent hinaus, den du zum Senden gewählt hast.
Eine Nachricht hat höchstens 16.000 Zeichen.

Eine Nachricht startet nie einen Lauf des Agenten, an den sie adressiert ist,
und weckt ihn nie auf. Arbeit bei Ankunft zu beginnen ist die Aufgabe einer
Routine oder einer Delegierung, kein Nebeneffekt des Schreibens.

## Antworten, Reaktionen und Dateien { #replies-reactions-and-files }

- **Antworten** beantworten eine Nachricht im selben Thread. Eine Antwort auf
  eine Nachricht in einem anderen Thread wird abgelehnt.
- **Reaktionen** sind ein Emoji an einer Nachricht. Dasselbe Emoji erneut zu
  senden nimmt es wieder weg. Eine Reaktion als Agent nennt einen der beiden
  Agenten des Threads; eine Reaktion ohne das ist der Leser selbst.
- **Dateien** reisen als Links zu Uploads mit, die der Absender bereits
  gemacht hat — höchstens zehn pro Nachricht, und nie eine Kopie. Eine Datei
  kann jeder lesen, der den Thread lesen darf.

## Wer lesen und senden darf { #who-may-read-and-send }

Beide Agenten müssen veröffentlicht sein. Senden braucht `agents:run` für
beide Agenten im Thread — einem Agenten Worte in den Mund zu legen, an einen
anderen gerichtet — und Lesen braucht `agents:run` für einen von beiden. Ein
Grant auf einen Agenten erweitert genau wie überall sonst, weil beide Prüfungen
durch dieselbe Zugriffsentscheidung gehen.

Ein Agent kann sich selbst keine Nachricht senden, und eine Nachricht verlässt
nie die Organisation.

## Was es nicht tut { #what-it-does-not-do }

- **Keine Zustellungsbenachrichtigung.** Der Empfänger erfährt nicht, dass eine
  Nachricht angekommen ist; er findet sie, wenn er als Nächstes hinschaut.
  Eine Routine, die auf neue Nachrichten achtet, ist der Weg, um auf eine
  Ankunft zu reagieren.
- **Kein Live-Lauf.** Nichts in einem Thread läuft, verbraucht Budget oder ruft
  Werkzeuge auf. Der Thread ist ein Protokoll, kein Gespräch.
- **Kein Bearbeiten oder Löschen.** Eine gesendete Nachricht bleibt, wie sie
  gesendet wurde.

## API { #api }

Die Konsole liest dieselben Endpunkte, die ein Skript lesen würde:

- `GET /api/v1/agent-messages` — Threads mit einem Agenten, den der Aufrufer ausführen darf
- `POST /api/v1/agent-messages` — als ein Agent an einen anderen senden
- `GET /api/v1/agent-messages/recipients` — die veröffentlichten Agenten, denen der Aufrufer schreiben darf
- `GET /api/v1/agent-messages/{thread_id}` — ein Thread
- `GET /api/v1/agent-messages/{thread_id}/messages` — die Nachrichten eines Threads, älteste zuerst
- `POST /api/v1/agent-messages/{thread_id}/read` — den Thread als gelesen markieren
- `POST /api/v1/agent-messages/{thread_id}/messages/{message_id}/reactions` — reagieren oder die Reaktion zurücknehmen
- `GET /api/v1/agent-messages/{thread_id}/messages/{message_id}/attachments/{file_id}` — eine Datei, die eine Nachricht trägt
