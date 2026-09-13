---
source_sha: ff4961c85112
---

# Über AgenticOS { #about-agenticos }

AgenticOS ist das Betriebssystem für die KI-Agents eines Unternehmens: selbst
gehostet, Open Source, mandantenfähig.

Es gibt das wegen einer Beobachtung. Die meisten Agent-Frameworks geben Ihnen eine
Bibliothek — Sie schreiben Python, Sie deployen es, und jede Änderung am Verhalten
eines Agents ist ein Pull Request, ein Review und ein Release. Das ist genau
richtig für ein Produktfeature und genau falsch für die vierzig kleinen Agents,
die ein Unternehmen tatsächlich will, denn wer weiß, was der Agent sagen soll,
ist nicht die Person mit Commit-Zugang.

Hier gilt also: **Code definiert, und Konfiguration setzt zusammen.** Ein Fachteam
baut Agents im Browser zusammen — Instruktionen, ein Modell, eine Auswahl an
Capabilities, ein Budget — und Entwickler erweitern das, was sich zusammensetzen
lässt, in typisiertem Python. Konfiguration erreicht immer nur das, was Code
registriert hat, und genau das macht einen No-Code-Builder sicher genug, um ihn
jemandem in die Hand zu geben, der kein Entwickler ist.

Der Spec ist ein Dokument, also bekommt er beim Veröffentlichen eine Version und
lässt sich als YAML in Ihr eigenes git-Repository exportieren. Die Obergrenze ist
nicht dieses Dokument: Sie ist das, was Ihre Entwickler in die Registry legen.

## Was etwas zu einem Betriebssystem für Agents macht { #what-makes-something-an-operating-system-for-agents }

Das Wort wird in dieser Kategorie locker verwendet, und das ist ein berechtigter
Vorwurf. Es lohnt sich zu sagen, was es bedeuten muss, denn ein Betriebssystem
ist keine Stimmung: Es sind sieben Aufgaben, und ein Produkt erledigt sie oder
eben nicht.

Nehmen Sie das als Test. Wenden Sie ihn auf AgenticOS an, und wenden Sie ihn auf
alles an, womit Sie es vergleichen.

| Ein Betriebssystem… | …und für Agents heißt das |
|---|---|
| **Führt Prozesse aus und isoliert sie** | Ein Run ist der Prozess. Er startet, er lässt sich stoppen, er ist von anderen Mandanten isoliert, und er hinterlässt einen Eintrag über das, was er getan hat |
| **Erzwingt Ressourcengrenzen** — Quota, cgroups | Ein Budget, geprüft *bevor* die Arbeit erlaubt wird, statt hinterher zusammengezählt, auf einer Einheit, für die jemand verantwortlich ist |
| **Kontrolliert Zugriffe** — Nutzer, Permissions, `sudo` | Permissions, an der Aufrufstelle geprüft, keine Rollennamen; und ein Eskalationsweg für alles, was auf die Außenwelt wirkt |
| **Erreicht Hardware über Treiber** | Eine Schnittstelle zu vielen Modell-Providern und vielen Tool-Servern, sodass der Austausch von beidem nicht neu schreibt, was sie nutzt |
| **Führt ein Dateisystem** | Ein dauerhafter Ort für das eigene Wissen der Organisation, mit den daran hängenden Zugriffsregeln |
| **Gibt vielen Schnittstellen eine Shell** | Derselbe Agent, der auf jeder Oberfläche über einen Ausführungspfad antwortet, statt dass jede Oberfläche sich ihren eigenen zusammenbaut |
| **Schreibt ein Audit-Log** | Wer was wann ausgeführt hat, was es gekostet hat, wer es freigegeben hat — geschrieben, ob der Run erfolgreich war oder nicht |

### Wie AgenticOS jede davon beantwortet { #how-agenticos-answers-each-one }

| | |
|---|---|
| Prozesse | Runs sind erstklassig: Historie, Kosten, Status, und Mandantentrennung, die Datenbank-Constraints erzwingen statt Service-Code |
| Ressourcengrenzen | [Monatsbudgets](../governance.md) pro Agent, geprüft vor jeder Modellanfrage. Ein Run, der fehlschlägt, verzeichnet trotzdem, was er gekostet hat, denn ein Budget, das Fehlschläge ignoriert, ist kein Budget |
| Zugriffskontrolle | Ein [Permission-Katalog](../permissions.md) in Code, Rollen daraus zusammengesetzt, Grants pro Ressource, die ausweiten und nie einengen. `approval: required` ist das `sudo` — der Run parkt und wartet auf einen Menschen |
| Treiber | [27 Modell-Provider](../models.md) hinter einem Modellprofil und [jeder MCP-Server per URL](../mcp.md). Ändern Sie das Profil, und jeder Agent, der es nutzt, zieht mit, ohne dass einer neu veröffentlicht wird |
| Dateisystem | [Collections, Skills und Context](../file-processing.md) in Ihrem eigenen Postgres, Embeddings mit einem Schlüssel pro Organisation |
| Shell | Ein Runner hinter [Web-Chat, der API, Slack, Telegram, einem Widget, einer gehosteten Seite und einem Zeitplan](../channels.md) |
| Audit-Log | Jeder Run, jede Approval-Entscheidung, jede Schlüsselrotation — mit Werten, nie mit Zeilen, und nie mit einem Schlüssel im Klartext |

!!! info "Warum der Test so geschrieben ist, dass er auch auf uns angewandt wird"

    Eine Checkliste, die immer nur eine Antwort hervorbringt, ist Marketing.
    Diese hier ist gegen jedes Produkt der Kategorie wirklich anwendbar, und so
    möchten wir beurteilt werden — einschließlich der Zeile unten, wo die Antwort
    noch nicht gut genug ist.

### Wo dieses hier nicht fertig ist { #where-this-one-is-not-finished }

Monitoring ist die schwächste der sieben. Jeder Run verzeichnet eine
`logfire_trace_id`, und noch liest sie niemand, also bekommen Sie heute
Run-Historie, Kosten und Status statt eines Trends, auf den Sie reagieren können.
Es steht als R11 auf
[der Roadmap](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md).

Zwei weitere Lücken, die man vor einem Vergleich kennen sollte: Es gibt noch kein
SAML und kein SCIM — die Anmeldung läuft über JWT, API-Schlüssel, Google OAuth und
Magic Links — und es gibt keine Evaluations-Umgebung, also testet man einen Agent
vor dem Veröffentlichen von Hand.

## Für wen es ist { #who-it-is-for }

Für ein Unternehmen, das mehr als drei Agents will und sie gesteuert haben will.

- **Wer den Agent baut**, schreibt kein Python. Diese Person schreibt
  Instruktionen, schaltet Capabilities ein, zeigt auf eine Wissens-Collection und
  setzt ein Budget.
- **Wer für die Rechnung verantwortlich ist**, bekommt Budgets, die einen Run
  stoppen, Approvals für alles mit Nebenwirkung und eine Audit-Spur.
- **Der Entwickler** bekommt einen Spec, der als YAML in sein eigenes
  git-Repository exportiert, eine HTTP-API und eine Plattform, deren Quellcode er
  lesen kann.

## Was es absichtlich nicht ist { #what-it-deliberately-is-not }

**Es ist kein Framework, um einen einzelnen Agent zu schreiben.**
[Pydantic AI](https://ai.pydantic.dev) ist die Laufzeit darunter, und wenn Sie
einen einzelnen Agent in Python als Teil eines Produkts wollen, nutzen Sie sie
direkt.

Das heißt nicht, dass dies für Code verschlossen wäre. Es zu erweitern *ist*
Python — eine [Capability](../howto/add-capability.md) ist typisierter,
getesteter Code in diesem Repository, und ein Connector, ein Channel oder eine
Ingestion-Strategie ist dasselbe Muster. Der Unterschied ist, dass Sie das Tool
einmal schreiben und danach alle damit zusammensetzen.

**Es ist kein gehosteter Dienst.** Nichts telefoniert nach Hause. Modellpreise
stammen aus einem Snapshot, der dem Release beiliegt, und die einzigen ausgehenden
Anfragen sind die, die Ihre Agents stellen. Ein Betriebssystem installiert man auf
der eigenen Maschine; niemand mietet einen Kernel pro Arbeitsplatz.

**Es ist kein Ort, um Integrationen zu schreiben.** Eine Integration mit einem
SaaS-Produkt ist eine [MCP-Verbindung](../mcp.md), kein Python-Modul, das jemand
in diesem Repository gegen die API dieses Produkts pflegt. Deshalb ist der
Capability-Katalog kurz und bleibt es.

## Der Teil, der tatsächlich das Produkt ist { #the-part-that-is-actually-the-product }

Der meiste Wert steckt hier in dem, was die Plattform **verweigert**: ein
mandantenübergreifender Lesezugriff, ein nicht gewährter Scope, eine
Budgetüberschreitung, eine zweite Entscheidung über eine entschiedene Approval,
ein Spec, der beim Veröffentlichen die Validierung nicht besteht.

Der glückliche Pfad — ein Modellaufruf mit ein paar angehängten Tools — ist die
leichte Hälfte, und ein Dutzend Bibliotheken macht ihn gut. Die Verweigerungen
sind die Hälfte, die entscheidet, ob Sie einen Agent jemandem übergeben können,
der nicht Sie ist.

## Wann man etwas anderes nimmt { #when-to-use-something-else }

Vier der sieben Aufgaben sind Dinge, die eine Bibliothek nie für Sie erledigen
wird, und drei davon sind Dinge, die eine gehostete Plattform erledigt, ohne Ihnen
die Maschine zu geben. Keines von beidem ist ein Vorwurf; es sind verschiedene
Produkte.

[Welches man wann nimmt →](comparison.md)

## Woher es kommt { #where-it-came-from }

Erzeugt aus dem
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
weshalb "die Plattformschicht" und "aus dem Template geerbt" Unterscheidungen
sind, die in der Dokumentation für Beitragende auftauchen. Die Plattformschicht —
alles, was AgenticOS obendrauf legt — wird in CI bei 100 % Testabdeckung gehalten.
Die geerbten Subsysteme werden berichtet, halten den Build aber nicht auf, denn
Code, den wir nicht entworfen haben, an dieselbe Latte zu hängen, kauft eine
Coverage-Zahl statt Vertrauen.

Die sechs Entscheidungen hinter seiner Form — warum ein Agent eine Datei ist,
warum sich das Spec-Format nur vorwärts bewegt, warum die Validierung beim
Veröffentlichen passiert — sind für Beitragende in
[`docs/about/design.md`](https://github.com/vstorm-co/agenticos/blob/main/docs/about/design.md)
aufgeschrieben.

## Wer es baut { #who-builds-it }

[Vstorm](https://vstorm.co), und wer immer einen Pull Request schickt.

## Fazit { #recap }

- **Code definiert, Konfiguration setzt zusammen** — ein Fachteam baut Agents
  zusammen, Entwickler erweitern das, was sich zusammensetzen lässt, und keiner
  wartet auf den anderen.
- "Betriebssystem" ist hier eine **Spezifikation, kein Etikett** — sieben
  Aufgaben, jede mit einem Mechanismus dahinter.
- Der Test ist dafür gedacht, **auch auf andere Produkte angewandt zu werden**,
  und auf dieses: Monitoring ist die Zeile, in der die ehrliche Antwort "noch
  nicht" lautet.
- Das Produkt besteht größtenteils aus den **Verweigerungen**, nicht aus dem
  glücklichen Pfad.
- Es läuft auf **Ihrer Maschine**, weil ein Betriebssystem genau das tut.

[Wann man etwas anderes nimmt →](comparison.md) · [Installieren →](../install.md)
