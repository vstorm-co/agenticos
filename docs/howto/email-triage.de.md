---
source_sha: "94fe4ff073a5"
title: "Ihren Posteingang triagieren und Antworten entwerfen"
description: "Verbinden Sie ein Postfach als abgefragten Ereignis-Trigger und lassen Sie einen Agent Antworten entwerfen oder Aufgaben extrahieren, ohne jemals etwas zu senden."
---

# Ihren Posteingang triagieren und Antworten entwerfen { #triage-your-inbox-and-draft-replies }

Verbinden Sie ein Gmail-Postfach als [Ereignis-Trigger](../triggers.md#gmail-1-minute-and-no-secret-anywhere) und lassen Sie einen Agent jede neue Nachricht lesen und einen Antwortentwurf oder eine Aufgabenliste erstellen. Dies ist eine Anleitung zum Ausführen, kein Bericht über eine gemessene Bereitstellung. Sie braucht ein echtes Gmail-Konto und einen Google-OAuth-Client, den die Bereitstellung hier nicht konfiguriert hat, sodass nichts auf dieser Seite gegen ein echtes Postfach ausgelöst wurde.

## Was der Agent mit E-Mails kann und was nicht { #what-the-agent-can-and-cannot-do-with-mail }

Lesen Sie das, bevor Sie etwas verbinden, denn davon hängt ab, ob die Seite unten die OAuth-Zustimmung wert ist.

**Er kann lesen.** Der Gmail-Trigger fragt das verbundene Postfach einmal pro Minute ab und übergibt dem Agent Betreff, Absender und Text einer neuen Nachricht. Die Bereitstellung bittet Google nur um den Scope `gmail.readonly`. Auf dem Zustimmungsbildschirm wird nichts weiter angefragt, es gibt also keine breitere Berechtigung, auf die man sich versehentlich verlassen könnte.

**Er kann weder senden noch einen echten Gmail-Entwurf anlegen.** Es gibt kein Tool, weder hier noch im MCP-Katalog, das die Sende- oder Entwurfs-API von Gmail aufruft. Was die Vorlagen unten "Entwurf" nennen, ist der Antworttext des Agents, geschrieben in den ausgelösten Run. Er landet in **Activity**, in der Konversation dieses Runs, als Nachricht, die ein Mensch noch lesen und selbst in eine ausgehende E-Mail einfügen muss. Nichts wird je in Ihrem Namen gesendet, und nichts wird ins Postfach zurückgeschrieben.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Einen Google-OAuth-Client, den der Betreiber der Bereitstellung registriert hat (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, Gmail-API aktiviert). Das ist eine Voraussetzung der *Bereitstellung*, nichts, was jede Organisation selbst einrichtet. Ohne ihn sagt die Gmail-Verbindungskarte das, statt einen Knopf zu zeigen, der nur fehlschlagen könnte.
- Die Berechtigung `mcp:manage`, um das Postfach zu verbinden.

## Den Agent bauen { #build-the-agent }

1. Öffnen Sie **Routines → New event trigger → Gmail → Connect account**. Die Zustimmung erlaubt nur lesenden Zugriff auf das Postfach. Das Verbinden löst nichts aus und verliert nichts: Die Position im Postfach wird in dem Moment festgelegt, in dem die Zustimmung abgeschlossen ist.
2. Wählen Sie, was ihn auslöst: jede neue Nachricht, nur der Posteingang oder als wichtig markiert. Grenzen Sie mit **Subject contains**, **Sender contains** oder einem Gmail-Label weiter ein. Alle drei sind optionale Teilstring-Filter, und ein nicht gesetzter Filter bedeutet, dass jede Nachricht im Umfang auslöst.
3. Beginnen Sie mit einer Vorlage statt mit einem leeren Prompt. `GET /trigger-templates` listet zwei für diese Quelle:

   | Vorlage | Was sie tut |
   | --- | --- |
   | **Draft a reply to the email** | Fasst in einer Zeile zusammen, was der Absender braucht, und entwirft dann eine Antwort zur Prüfung |
   | **Turn the email into action items** | Extrahiert jede Aufgabe, ihren Verantwortlichen und eine etwaige Frist |

4. Erstellen Sie einen Agent, den dieser Trigger auslöst, mit einem Modellprofil, und veröffentlichen Sie ihn. Keine der beiden Vorlagen braucht eine Sandbox, eine Wissenssammlung oder eine andere Capability.
5. Binden Sie den Trigger an den veröffentlichten Agent und setzen Sie ihn aktiv.

Der Prompt der Antwortentwurf-Vorlage, wörtlich:

```text
An email just arrived - its subject, sender and body are in this message.
Summarise in one line what the sender needs, then draft a reply I can review and
send. Match the sender's tone, answer every question they asked, and keep it
brief.
```

## Was "Ausführen" hier bedeutet { #what-run-it-means-here }

Es gibt keine signierte Zustellung, die man von Hand senden könnte: Gmail wird abgefragt, nicht gepusht, also gibt es weder eine URL noch ein Geheimnis. Zwei Wege, den Agent arbeiten zu sehen, bevor eine echte Nachricht eintrifft:

- **Run now** am Trigger löst den **Basis-Prompt des Agents ohne Zustellungskontext** aus: keine Nachricht, kein Absender, nichts, worauf man antworten könnte. Das beweist, dass Agent, Budget und Veröffentlichungsstatus in Ordnung sind, prüft aber nicht die Triage, denn in diesem Run gibt es keine E-Mail, auf die die Instruktionen der Vorlage wirken könnten.
- **Eine echte Nachricht im verbundenen Postfach** ist der einzige Weg, einen tatsächlichen Entwurf zu sehen. Der Heartbeat liest einmal pro Minute, was seit der letzten Prüfung eingetroffen ist, bis zu 25 Nachrichten pro Durchlauf. Die schlimmste Verzögerung ist also eine Minute, und ein Schwall von einer Mailingliste wird nicht zu Hunderten von Runs.

## Das Ergebnis prüfen { #check-the-result }

Sobald eine echte Nachricht den Trigger ausgelöst hat, gelten allgemein diese Prüfungen:

| Prüfung | Referenz |
| --- | --- |
| Eine Nachricht, die zum Filter passt | Löst einmal aus, und die Konversation des Runs enthält einen Antwortentwurf oder eine Aufgabenliste, nie eine gesendete E-Mail |
| Eine Nachricht, die **nicht** zu Betreff/Absender/Label passt | Löst gar nicht aus |
| Eine E-Mail ohne klare Frage oder Aufgabe | Die Aufgaben-Vorlage sagt offen, dass es nichts zu tun gibt, statt etwas zu erfinden |
| Der eigene Status der Gmail-Verbindung | Wird am Trigger angezeigt; eine fehlgeschlagene Abfrage wird dort gemeldet, nicht nur in einem Container-Log |
| E-Mails von vor dem Verbinden des Postfachs | Lösen nie aus, weil der Cursor im Moment der abgeschlossenen Zustimmung beginnt |

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Nichts löst aus.** Prüfen Sie zuerst den Status der Gmail-Verbindung, denn eine defekte Abfrage wird am Trigger gemeldet. Prüfen Sie dann den Filter: Ein leeres **Subject contains** oder **Sender contains** passt zu allem, sodass ein enger Filter, der auf dem Papier richtig aussieht, trotzdem die Nachricht ausschließen kann, die Sie als Test gesendet haben.
- **Sie erwarten eine gesendete Antwort und bekommen stattdessen eine Chat-Nachricht.** Genau so ist es hier gedacht, kein Fehler; siehe *Was der Agent mit E-Mails kann und was nicht* oben. Kopieren Sie den Entwurf von Hand in Ihr E-Mail-Programm.
- **Ein verpasster Rückstand nach einem Ausfall.** Google hält etwa eine Woche Verlauf vor. Ein älterer Cursor synchronisiert sich auf jetzt, statt alles Aufgelaufene nachzuholen, sodass ein Postfach, das länger als eine Woche ausfiel, eine Lücke hat, die nichts auffüllt.
- **`Run now` sieht erfolgreich aus, aber nichts Nützliches kam zurück.** Es führte den Agent ohne angehängte Nachricht aus. Das ist erwartet und kein Weg, die Triage selbst zu testen. Warten Sie auf eine echte Zustellung oder senden Sie sich eine passende Test-E-Mail.

## Den Versuch festhalten { #record-the-trial }

Sobald Sie das mit einem echten Postfach ausführen können: Bewahren Sie den gesetzten Filter, die verwendete Vorlage oder den Prompt, einige ausgelöste Runs mit ihren Entwürfen auf und wer diese Entwürfe liest, bevor etwas gesendet wird. Ein Mensch sendet jede Antwort und legt jede Aufgabe ab. Dieser Agent bereitet nur den Text vor.

## Nächste Schritte { #next-steps }

Für eine Triage, die von Ihrer eigenen App statt von einem Postfach gesteuert wird, siehe [Eingehende Support-Anfragen aus Ihrer eigenen App triagieren](support-ticket-triage.md). Sie nutzt einen signierten Webhook, den Sie vollständig kontrollieren, und lässt sich ohne externes Konto prüfen.
