---
source_sha: "62fe6a8232a7"
title: "Anfragen an ein Team von Spezial-Agents weiterleiten"
description: "Bauen Sie einen Front-Desk-Agent, der eine Abrechnungs- oder eine technische Frage an einen veröffentlichten Spezialisten delegiert und nachfragt, wenn eine Frage mehrdeutig ist."
---

# Anfragen an ein Team von Spezial-Agents weiterleiten { #route-requests-to-a-team-of-specialist-agents }

Bauen Sie drei Agents: einen Abrechnungsspezialisten, einen technischen Spezialisten und einen Front Desk, der eine Frage an den zuständigen weiterleitet oder nachfragt, wenn es nicht klar ist. Jeder Spezialist wird separat veröffentlicht, wird also geprüft, versioniert und kann von anderen Front Desks wiederverwendet werden. Dies ist eine Anleitung zum Ausführen, mit drei festgehaltenen Fragen als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil für alle drei Agents.
- `agents:run` auf beiden Spezialisten, um sie vom Front Desk aus festzupinnen. Das ist dieselbe Berechtigung, die eine Kanal-Erwähnung oder eine Delegationsprüfung überall sonst im Produkt auflöst. Siehe [Berechtigungen](../permissions.md#delegation-is-not-a-privilege-boundary).
- Keine Wissenssammlung, keine Sandbox und keine MCP-Verbindung für dieses Beispiel.

## Die Eingabe vorbereiten { #prepare-the-input }

Ein kleines synthetisches Produkt, damit die Fakten der Spezialisten prüfbar sind:

**Abrechnungsfakten**: Basic-Plan 9 USD/Monat, Pro 29 USD/Monat, beide monatlich abgerechnet. Volle Rückerstattung innerhalb von 14 Tagen nach einer Belastung, ohne Angabe von Gründen; danach keine. Rechnungen werden am Tag der Belastung per E-Mail verschickt und sind immer auf der Billing-Seite des Kontos verfügbar.

**Technische Fakten**: Der API-Schlüssel liegt unter Settings → API keys; das Erzeugen eines neuen widerruft den alten sofort. Das Rate-Limit beträgt 60 Anfragen pro Minute und Schlüssel; eine `429` nennt die Sekunden, die zu warten sind. Status und Vorfallverlauf werden auf einer Statusseite veröffentlicht.

## Die beiden Spezialisten bauen { #build-the-two-specialists }

Veröffentlichen Sie jeden als eigenen Agent ohne Capabilities. Jeder antwortet nur aus den Fakten, die Sie ihm gegeben haben.

1. **uc-billing-specialist**: Instruktionen mit den Abrechnungsfakten oben und dem Hinweis, dass eine Frage außerhalb davon nicht in den Bereich dieses Agents fällt.
2. **uc-tech-specialist**: Instruktionen mit den technischen Fakten oben und derselben Ablehnung für alles andere.

Veröffentlichen Sie beide, bevor Sie den Front Desk bauen. Ein Delegate muss ein veröffentlichter Agent sein, den Sie ausführen dürfen, referenziert über seinen Slug.

## Den Front Desk bauen { #build-the-front-desk }

1. Erstellen Sie einen dritten Agent, **uc-front-desk**, und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Delegation**. Lassen Sie `allow_dynamic` aus: Dieser Agent ruft immer nur die beiden Spezialisten auf, die Sie nennen, nie einen, den er selbst erfindet.
3. Fügen Sie unter **Delegates** beide veröffentlichten Spezialisten hinzu, auf ihre aktuelle Version gepinnt.
4. Legen Sie Budget und Schrittlimit für den Versuch fest.
5. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You are the front desk for this product's support. You never answer a billing
or technical question yourself.
Route a billing question (pricing, refunds, invoices, charges) to the billing
specialist with task(description=..., subagent_type="uc-billing-specialist").
Route a technical question (the API, keys, rate limits, uptime) to the
technical specialist with task(description=..., subagent_type="uc-tech-specialist").
If a question could be either, or names neither, ask the user one short
question to tell which team it belongs to before delegating anything.
Relay the specialist's answer; do not add facts of your own.
```

`task` hat keine Seiteneffekte, also bittet keine der beiden Delegationen standardmäßig um Genehmigung. Genehmigen würde ein Mensch die eigenen Tools des Spezialisten, im Spec des Spezialisten.

## Wer bezahlt und was der Nutzer sieht { #who-pays-and-what-the-user-sees }

Der Run des Front Desks bezahlt den ganzen Austausch: Ein gemeinsames Ausgabenbuch deckt den Parent und jeden aufgerufenen Spezialisten ab, und durchgesetzt wird mitten im Gespräch das Budget des Front Desks. Jeder Spezialist bekommt trotzdem eine eigene Zeile in Activity mit `parent_run_id` auf dem Run des Front Desks, sodass die Frage "was hat der Abrechnungsspezialist diesen Monat gekostet" eine Antwort hat, die die Rechnung der Organisation nicht verdoppelt. Siehe [wie ein delegierter Run festgehalten wird](../governance.md#what-a-delegated-run-is-recorded-as).

Die fragende Person sieht eine durchgehende Antwort. Der Front Desk gibt weiter, was der Spezialist gesagt hat. Im Transkript sieht nichts nach Übergabe aus, bis Sie den Run in Activity öffnen und die Delegation darunter sehen.

## Eine Genehmigung innerhalb einer Delegation { #an-approval-inside-a-delegation }

Keiner der Spezialisten hat hier ein geschütztes Tool, also parkt nichts. Hätte einer eines, etwa eine `send_email`-Capability beim Abrechnungsspezialisten, würde die Genehmigung trotzdem in derselben Warteschlange landen, die die Person im Gespräch mit dem Front Desk beobachtet, mit Angabe, **welcher Delegate** den Aufruf vorgeschlagen hat, nicht nur welches Tool. Die Genehmigung setzt diesen Spezialisten dort fort, wo er angehalten hat, statt erneut von vorn zu delegieren. Siehe [eine Genehmigung innerhalb einer Delegation](../governance.md#an-approval-inside-a-delegation).

## Ausführen { #run-it }

Stellen Sie dem Front Desk drei Fragen, jede in einer eigenen Konversation:

```text
I was charged twice this month, can I get a refund on the extra charge?
```

```text
My integration keeps getting 429s, what's the limit and where do I check status?
```

```text
Something changed and now it doesn't work like before.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Abrechnungsfrage | Delegiert an `uc-billing-specialist`; die Antwort nennt die 14-Tage-Rückerstattungsregel |
| Technische Frage | Delegiert an `uc-tech-specialist`; die Antwort nennt das Limit von 60 pro Minute und die Statusseite |
| Mehrdeutige Frage | Keine Delegation; der Front Desk fragt, zu welchem Team sie gehört |
| Activity, Abrechnungs-Run | Ein Kind-Run unter dem des Front Desks, `parent_run_id` gesetzt, eigene Kosten |
| Activity, technischer Run | Dieselbe Form, unter `uc-tech-specialist` |
| Eine Frage, die kein Team nennt, und die Person verweigert die Klärung | Der Front Desk fragt weiter nach, statt zu raten, welchen Spezialisten er aufruft |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, für alle drei Agents. Die Frage zur Rückerstattung erzeugte einen `task`-Aufruf an `uc-billing-specialist` (Kosten 0,0236 USD für den Run des Front Desks einschließlich des Delegates), dessen Antwort das 14-Tage-Fenster nannte und auf die Billing-Seite verwies. Die Frage zum Rate-Limit erzeugte einen `task`-Aufruf an `uc-tech-specialist` (0,0227 USD), dessen Antwort 60 Anfragen pro Minute und die Statusseite nannte. Die mehrdeutige Nachricht erzeugte gar keine Delegation: "Could you tell me a bit more about what changed - is this related to billing... or something technical...?" (0,0066 USD). Die eigene Run-Zeile des Abrechnungsspezialisten verbuchte 0,0057 USD als Kind des Front-Desk-Runs und bestätigte damit die oben beschriebene Form aus gemeinsamem Buch und getrennter Zeile.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Front Desk antwortet selbst, ohne Delegation.** Die Instruktionen wurden nicht befolgt, oder `subagents` ist nicht gebunden. Prüfen Sie die Toolbox, bevor Sie den Prompt erneut lesen.
- **Das Veröffentlichen des Front Desks wird unter Nennung eines Delegates abgelehnt.** Einer der Spezialisten ist nicht veröffentlicht, oder Sie dürfen ihn nicht ausführen. Das Pinnen prüft `agents:run` auf der Zeile dieses Spezialisten.
- **Der Front Desk fragt immer nach, auch bei einer klaren Abrechnungsfrage.** Die Weiterleitungsregel in den Instruktionen ist zu streng, oder das Modell liest "could be either" zu weit. Grenzen Sie die Beispiele im Prompt ein.
- **Ein Spezialist beantwortet eine Frage außerhalb seiner Fakten, statt abzulehnen.** Seine eigenen Instruktionen sagen nicht, dass er ablehnen soll. Fügen Sie die ausdrückliche Ablehnungszeile von oben hinzu.
- **Die Version eines Delegates hat sich geändert, ohne dass Sie darum gebeten haben.** Hat sie nicht. Ein Pin ändert sich nur, wenn der Spec des Front Desks gegen die neue Version neu veröffentlicht wird. Siehe [ein gepinnter Delegate bewegt sich nicht von selbst](../governance.md#a-pinned-delegate-does-not-move-on-its-own).

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie jede Frage, den antwortenden Spezialisten, die Antwort, den Kind-Run in Activity mit seinen eigenen Kosten und die Summe des Front Desks auf. Ein Mensch entscheidet weiterhin, was mehrdeutig genug für eine Rückfrage ist, prüft die Fakten jedes Spezialisten vor der Veröffentlichung und beurteilt, ob eine weitergegebene Antwort wirklich wiedergibt, was der Spezialist gesagt hat.

## Nächste Schritte { #next-steps }

Fügen Sie einen dritten Spezialisten hinzu und beobachten Sie, wie schwer es wird, die Weiterleitungsinstruktionen des Front Desks eindeutig zu halten. Das ist ein gutes Zeichen, dass das Team handgeschriebenen Weiterleitungsregeln entwächst. `allow_questions` lässt einen Spezialisten mitten in der Antwort dieselbe Person fragen, mit der der Front Desk spricht, statt zu raten; siehe [Delegation](../reference/capabilities.md#delegation).
