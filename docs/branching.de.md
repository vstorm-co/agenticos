---
source_sha: c8b11ff21e6a
---

# Branches und was sie schützt { #branches-and-what-protects-them }

Ein einziger langlebiger Branch.

```
feat/… fix/… ──pull request──▶ main
```

`main` ist das, was ein Leser dieses Repositorys klont, und das, woraus Tags
geschnitten werden. Alles, was dorthin gelangt, tut das als gequetschter Commit
aus einem kurzlebigen Branch, nachdem die CI am Pull Request gelaufen ist.

Ein Push auf `main` und ein `v*`-Tag veröffentlichen außerdem jeweils die beiden
Container-Images - `ghcr.io/vstorm-co/agenticos-backend` und `-frontend`, `edge`
und `sha-<short>` aus dem Branch, die Version und `latest` aus dem Tag - über
`.github/workflows/images.yml`. Der Workflow hat keinen Pull-Request-Trigger,
also kann ein Fork nichts unter dem Namen der Organisation veröffentlichen, und
er weist einen Commit ab, der nicht auf `main` liegt, sodass auch ein aus einem
Branch gepushter Tag `latest` nicht verschieben kann;
[Deploy](deploy.md#the-images) sagt, was sie zieht.

Es gibt kein `dev`. Kurzzeitig gab es das: Arbeit landete dort und erreichte
`main` in Release-Pull-Requests. In dieser Größenordnung brachte es einen
Staging-Branch, den niemand brauchte, und kostete einen zweiten Ort, an dem jede
Änderung liegen musste, also wurde es entfernt.

## Was erzwungen wird, und wodurch { #what-is-enforced-and-by-what }

| Regel | Erzwungen durch |
|---|---|
| Kein direkter Push auf `main` | Ruleset — ein Pull Request ist erforderlich |
| CI grün vor dem Merge | Erforderliche Status-Checks: `lint`, `test`, `test-frontend`, `e2e`, `docs`, `Security Scan` |
| Squash beim Merge | Ruleset — die einzige erlaubte Merge-Methode |
| Konversationen aufgelöst | Ruleset |
| Veraltete Freigaben werden bei einem neuen Push verworfen | Ruleset |
| Kein Force-Push, keine Löschung | Ruleset |
| Kein Commit, während man auf `main` steht | `no-commit-to-branch` in `.pre-commit-config.yaml` |
| Rechtschreibung, über jede versionierte Datei | codespell — als Hook auf den Dateien, die ein Commit berührt, und als `make lint-spelling` im `lint`-Job der CI über den gesamten Baum |
| Routen halten nur Router, keine Banner-Kommentare, keinen toten Code | `check_routes.py`, `check_comments.py` und `vulture` — Hooks in `.pre-commit-config.yaml` (jeder scannt den gesamten Baum, `pass_filenames: false`) und Schritte von `make lint-backend` im `lint`-Job der CI |
| Keine deklarierte Abhängigkeit, die nichts importiert | `deptry` — ein Schritt von `make lint-backend` im `lint`-Job der CI, der auf DEP002 und DEP004 prüft. Kein Pre-Commit-Hook: es liest das gesamte Manifest gegen den gesamten Baum, es gibt also keine Variante der Frage pro Datei |
| YAML-Formatierung, Workflow-Sicherheit, die Pre-Commit-Grundlagen, über jede versionierte Datei | yamlfmt, zizmor und `pre-commit-hooks` (`end-of-file-fixer`, `trailing-whitespace`, `check-yaml/json/toml`, `detect-private-key` …) — als Hooks auf den Dateien, die ein Commit berührt, und als `make lint-precommit` im `lint`-Job der CI über den gesamten Baum. Wie bei der Rechtschreibung sind diese ihrer Natur nach dateiweise, sodass ein `rev:`-Sprung, der eine neue Regel mitbringt, jede bestehende Datei bricht, ohne dass es jemand bemerkt, bis eine unbeteiligte Änderung daran scheitert |

Ein Hook liest immer nur, was ein Commit berührt, was ihn für sich genommen zu
einem schlechten Tor macht: ein Tippfehler, der mit seiner Datei gemergt wird,
liegt dort, bis jemand diese Datei aus einem anderen Grund bearbeitet, und dessen
Commit wird an einem Wort abgewiesen, das er nicht geschrieben hat. Deshalb steht
die Rechtschreibprüfung zweimal in der Tabelle — der Hook ist die schnelle
Rückmeldung, `make lint-spelling` hält die Aussage für den gesamten Baum wahr.

Die Status-Checks sind heute einzeln aufgeführt. Sie sollten zu einem einzigen
aggregierenden Job `All Checks Passed` zusammenfallen, damit das Hinzufügen eines
CI-Jobs nicht mehr bedeutet, "daran zu denken, ein Ruleset zu bearbeiten" — eine
Liste erforderlicher Checks, die vom Workflow abdriftet, ist der Weg, auf dem ein
Build am Ende über nichts grün wird.

### Ein erforderlicher Check darf berechtigterweise `skipped` melden { #a-required-check-may-legitimately-report-skipped }

!!! info "Ein erforderlicher Check mit `skipped` ist ein Pass, kein Problem"

    GitHub erfüllt einen erforderlichen Status-Check mit `success`, `skipped`
    **oder** `neutral`. Ein Branch, der nur das Backend berührt, bekommt also gar
    keine Antwort vom Frontend - was heißt, dass "grün" auf so einem Branch eine
    Aussage über weniger Jobs ist, als `make check` ausführt.

Drei dieser sechs laufen nicht bei jedem Pull Request. `test`, `test-frontend`
und `e2e` kosten 8,2, 5,3 und 5,1 abgerechnete Minuten, und ein `changes`-Job
entscheidet, welche davon ein Änderungssatz nachweislich nicht beeinflussen kann
— `scripts/ci_changed_scope.py`, sodass die Regel prüfbar ist statt ein Glob in
einer YAML-Datei
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

Deshalb ist das Tor ein `if:` auf Job-Ebene und **kein** `paths:`-Filter auf dem
Workflow: ein herausgefilterter Workflow meldet seine Checks überhaupt nie,
sodass das Ruleset auf sechs Kontexte wartet, die niemals eintreffen, und der
Merge-Button für immer grau bleibt.

Der Klassifizierer ist in der zurückhaltenden Richtung geschrieben: **ein Job
wird nur dann übersprungen, wenn jeder geänderte Pfad nachweislich für ihn
irrelevant ist**, sodass ein unbekannter Pfad alles ausführt.

Die freizügige Schreibweise derselben Idee würde ein neues Verzeichnis
stillschweigend eine Suite vom Laufen abhalten lassen — was kein roter Build ist,
sondern ein grüner, bei dem ein Tor fehlt, und dieses Repository hat dafür schon
zweimal bezahlt (#143, #165).

Es gibt nur zwei Ausnahmen, beide geprüft statt angenommen:

- `docs/**`, `mkdocs.yml` und eine `*.md` auf oberster Ebene, weil kein Test
  eine davon liest;
- die jeweils andere Hälfte des Baums, für jede der beiden Unit-Suiten.

`e2e` ist von keiner der beiden Hälften ausgenommen, und `lint` wird überhaupt
nie durch ein Tor geführt — weil `make lint-spelling` und `make lint-precommit`
jede versionierte Datei lesen.

Die zweite Ausnahme macht vor einem Verzeichnis halt.
`frontend/src/app/api/**` ist das BFF, und
`backend/tests/api/test_bff_forwarded_paths.py` prüft die `/api/v1/…`-Pfade, die
diese Handler fest verdrahten, gegen die Routentabelle des Backends — eine
Änderung an einem Proxy führt also auch die Backend-Suite aus. Sie dort zu
überspringen wäre derselbe Fehler "grün mit fehlendem Tor" wie oben, an genau dem
Test, der geschrieben wurde, um ihn zu fangen.

Zwei Details braucht die zurückhaltende Richtung, damit sie tatsächlich hält, und
die erste Fassung hat beide falsch gemacht:

- Jeder torgeführte Job trägt `!cancelled()` neben der Ausgabeprüfung. Ohne das
  würde ein `changes`-Job, der **fehlschlägt** — ein 502 von der API, ein Rate
  Limit — alle drei Suiten überspringen, ohne dass ihre Bedingungen je gelesen
  würden, und da `changes` selbst kein erforderlicher Kontext ist, würde der
  Merge-Button über einem Branch grün, auf dem keine Suite gelaufen ist.
- Der Job füttert `previous_filename` ebenso ein wie `filename`. Eine Umbenennung
  meldet nur den Pfad, an dem sie angekommen ist, sodass ein aus `backend/`
  verschobenes Modul sonst ein Frontend-Pfad wäre und die Backend-Suite für eine
  Änderung überspringen würde, die ein Backend-Modul gelöscht hat.

Was ein Änderungssatz überspringt, steht im Log des `changes`-Jobs. Lokal wird
nichts übersprungen: `make check` führt den gesamten Satz aus.

### Ein gestapelter Pull Request führt die CI ebenfalls aus { #a-stacked-pull-request-runs-ci-too }

Zwei Branches, die dieselbe Datei bearbeiten, sollen gestapelt werden — der
zweite wird gegen den ersten geöffnet statt gegen `main` — deshalb trägt der
`pull_request`-Trigger in `ci.yml` **keinen `branches:`-Filter**. Dieser Filter
greift auf der *Basis*, und solange er da war, passte ein gestapelter Pull
Request auf keinen Trigger und führte überhaupt nichts aus
([#359](https://github.com/vstorm-co/agenticos/issues/359)).

Die gefährliche Hälfte war nicht der fehlende Lauf, sondern wie er sich las. Ein
Pull Request ohne Jobs zeigt eine **leere** Check-Liste, keine rote: `gh pr
checks` antwortet "no checks reported" und das Rollup ist leer, was aussieht wie
ein Lauf, der noch nicht begonnen hat. Vier Pull Requests wurden an einem Tag so
gemergt, jeder nur auf einem Laptop verifiziert. Nichts schloss die Lücke, bis
das Kind nach dem Merge seines Elternteils auf `main` umgehängt wurde, und genau
dann wartet niemand auf einen frischen Lauf von sieben Minuten.

Es kostet wenig: der `changes`-Job klassifiziert ein gestapeltes Kind anhand
seines eigenen Diffs — er liest `pulls/{n}/files`, was dem Vergleich gegen die
eigene Basis dieses Pull Requests entspricht — und die Concurrency-Gruppe weiter
unten bricht die überholten Läufe des Kindes ab wie bei jedem anderen auch.

Dass der Trigger keinen Basisfilter trägt, wird geprüft statt angenommen, in
`backend/tests/test_ci_workflow.py`. Das muss so sein: ein Workflow, der nicht
auslöst, erzeugt keinen Beleg dafür, dass er es nicht getan hat, also kann nichts
an einem Lauf die Regression zeigen. Dieselbe Datei prüft die andere Eigenschaft,
die kein Lauf zeigen kann — dass jeder Job seine eigene Laufzeit begrenzt, siehe
unten.

Zwei Grenzen, die klar gesagt gehören. **Ein grüner gestapelter Pull Request
wurde gegen sein Elternteil geprüft, nicht gegen `main`** — Checks gehören zu
einem Head-Commit, also trägt das Umhängen das alte Ergebnis unverändert weiter;
das liegt am Stapeln selbst und nicht an etwas, das ein Trigger beheben könnte,
und es ist ein Grund, Stapel kurz zu halten. Und **CodeQL ist hier nicht
konfiguriert**: es läuft aus GitHubs Standardeinrichtung, deren Trigger nicht in
diesem Repository liegen, also ist es nicht unsere Entscheidung, ob es einen
gestapelten Pull Request liest.

### Jeder Job begrenzt seine eigene Laufzeit { #every-job-bounds-its-own-runtime }

`changes` war der einzige Job in `ci.yml`, der ein `timeout-minutes` trug, also
erbten die anderen sieben GitHubs Standardwert von **360 Minuten**
([#364](https://github.com/vstorm-co/agenticos/issues/364)), sodass ein
hängender Job seinen erforderlichen Status-Check sechs Stunden lang gehalten
hätte, ohne dass irgendetwas in diesem Repository ihn früher beendet. Das war als
Vorsichtsmaßnahme gegen etwas geschrieben, das niemand gesehen hatte. Vierzehn
`e2e`-Läufe erreichten die Grenze in den vier Tagen bis zum 18. August
([#879](https://github.com/vstorm-co/agenticos/issues/879)) — und wie ein Job
dabei aussieht, steht weiter unten.

| Job | Grenze | Gemessen |
|---|---|---|
| `changes` | 5 | 7s |
| `lint` | 10 | 22s |
| `Security Scan` | 10 | 14s |
| `docs` | 15 | 4m34s |
| `test-frontend` | 20 | 5m08s |
| `docker` | 20 | 2m30s |
| `test` | 25 | 7m43s |
| `e2e` | 25 | 8m01s |

Die gemessenen Zeiten stammen aus Lauf 31116003994, einer vollen Matrix auf
`main`. Jede Grenze liegt beim Mehrfachen ihres Jobs statt knapp darüber: das
Timeout existiert, um einen Hänger zu beenden, und eines, das eng genug ist, um
einen berechtigt kalten Cache zu kappen, ist ein roter Build aus einem Grund, der
nichts mit dem Diff zu tun hat.

### Ein Lauf pro Branch { #one-run-per-branch }

`ci.yml` trägt eine Concurrency-Gruppe mit Schlüssel `github.ref`, sodass ein
erneuter Push auf einen Branch dessen vorigen Lauf abbricht. Das ist wichtig,
weil `CLAUDE.md` einen Commit und einen Push pro fertigem Teilstück verlangt:
ohne Abbruch wurden 75 der 369 Läufe in den ersten sechs Augusttagen überholt,
während sie noch liefen — etwa 1.800 abgerechnete Minuten, die Fragen zu Commits
beantworteten, auf die niemand wartete.

**Ein Push auf `main` ist ausgenommen, und wie er ausgenommen wird, ist der
interessante Teil.**

Der Lauf des Merges selbst ist das, was Historie und Badge überhaupt bedeutsam
macht, also darf ein `main`-Lauf weder abgebrochen noch eingereiht werden.

`cancel-in-progress: false` liefert nur das erste davon. `false` heißt
*einreihen*, und GitHub bricht jeden zuvor **wartenden** Lauf einer Gruppe ab,
wenn ein neuerer eingereiht wird.

Bei einer einzigen Gruppe für `main` — Merge A läuft, B wartet — würde ein
landendes C B rundheraus abbrechen, und Bs Commit bekäme überhaupt keine CI. Bei
vierzehn Releases in sechs Tagen gegen einen `main`-Lauf von rund 10 Minuten sind
zwei Merges innerhalb eines Fensters keine seltene Form.

Also trägt die Gruppe bei einem Push `github.run_id`, das pro Lauf eindeutig ist:
jeder Merge bekommt eine eigene Gruppe und kollidiert mit nichts. Pull Requests
lösen alle zum selben Suffix auf und brechen einander weiterhin pro `github.ref`
ab.

### Zwei Dinge melden `cancelled`, und nur eines davon ist das { #two-things-report-cancelled-and-only-one-of-them-is-that }

Der Abschnitt oben beschreibt den Abbruch, der wie entworfen funktioniert, und er
ist die Erklärung, nach der alle greifen. **Das andere ist ein Job, dem seine
`timeout-minutes` ausgegangen sind** — GitHub verzeichnet einen Job, den es an
der Grenze beendet hat, als `cancelled` und nicht als Fehlschlag — und ein
erforderlicher Check mit `cancelled` gilt *nicht* als Pass, wie ein `skipped` es
tut, sodass der Merge über einem Diff blockiert bleibt, mit dem alles in Ordnung
ist.

Sie auseinanderzuhalten kostet einen Blick:

| | Überholt (#317) | An der Grenze beendet (#879) |
|---|---|---|
| Was sonst im Lauf ist | jeder laufende Job gemeinsam abgebrochen | **ein** Job; der Rest ist grün |
| Der Schluss des Laufs selbst | `cancelled` | `success`, abzüglich des einen Jobs |
| Dauer des abgebrochenen Jobs | was immer er erreicht hatte | seine `timeout-minutes`, auf die Sekunde |
| Ein neuerer Push auf dem Branch | ja — das ist die Ursache | nein |
| Die letzte Zeile des Logs | `The operation was canceled.` | dieselbe Zeile, und das ist die Falle |

Die Dauer ist das Erkennungszeichen.
`gh api repos/vstorm-co/agenticos/actions/runs/<id>/attempts/<n>/jobs` liefert
`started_at`, `completed_at` und Schlüsse pro Schritt — **und es muss die Form
`attempts/<n>` sein**, denn ein Re-Run schreibt um, was der schlichte Endpunkt
`runs/<id>/jobs` antwortet, sodass ein ins Grüne wiederholter Job dort `success`
meldet und der ursprüngliche Schluss verschwunden ist.

Was die vierzehn gemeinsam hatten, war ein Schritt: `playwright install
--with-deps`, das nach `apt-get` ausweicht, was unbegrenzt hängt, wenn der
Azure-Mirror des Runners nicht erreichbar ist. Der e2e-Job installiert überhaupt
keine Systempakete mehr, und `backend/tests/test_ci_workflow.py` weist einen
Schritt ab, der das täte. Die allgemeine Lehre überlebt diesen Schritt jedoch:
**ein Schritt, der zu einem Dritten greift, ist ein Schritt, der ohne eigene
Grenze hängen kann**, und einer, der das tut, verbraucht das gesamte Budget des
Jobs und meldet sich dann als der Abbruch von jemand anderem.

## Squash, und warum der Titel des Pull Requests zählt { #squash-and-why-the-pull-request-title-matters }

!!! important "Die Beschreibung des Pull Requests *ist* die Commit-Nachricht, die überlebt"

    `main` behält einen Commit pro Pull Request, gebaut aus Titel und Rumpf statt
    aus den eigenen Commits des Branches. `CLAUDE.md` hat das Format.

Also erreichen `wip`, `fixup` und `try again` es nie — und die Beschreibung ist
keine Höflichkeit.

## Die Notluke { #the-escape-hatch }

!!! warning "Es gibt keine Bypass-Akteure"

    Ein Owner, der jetzt etwas mergen muss, deaktiviert das Ruleset, mergt und
    schaltet es wieder ein - drei Klicks und ein Audit-Eintrag, was genau das
    richtige Maß an Reibung für etwas ist, das selten sein sollte.

Das ist Absicht: ein Bypass, der immer verfügbar ist, ist ein Bypass, der
wöchentlich genutzt wird, und ein Release-Weg, den niemand beschreiben kann.

## Aktualisierung von Abhängigkeiten { #dependency-updates }

Das Backend läuft wöchentlich, wobei die Agent-Frameworks getrennt von allem
anderen gruppiert sind — sie bewegen sich schnell, und diese Codebasis soll ihnen
folgen. Das Frontend läuft monatlich, nach einer Abkühlzeit von sieben Tagen.

Dependabot schlägt Aktualisierungen für **direkte** Abhängigkeiten vor. Alles
darunter bewegt sich nur, wenn eine direkte es mitzieht, und genau dafür gibt es
`.github/workflows/dependency-freshness.yml`: einmal pro Woche hebt es das
gesamte Lock an — transitive Pakete eingeschlossen —, führt die ganze Suite
dagegen aus und eröffnet ein Issue, wenn das etwas bricht. Nichts wird committet;
die Aktualisierung wird mit dem Runner verworfen. `make deps-upgrade-all` ist
dasselbe lokal und der Weg, auf dem sich ein rotes Issue daraus reproduzieren
lässt.

Zwei Dinge daran sind nicht offensichtlich, und beide haben Zeit gekostet, bevor
sie verstanden waren:

- **Ein Gruppenmuster muss ein abschließendes `*` tragen, um eine mit Extras
  geschriebene Abhängigkeit zu treffen.** `pydantic-ai-slim[openrouter,…]` wird
  von `pydantic-ai-slim` nicht getroffen. Dieses Schweigen kostete Monate: die
  Gruppe `agent-frameworks` eröffnete keinen einzigen Pull Request, und die
  Laufzeit ritt mit ihren Majors in `backend-everything-else` mit. Umgekehrt
  bleibt `fastapi` exakt, weil es ohne Extras deklariert ist und keine Wildcard
  braucht; früher musste es eine vermeiden, da `fastapi*` auch `fastapi-cache2`
  fing, bis diese Abhängigkeit in #155 entfernt wurde.
- **Dependabot kann `frontend/bun.lock` nicht aktualisieren.** Sein
  npm-Ökosystem kennt `package-lock.json`, `yarn.lock` und `pnpm-lock.yaml`, und
  nicht das von bun. Ein Frontend-Sprung kommt also als `package.json` allein an,
  und `bun install --frozen-lockfile` weist die Abweichung ab, wodurch
  `test-frontend` und `e2e` aus einem Grund rot werden, der nichts mit der
  Abhängigkeit zu tun hat. **Erzeugen Sie es von Hand neu** auf dem Branch des
  Pull Requests:

  ```bash
  cd frontend && bun install --lockfile-only && git commit -am "build(deps): sync bun.lock"
  ```

  Das zu automatisieren ist schwerer, als es aussieht: ein Workflow auf
  `pull_request` bekommt ein schreibgeschütztes Token, wenn Dependabot ihn
  ausgelöst hat, ganz gleich was sein `permissions`-Block sagt, also kann er das
  Ergebnis nicht zurückpushen.

## Reviews { #reviews }

Der [automatisierte Reviewer](code-review.md) läuft bei jedem Pull Request. Er
ist nie ein erforderlicher Check, kann also keinen Build zum Scheitern bringen —
aber seine Befunde sind Review-Threads, und das Ruleset oben verlangt, dass diese
aufgelöst sind. Antworten reicht nicht — jemand muss den Thread als aufgelöst
markieren, bevor der Merge-Button zurückkommt. Siehe
[code-review.md](code-review.md).

Die Qualitätshälfte von CodeQL eröffnet Threads unter denselben Bedingungen, als
`github-code-quality[bot]`. Sie lässt sich nicht nach Regel oder Pfad filtern —
der einzige Schalter ist aus, für eine ganze Sprache, was kein lohnender Tausch
ist — deshalb listet
[code-review.md](code-review.md#codeql-and-the-findings-that-block-a-merge)
stattdessen die bereits entschiedenen Befunde auf, und einen davon aufzulösen
kostet einen Klick statt eines Aufsatzes.

## Zusammenfassung { #recap }

- **Ein langlebiger Branch.** Branch, Pull Request, Squash beim Merge.
- Ein Push bricht den laufenden Lauf ab, ein erneuter Push ist also auch die
  Entscheidung, sich für die vorige Antwort nicht mehr zu interessieren.
- Die CI führt **weniger Jobs aus als `make check`** — ein erforderlicher Check
  mit `skipped` ist ein Pass, kein Problem.
- `main` ist vom Abbruch ausgenommen, und die Art der Ausnahme ist eine
  Concurrency-Gruppe, die `github.run_id` trägt — eindeutig pro Lauf, sodass kein
  `main`-Lauf einen anderen abbricht.
