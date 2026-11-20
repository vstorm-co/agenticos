---
source_sha: "ac197a8b5ef6"
---

# Babysit PR { #babysit-pr }

Einen Pull Request in CI und Review-Bots beobachten, nur melden, was
sich geändert hat, und stoppen, wenn die Bots auf dem neuesten Commit
grün sind. Das ist der Babysit-PR-Skill als Capability: Das Verfahren
steht im `babysit-pr`-Skill
(`backend/app/core/catalog/skills/babysit-pr/SKILL.md`), der sagt, wann
beobachtet wird; diese Seite sagt, was die Capability mit einem
Snapshot macht.

## How a watch works { #how-a-watch-works }

Der Agent beobachtet mit der Monitor-Capability — `start_monitor` auf
`gh pr checks --watch` — und übergibt jeden neuen Snapshot an
`babysit_pr_check` mit Repo, PR-Nummer, Head-SHA und den Checks, wie
gemeldet. Das Tool klassifiziert den Snapshot: Nur die Checks des
aktuellen Commits zählen, jeder fehlgeschlagene Check wird als echt
oder Flake benannt, mit Grund, und nur die Checks, die sich seit dem
letzten Snapshot geändert haben, werden gemeldet. Wenn sich nichts
geändert hat und die Beobachtung weiterläuft, ist der Bericht leer,
und der Agent beendet seine Runde ohne Nachricht — er postet nie und
sagt nie „warte noch".

Die Beobachtung endet, wenn das Tool Grün auf dem neuesten Commit
meldet, wenn die Beobachtung über ihr konfiguriertes Maximum hinaus
ohne Grün läuft, oder wenn der Agent sie mit `babysit_pr_stop`
stoppt — bereit, blockiert oder mit einer Frage an den Nutzer. Ein
Merge oder Schließen beendet die Beobachtung von selbst. Vor dem
erneuten Beobachten prüft der Agent `gh api rate_limit` und übergibt
das Ergebnis an `babysit_pr_rate_limit`: Solange Aufrufe übrig sind,
beobachtet er erneut, wenn sie fast aufgebraucht sind, wartet er auf
den Reset.

## Configuration { #configuration }

| Feld | Standard | Was es ist |
|---|---|---|
| `poll_interval_seconds` | `300` | Sekunden zwischen den Prüfungen des Pull Requests (60–1800) |
| `max_watch_minutes` | `240` | Minuten, die eine Beobachtung laufen darf, bevor sie stoppt und blockiert meldet (30–1440) |

Abfragen liegen mindestens 60 Sekunden auseinander, sodass der
Watcher nie in einer engen Schleife abfragt und nie das gemeinsame
GitHub-Limit verbraucht. Eine Beobachtung, die ohne Grün über ihr
Maximum hinaus läuft, wurde nicht freigegeben — sie ist abgelaufen.

## The watch log { #the-watch-log }

Jeder Check, der sich geändert hat, wird im Run-Manifest
aufgezeichnet, mit seiner Klassifizierung und der Entscheidung, zu
der er geführt hat. Eine Flake-Klassifizierung ist eine Heuristik
über den eigenen Fehlertext des Checks, kein Urteil: Der Agent prüft
jeden Befund an der Quelle, bevor er ihn mit einer schriftlichen
Begründung abweist, und ein Fehler, dessen Text auf kein
Infrastruktursignal passt, ist echt, bis das Gegenteil bewiesen ist.

## What it does not do { #what-it-does-not-do }

- **Mergen, kommentieren oder sonst etwas auf dem PR unternehmen.**
  Nur beobachten und melden. Eine Meldung ist eine Nachricht, keine
  Merge-Entscheidung; das Merge-Gate prüft der Agent, und ein Merge
  braucht die ausdrückliche Bitte des Nutzers.
- **`gh` selbst ausführen.** Die Checks zu lesen, ist die Aufgabe
  des Agenten, unter der Monitor-Capability. Diese Capability
  klassifiziert Snapshots, die ihr übergeben werden, also braucht sie
  weder GitHub-Zugangsdaten noch einen Sandbox-Scope.
- **Einen PR beobachten, der ihr nicht gehört.** Ein Watcher pro PR,
  und nur der Thread, dem der PR gehört, beobachtet ihn. Ein
  delegiertes Kind beobachtet nie; ein zweiter PR, während einer
  aktiv ist, wird abgelehnt.
- **Beobachtungsereignisse anderswo als im Manifest halten.**
  Ereignisse leben im JSONB des Run-Manifests, neben den Requests.
  Es gibt keine Tabelle zu migrieren und kein Ereignis, das über
  Runs hinweg abgefragt wird.
