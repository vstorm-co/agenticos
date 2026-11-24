---
source_sha: "5e91e7483c03"
---

# Rat { #council }

Drei Delegierte prüfen die Arbeit, bevor sie weitergeht: je ein starkes
Modell von drei verschiedenen Anbietern, mit hohem Reasoning-Aufwand,
parallel. Jeder Delegierte bewertet die Arbeit mit bis zu 10 Punkten, und
eine neue Prüfung nach Korrekturen ist eine neue Runde. Die Schleife läuft,
bis jeder Delegierte zufrieden ist.

Das ist der Council-Skill als Capability. Das Verfahren steht im Skill
`council-review` (`backend/app/core/catalog/skills/council-review/SKILL.md`),
der sagt, wann eine Prüfung verlangt wird; diese Seite sagt, was die
Capability mit der Antwort macht.

## Wie eine Runde läuft { #how-a-round-works }

Der Agent ruft `run_council_review` mit der Arbeit und dem Kontext auf, den
sie braucht. Ein Aufruf ist eine Runde: Der Aufruf verteilt die Arbeit an
die Delegierten, jeden auf dem Modell seines eigenen Anbieters, und liefert
ihre Punktzahlen mit ihren Befunden zurück.

Nach einer Runde behebt der Agent, was die Delegierten gefunden haben, und
ruft erneut auf, um eine frische Runde zu bitten, bis jeder Delegierte
mindestens die Einigungsschwelle erreicht. Die Obergrenze der Runden
verhindert, dass wiederholte Prüfungen die Arbeit ausweiten: Behebe, was
verlangt wurde, nichts weiter.

Die Prüfung eines Delegierten ist nur lesend. Sie beurteilt die Arbeit, wie
sie steht; sie bearbeitet sie nicht und schlägt keine Arbeit außerhalb ihres
Umfangs vor.

## Konfiguration { #configuration }

| Feld | Standard | Was es ist |
|---|---|---|
| `members` | — | Genau drei Delegierte, jeder mit einem Namen, einem jeweils anderen Anbieter und einem Modellprofil |
| `agreement_threshold` | `8` | Die Punktzahl von 10, die jeder Delegierte erreichen muss, damit eine Runde den Rat zufriedenstellt |
| `max_rounds` | `3` | Wie viele Prüfungsrunden ein Run höchstens verlangen darf (1–5) |

Jedes Mitglied prüft nur auf dem **primären** Modell seines Profils. Die
Fallback-Kette eines Profils wird hier nie verwendet: Ein Fallback würde
still einen anderen Anbieter einsetzen, wenn der erste ausfällt, und ein Rat
mit zwei Delegierten bei einem Anbieter ist kein Rat.

## Die Tabelle { #the-table }

Jede Runde wird im Manifest des Runs festgehalten und als die Tabelle
dargestellt, die der Council-Skill in eine PR-Beschreibung setzt:

```markdown
## Council review

Rounds: 2

| Delegate | Round 1 | Round 2 |
| --- | --- | --- |
| Claude Opus | 7/10 | 9/10 |
| GPT Sol | 8/10 | 10/10 |
| Gemini Pro | 7/10 | 9/10 |
```

Ein Delegierter ohne Punktzahl liest sich als `no score`. Einer, der nicht
erreicht werden konnte, liest sich als `unavailable`, mit dem Grund. Keiner
von beiden bekommt je eine Punktzahl, die er nicht selbst gegeben hat, und
ein nicht verfügbares Mitglied wird nie ersetzt.

## Was es nicht tut { #what-it-does-not-do }

- **Behebt nicht, was es findet.** Der Rat urteilt; der Agent behebt, und
  bittet dann um eine frische Runde.
- **Legt Punktzahlen nirgendwo außer im Manifest ab.** Punktzahlen stehen im
  JSONB des Run-Manifests, neben den Requests. Es gibt keine Tabelle zu
  migrieren und keine Punktzahl, die man über Runs hinweg abfragen könnte.
- **Läuft nicht in einem Live-Anruf.** Eine Prüfung dauert Minuten, auf die
  ein Anruf nicht warten kann, also läuft die Capability im Text-Zwilling des
  Agents, übergeben aus dem Anruf.

Die Capability braucht den Scope `agents:delegate`, weil ihre Delegierten
Modellaufrufe sind, denen der Agent Arbeit übergibt.
