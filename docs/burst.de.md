---
source_sha: "30a1fb9a1506"
---

# Burst { #burst }

Eine Aufgabe teilt sich in unabhängige Teilaufgaben, die parallel laufen,
und deren Ergebnisse zu einem Ergebnis zusammengeführt werden - ein Burst
paralleler Arbeit statt eines sequenziellen Laufs. Der Agent teilt die
Aufgabe zuerst und zeigt die Aufteilung der Person, so wie OpenMausBots
`/burst` die Teile vorab zeigt, dann fächert ein Aufruf die Teile parallel
auf Worker auf und gibt die Zusammenführung zurück.

Dies ist OpenMausBots Burst-Modus v0.1.153 als Capability: das Konzept -
Aufteilung vorab zeigen, Teile parallel laufen lassen, Ergebnisse
zusammenführen - neu aufgebaut auf dem Fan-out, den Council (#5) und
Sol-loop (#6) bereits nutzen. Das Verfahren lebt im `burst-mode`-Skill
(`backend/app/core/catalog/skills/burst-mode/SKILL.md`), der sagt, wann zu
teilen ist; diese Seite sagt, was die Capability mit den Teilen macht.

## Wie ein Burst läuft { #how-a-burst-works }

Der Agent ruft `run_burst` mit der Aufgabe und den Teilen auf, jeder Teil
ein Prompt für seinen eigenen Worker. Ein Aufruf ist ein Burst: Der Aufruf
führt jeden Teil parallel auf dem eigenen Modell des Runs aus und führt
zusammen, was zurückkommt, in Teilreihenfolge, unter der eigenen
Überschrift jedes Teils.

Nach einem Burst handelt der Agent bei den fehlgeschlagenen Teilen -
wiederholt sie, macht sie direkt, oder verengt die Aufgabe - und ruft erneut
für einen neuen Burst auf. Die Obergrenze für Bursts verhindert, dass
wiederholte Bursts die Arbeit ausweiten: Behebe, was fehlgeschlagen ist,
nichts weiter. Führe nicht den ganzen Burst erneut aus, um einen Teil zu
reparieren: Burste nur die fehlgeschlagenen Teile.

Ein Burst-Worker macht nur seinen eigenen Teil und nichts anderes. Er macht
die Arbeit eines anderen Teils nicht erneut und weitet die Aufgabe nicht aus.

## Konfiguration { #configuration }

| Feld | Standard | Was es ist |
|---|---|---|
| `max_subtasks` | `3` | Wie viele Teilaufgaben ein Burst höchstens gleichzeitig ausführt (2–10) |
| `max_bursts` | `3` | Wie viele Bursts ein Run höchstens verlangen darf (1–5) |

Die Obergrenze für Teilaufgaben spiegelt die `max_fanout`-Obergrenze von
Subagents - Standard 3, Höchstwert 10 - statt sie zu erhöhen. Die Worker
sind einmalige Ambient-Agents auf dem eigenen Modell des Runs, abgerechnet
gegen das Budget des Runs; eine Budgetverweigerung zeichnet den Teil als
fehlgeschlagen auf, statt über die Obergrenze hinaus auszugeben.

## Die Zusammenführung { #the-merge }

Jeder Burst wird auf dem Run-Manifest aufgezeichnet und rendert als das
zusammengeführte Ergebnis, das der Burst-Skill in eine PR-Beschreibung setzt:

```markdown
## Burst

Task: Write the guide

Parts: 3 - 3 completed, 0 failed.

| B1 | Part 1 | completed |
| B2 | Part 2 | completed |
| B3 | Part 3 | completed |
```

Ein Teil, der fehlgeschlagen ist, liest sich als `failed` mit seinem Grund,
und die Zusammenführung nennt ihn unter einer `FAILED`-Überschrift mit einer
Fußzeile, die zählt - nie als Teil, der fertig wurde, und nie aus der
Zusammenführung gefallen. Ein Burst, der einen Teil verloren hat, liest sich
nie als einer, der ihn fertiggestellt hat.

## Was es nicht tut { #what-it-does-not-do }

- **Einen fehlgeschlagenen Teil fallen lassen.** Ein Worker, der eine
  Ausnahme wirft oder nichts Verwertbares zurückgibt, wird als `failed` mit
  dem Grund aufgezeichnet. Die Zusammenführung sagt es.
- **Ein Ergebnis erfinden.** Die Zusammenführung sind die tatsächlichen
  Ergebnisse der Teile unter ihren eigenen Überschriften. Nichts wird
  weg-zusammengefasst.
- **Die Fan-out-Obergrenze erhöhen.** Die Obergrenze für Teilaufgaben ist die
  Obergrenze von Subagents, keine neue.
- **Mit einer Spec delegieren.** Burst-Worker sind einmalige Agents auf dem
  eigenen Modell des Runs, ohne eigene Spec. Ein Teil, der eigene Tools,
  Credentials oder einen stehenden Agent braucht, ist eine Delegation über
  die Subagents-Capability, kein Burst-Teil.
- **Die Arbeit bewerten.** Burst-Teile arbeiten; sie beurteilen nicht. Ein
  Burst, der beurteilt werden muss, ist eine Council-Runde nach der
  Zusammenführung.
- **Reparieren, was fehlgeschlagen ist.** Der Burst repariert nicht und
  iteriert nicht von selbst. Der Agent wiederholt, macht den Teil direkt
  oder verengt die Aufgabe, dann fragt er nach einem neuen Burst.
- **Bursts woanders als auf dem Manifest halten.** Bursts leben im JSONB des
  Run-Manifests, neben den Requests, und werden über das Manifest-Schema
  zurückgelesen. Es gibt keine Tabelle zu migrieren und keinen Burst, der
  über Runs hinweg abfragbar wäre.
- **Auf einem Live-Anruf laufen.** Ein Burst dauert Minuten, auf die ein
  Anruf nicht warten kann, also läuft die Capability im Text-Zwilling des
  Agents, vom Anruf übergeben.

Die Capability braucht den Scope `agents:delegate`, weil ihre Worker
Modellaufrufe sind, denen der Agent Arbeit übergibt.
