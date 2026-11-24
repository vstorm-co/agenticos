---
source_sha: "1fe0c9faf3be"
---

# Sol-Loop { #sol-loop }

Ein Prüfer beurteilt die Arbeit, bevor sie weitergeht, in Runden, bis sie
besteht oder das Budget endet. Runde 1 prüft die ganze Änderung; spätere
Runden prüfen nur den geänderten Code und die offenen Befunde. Der Agent
behebt, was der Prüfer gefunden hat, und ruft erneut auf, um eine frische
Runde zu bitten.

Das ist der Sol-Loop-Skill als Capability. Das Verfahren steht im Skill
`sol-loop` (`backend/app/core/catalog/skills/sol-loop/SKILL.md`), der sagt,
wann eine Prüfung verlangt wird; diese Seite sagt, was die Capability mit
der Antwort macht.

## Wie eine Runde läuft { #how-a-round-works }

Der Agent ruft `run_sol_loop_review` mit der Arbeit und dem Kontext auf, den
sie braucht. Ein Aufruf ist eine Runde: Der Aufruf bittet den einen
konfigurierten Prüfer um ein Urteil und um Befunde mit stabilen Ids.

Nach einer Runde behebt der Agent, was der Prüfer gefunden hat, und ruft
erneut auf, um eine frische Runde zu bitten, bis das Urteil auf dem aktuellen
Diff APPROVE lautet. Die Obergrenze der Runden verhindert, dass wiederholte
Prüfungen die Arbeit ausweiten: Behebe, was verlangt wurde, nichts weiter.
Eine Runde, deren Befunde alle Nits sind, stoppt früh - für abgelehnte Nits
gibt es keine neue Runde.

Die Prüfung eines Prüfers ist nur lesend. Sie beurteilt die Arbeit, wie sie
steht; sie bearbeitet sie nicht, committet nicht, kommentiert nicht und
startet keine Subagents oder Prüfer.

## Konfiguration { #configuration }

| Feld | Standard | Was es ist |
|---|---|---|
| `reviewer` | — | Der eine Prüfer: Name, Anbieter und Modellprofil |
| `max_rounds` | `3` | Wie viele Prüfungsrunden ein Run höchstens verlangen darf (1–5) |

Der Prüfer prüft nur auf dem **primären** Modell seines Profils. Die
Fallback-Kette eines Profils wird hier nie verwendet: Ein Fallback würde
still ein anderes Modell einsetzen, wenn das erste ausfällt, und eine Prüfung
durch ein Ersatzmodell ist nicht die Prüfung, die der Betreiber konfiguriert
hat. Der Code erzwingt nicht, dass das Modell ein Sol-Modell ist: Der
Betreiber richtet das Prüferprofil auf sein Sol-Modell aus, und eine Version
im Code zu nennen, würde veralten, sobald ein neueres Sol erscheint.

## Das Ledger { #the-ledger }

Jede Runde wird im Manifest des Runs festgehalten und als das Befund-Ledger
dargestellt, das der Sol-Loop-Skill führt:

```markdown
## Sol-loop review

Rounds: 2

| Round | Scope | Verdict | Stop |
| --- | --- | --- | --- |
| 1 | full | CHANGES | — |
| 2 | changed-only | APPROVE | approved |

| Finding | Severity | File | Outcome |
| --- | --- | --- | --- |
| S1 | blocker | app/x.py | agree-fixed |
```

Ein Befund, auf den noch niemand geantwortet hat, liest sich als `open`. Ein
Prüfer, der nicht erreicht werden konnte, liest sich als `unavailable`, mit
dem Grund - nie ein Urteil, das er nicht selbst gegeben hat, und nie eine
Freigabe. Ein Budgetende liest sich als `budget_exhausted`, und ist ebenfalls
keine Freigabe. Ein Befund, der nach zwei Antworten weiter umstritten ist,
liest sich als `stuck`: Der Nutzer entscheidet. Die Prüfungsnutzung liest
sich als `not exposed`: Der Prüfungsaufruf liefert nur die Prüfung zurück,
nie ihren Tokenverbrauch.

## Was es nicht tut { #what-it-does-not-do }

- **Behebt nicht, was es findet.** Sol-loop urteilt; der Agent behebt, und
  bittet dann um eine frische Runde.
- **Legt Runden nirgendwo außer im Manifest ab.** Runden stehen im JSONB des
  Run-Manifests, neben den Requests. Es gibt keine Tabelle zu migrieren und
  keine Runde, die man über Runs hinweg abfragen könnte.
- **Ersetzt keinen Prüfer.** Ein Prüfer, dessen Modell nicht aufgelöst werden
  konnte, wird als nicht verfügbar gemeldet, nie durch ein anderes Modell
  ersetzt.
- **Rät keine Nutzung.** Das Ledger sagt, dass die Nutzung nicht offengelegt
  ist, statt eine Zahl zu erfinden.
- **Läuft nicht in einem Live-Anruf.** Eine Prüfung dauert Minuten, auf die
  ein Anruf nicht warten kann, also läuft die Capability im Text-Zwilling des
  Agents, übergeben aus dem Anruf.

Die Capability braucht den Scope `agents:delegate`, weil ihr Prüfer ein
Modellaufruf ist, dem der Agent Arbeit übergibt.
