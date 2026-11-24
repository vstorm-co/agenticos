---
source_sha: "eacd467a0b5c"
---

# Eval-Tool-Tuning { #eval-tool-tuning }

Bewerte ein Tool anhand bereits beurteilter Eval-Fälle und entwirf
Tuning-Vorschläge aus den Fehlern. Ein Tuning-Run nimmt die beurteilten
Ergebnisse eines Eval-Versuchs - die Fälle, die die Failure-Learning-
Schleife (#32) versucht hat - und fragt, wie sich ein Tool über sie hinweg
verhalten hat: Wurde es aufgerufen, wurde das richtige Tool gewählt, gab
es einen Fehler, verfehlte die Antwort trotzdem das Ziel?

Dies ist der Eval-Tool-Tuning-Skill als Capability. Das Verfahren lebt im
`eval-tool-tuning`-Skill
(`backend/app/core/catalog/skills/eval-tool-tuning/SKILL.md`), der sagt,
wann ein Tool bewertet wird; diese Seite sagt, was die Capability mit der
Antwort macht.

## Wie ein Tuning-Run funktioniert { #how-a-tuning-run-works }

Der Agent ruft `record_eval_tool_tuning` mit dem Tool und den beurteilten
Fällen auf - jeden Fall mit dem, was seine Antwort hätte sagen sollen, ob
der Judge sagte, dass sie bestanden hat, was die Antwort sagte, und jedem
Tool-Aufruf, den der Run des Falls gemacht hat. Ein Aufruf ist ein
Tuning-Run: Er bewertet das Tool, klassifiziert jeden Fehler, entwirft je
Fehlerklasse einen Vorschlag und zeichnet den Run im Manifest auf.

Ein Fehler gehört zu einer von vier Klassen:

| Klasse | Was sie bedeutet |
|---|---|
| `not_called` | Kein Tool lief bei dem Fall - das Tool wurde nie erreicht |
| `wrong_tool` | Ein anderes Tool wurde stattdessen gewählt |
| `bad_arguments` | Das Tool wurde aufgerufen und schlug fehl |
| `wrong_answer` | Das Tool lief sauber, aber die Antwort verfehlte trotzdem die Erwartung |

Jede Klasse entwirft eine Art von Vorschlag:

| Fehler | Vorschlag | Was er ändert |
|---|---|---|
| `not_called`, `wrong_tool` | `tool_choice` | Welches Tool gewählt wird - eine Routing-Regel, oder dieses Tool dem gewählten vorzuziehen |
| `bad_arguments` | `tool_parameters` | Die Argumente des Tools - ihre Pflichtfelder, Bereiche und was als gültig zählt |
| `wrong_answer` | `prompt_wording` | Was die Antwort sagen muss - eine Zeile in den Anweisungen des Agents |

Ein Vorschlag je Klasse, nicht je Fall: Fünf Fälle, die auf dieselbe Weise
scheitern, sind ein Tuning-Problem, nicht fünf. Eine Bewertung ohne Fehler
entwirft nichts.

## Konfiguration { #configuration }

| Feld | Standard | Was es ist |
|---|---|---|
| `max_tuning_runs` | `3` | Wie viele Tuning-Runs ein Run höchstens aufzeichnen darf (1–5) |

Die Obergrenze verhindert, dass wiederholtes Bewerten die Arbeit
ausweitet: bewerten, die Entwürfe zeigen, einen Menschen entscheiden
lassen. Ein neuer Tuning-Run nach Anwendung eines Vorschlags ist ein
neuer Run.

## Der Datensatz { #the-record }

Jeder Tuning-Run wird im Run-Manifest aufgezeichnet und in der Run-
Schublade angezeigt:

```markdown
## Eval-Tool-Tuning

Tool: search · 1/2 bestanden · häufigster Fehler: not_called

| Fall | Klassifizierung |
| --- | --- |
| total | passed |
| missing | not_called |

| Vorschlag | Art | Belege |
| --- | --- | --- |
| Route these requests to search | tool_choice | missing |
```

## Was es nicht tut { #what-it-does-not-do }

- **Eine Antwort beurteilen.** Das Urteil je Fall kommt bereits beurteilt
  an, vom `judge()` der Failure-Learning-Schleife
  (`app/services/eval_judging.py`, geteilt mit Workflow-Evals). Die
  Bewertung verbraucht `(passed, shown)`-Paare; ein zweiter Judge würde
  vom ersten abweichen, und das Eval-Gate würde aufhören, eine Sache zu
  bedeuten.
- **Evals ausführen.** Fälle über den Test-Run-Pfad laufen zu lassen, ist
  der Try-Runner der Schleife (#32). Bis #32 landet, nimmt das Tool
  beurteilte Fälle als Eingabe; wenn #32 landet, speisen seine
  Try-Ergebnisse dieses Tool.
- **Einen Vorschlag anwenden.** Jeder Vorschlag ist ein Entwurf mit seinen
  scheiternden Fällen als Belegen, zur Freigabe durch einen Menschen. Das
  Anwenden einer Anweisungsänderung läuft über das Proposal-Apply der
  Schleife (eval-gated, auditiert); eine Skill-Änderung über den
  Learned-Skill-Pfad (#9). Hier gibt es keine Apply-Funktion.
- **Tuning-Runs anderswo als im Manifest halten.** Runs leben im JSONB des
  Run-Manifests, neben den Requests. Es gibt keine zu migrierende Tabelle
  und keinen Tuning-Run, der über Runs hinweg abfragbar wäre - die eigenen
  Tabellen der Schleife halten die Fälle, sobald #32 landet.

Die Capability braucht keinen Scope: Ihr Tool zeichnet im eigenen Manifest
des Runs auf und ruft kein Modell auf, delegiert nichts und berührt keinen
Dienst.
