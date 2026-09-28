---
source_sha: "bc3d361ee1d5"
title: "Einen Artikel in Social-Media-Beiträge in Ihrer Markenstimme umwandeln"
description: "Hängen Sie einen kurzen synthetischen Artikel an und lassen Sie einen Agent einen Beitrag pro Kanal schreiben, jeder auf die Quelle rückführbar und innerhalb der Grenzen seines Kanals."
---

# Einen Artikel in Social-Media-Beiträge in Ihrer Markenstimme umwandeln { #turn-one-article-into-social-posts-in-your-brand-voice }

Geben Sie einem Agent einen Artikel und einen Skill mit Ihren Regeln für die Markenstimme und den Grenzen pro Kanal, und lassen Sie ihn einen Beitrag für LinkedIn, einen für X und einen Newsletter-Teaser schreiben. Das Beispiel ist kurz genug, um jede Behauptung in den Beiträgen von Hand mit dem Artikel abzugleichen. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz. Sie misst nicht, wie gut die Stimme zu Ihrer passt.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Sandbox, kein Embedding-Modell und keine MCP-Verbindung. Dieser Agent braucht nur die [Skills-Capability](../reference/capabilities.md#skills) und einen Chat-Anhang.

## Die Eingabe vorbereiten { #prepare-the-input }

Speichern Sie dies als Skill unter **Skills → New skill**. Nennen Sie ihn `brand-voice`, geben Sie eine Beschreibung wie "Tone, banned phrases and per-channel limits for turning an article into social posts" an und fügen Sie diesen Inhalt ein:

```text
Plain, confident, specific. Say what happened and what it means for the
reader. Use second person when addressing the reader, and "we" when
describing what the company did. State only facts, numbers and outcomes that
appear in the source article — never round a figure or add an outcome the
article does not give.

## Banned phrases

Never use any of: "game-changer", "revolutionize", "cutting-edge", "seamless",
"unlock your potential", "at the end of the day", "in today's fast-paced
world".

## Channel limits

| Channel | Limit | Shape |
|---|---|---|
| LinkedIn | 80-150 words | Open with the concrete result, two or three short paragraphs, at most one hashtag |
| X | 280 characters or fewer, counting spaces | One idea, no thread, no hashtag needed |
| Newsletter blurb | 40-60 words | One sentence hook, one sentence of detail, end with the placeholder [link] |

Write one post per channel from the attached article. Every claim in a post
must trace to a sentence in the article. If the article does not state a
number or outcome, the post does not state one either.
```

Speichern Sie dann diesen synthetischen Artikel mit etwa 400 Wörtern als `article.md`. Die Zahlen sind für diesen Test erfunden: ein fiktives Unternehmen, ein fiktiver Pilot, nichts davon ist echt.

```text
Northwind Robotics cuts warehouse pick times in six-week pilot

Northwind Robotics, a fictional logistics-robotics company, ran a six-week pilot
of its updated picking robot, the Pallox-3, across three regional warehouses.
The pilot measured the time from an order arriving to an item leaving the pick
station.

Average pick time fell from 12 seconds to 9 seconds per item, a 25 percent
reduction, measured across 40,000 picks during the pilot. The Pallox-3's
battery lasts 8 hours per charge, up from 5 hours on the previous model,
which let two of the three sites run a full shift without a midday swap.

No worker injuries were recorded at any of the three pilot sites during the
six weeks, according to the internal safety log Northwind shared with pilot
staff. The robot's new obstacle sensor, added after last year's design
review, stops the unit within 4 centimeters of an unexpected object, compared
with 15 centimeters on the previous sensor.

Warehouse staff at the pilot sites were surveyed at the end of the six weeks.
68 percent said the robot's new charging dock was easier to use than the old
one; 12 percent reported no opinion; the remainder did not respond to that
question.

Based on the pilot results, Northwind plans to roll the Pallox-3 update out
to 40 additional warehouses during the fourth quarter. The rollout will
happen in four batches of ten sites, starting with the two regions that ran
the pilot. Each batch is expected to take one week to install and configure,
based on the installation time recorded during the pilot.

The Pallox-3 hardware itself did not change during the pilot; the
improvement came from a software update to the picking algorithm, which
Northwind's engineering team had been testing internally for four months
before the pilot began. The update is delivered over the air to existing
Pallox-3 units, so warehouses do not need to replace hardware to get the
faster pick times.

Northwind has not yet published pricing for warehouses outside the original
three pilot sites, and a company spokesperson said in the pilot debrief that
a decision on pricing for the Q4 rollout is still under review. The company
also declined to say whether the update would be offered to older Pallox-2
units.

This is a synthetic case study; Northwind Robotics, the Pallox-3 and every
figure above are invented for this test.
```

Referenzfakten für den späteren Abgleich: 25 % schneller (12 s auf 9 s), 40.000 Picks, ein 8-Stunden-Akku, ein Sensor, der den Roboter innerhalb von 4 cm stoppt, 68 % des Personals fanden die neue Ladestation einfacher zu bedienen, ein reines Software-Update, keine Verletzungen und ein Rollout im vierten Quartal auf 40 Standorte in vier Tranchen. Der Artikel sagt auch, was noch *nicht* bekannt ist: die Preise für den Rollout und ob ältere Pallox-2-Geräte das Update bekommen.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Skills** und binden Sie den gerade erstellten Skill `brand-voice`.
3. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You repurpose one article into social posts.
Follow the bound brand-voice skill for tone, banned phrases and channel limits.
Write exactly one post per channel: LinkedIn, X and the newsletter blurb.
Every claim must trace to a sentence in the attached article. Do not invent a
fact, a number or an outcome the article does not state.
Label each post with its channel name.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent, hängen Sie `article.md` an und senden Sie:

```text
Turn the attached article into one post per channel: LinkedIn, X and the
newsletter blurb.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Länge des X-Beitrags | Höchstens 280 Zeichen, einschließlich Leerzeichen |
| Länge des LinkedIn-Beitrags | 80–150 Wörter |
| Länge des Newsletter-Teasers | 40–60 Wörter |
| Verbotene Formulierungen | Keine der sieben Formulierungen aus dem Skill erscheint in einem Beitrag |
| Jede Zahl und jedes Ergebnis | Lässt sich auf einen Satz in `article.md` zurückführen: 25 %, 12 s auf 9 s, 40.000 Picks, 4 cm, keine Verletzungen, Rollout im vierten Quartal auf 40 Standorte |
| Dieselbe Anfrage ohne angehängte Datei | Der Agent fragt nach dem Artikel, statt einen zu erfinden |

Zählen Sie die Zeichen des X-Beitrags von Hand oder mit einem kurzen Skript. Verlassen Sie sich nicht auf die eigene Längenangabe des Modells.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent rief `load_capability` für `brand-voice` auf und antwortete dann direkt mit allen drei Beiträgen. Der X-Beitrag hatte 185 Zeichen. Der LinkedIn-Beitrag hatte 113 Wörter und der Newsletter-Teaser 50 Wörter, beide innerhalb ihrer Grenzen. In keinem Beitrag tauchte eine verbotene Formulierung auf. Jede Zahl in allen drei Beiträgen (25 %, 12 s auf 9 s, 40.000 Picks, die 4 cm Anhalteweg des Sensors und der Rollout im vierten Quartal auf 40 Standorte in vier Tranchen) stimmte mit dem Artikel überein. Kosten: 0,016 USD.

    Ohne angehängte Datei lud der Agent trotzdem den Skill, schrieb dann "I don't see any article attached to your message" und bat um den Artikel, statt Beiträge aus dem Nichts zu schreiben.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Ein Beitrag überschreitet seine Grenze.** Der Skill nennt die Grenze als Regel, nicht als Vorschlag. Verschärfen Sie die Instruktionen so, dass der Agent vor der Antwort zählen muss, oder kürzen Sie die Beispiellängen im Skill selbst.
- **Eine verbotene Formulierung rutscht durch.** Prüfen Sie, ob genau dieser Skill-Inhalt gebunden ist und nicht von einer älteren Version überdeckt wurde. Skills hält eine Version pro Skill, und eine alte Konversation kann vor einer Änderung eine frühere Antwort geladen haben.
- **Der Agent erfindet eine Statistik.** Bitten Sie ihn, den Satz zu zitieren, aus dem eine Zahl stammt. Eine Zahl, die er nicht zurückzitieren kann, hat er erfunden.
- **Der Agent schreibt Beiträge ohne angehängten Artikel.** Wenn er nicht ablehnt, verschärfen Sie die Instruktionen, sodass er ablehnen muss, wenn keine Datei vorhanden ist.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie den Artikel, den Skill-Inhalt, die drei Beiträge, die Agent-Version und den Run in Activity auf. Bewahren Sie auch einen Run auf, in dem eine Grenze überschritten wurde. Er zeigt, ob der Fehler an der Formulierung des Skills oder an der Arithmetik des Modells lag.

Ein Mensch entscheidet weiterhin, ob die Stimme wirklich nach der Marke klingt und ob ein Beitrag veröffentlichungsreif ist. Das Zählen der Zeichen und die Prüfung verbotener Formulierungen sind mechanisch, das Urteil über die Stimme nicht.

## Nächste Schritte { #next-steps }

Fügen Sie die Stimme einer zweiten Marke als eigenen Skill hinzu und binden Sie jeweils den, den eine Konversation braucht, statt einen Skill um eine Variante pro Kunde wachsen zu lassen. Wie ein Skill eingegrenzt und geteilt wird, beschreibt [Skills](../skills.md).
