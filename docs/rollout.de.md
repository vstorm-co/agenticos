---
source_sha: 5eec786139c5
---

# Die Einführung { #rolling-it-out }

Diese Seite ist für alle, die für die Entscheidung verantwortlich sind und nicht
für die Installation: was sich in einem Unternehmen ändert, das dies betreibt,
wer was macht, was es kostet und die drei Arten, wie es üblicherweise schiefgeht.

Nichts hier braucht ein Terminal. [Die Installation](install.md) ist die andere
Hälfte.

## Was es ersetzt { #what-it-replaces }

Keinen Menschen. **Einen Rückstau.**

Jedes Unternehmen hat eine Schlange kleiner Automatisierungen, die nie gebaut
werden: die Antwort auf dieselbe Kundenfrage, die Wochenübersicht, die jemand von
Hand zusammenstellt, das aus einer E-Mail befüllte Formular, die interne Frage,
die beantwortet wird, indem man die eine Person stört, die es weiß.

Jede ist zu klein, um ein Projekt zu rechtfertigen, und es gibt vierzig davon.
Sie bleiben liegen, weil der einzige Weg, eine zu bauen, bisher ein Entwickler,
ein Repository und ein Release war — und die Zeit eines Entwicklers ist am
Produkt besser aufgehoben.

AgenticOS macht aus jeder davon ein Dokument, das jemand schreibt, statt Software,
die jemand ausliefert.

## Wer was macht { #who-does-what }

Drei Rollen, und die Aufteilung zählt mehr als das Werkzeug.

| | Wer das ist | Wofür sie zuständig sind |
|---|---|---|
| **Der Builder** | Die Person, die die Antwort kennt — Support-Leitung, Ops-Manager, Analyst | Schreibt die Instruktionen des Agents, wählt, was er darf, zeigt ihm die richtigen Dokumente, testet ihn, veröffentlicht ihn |
| **Der Owner** | Wer für die Ausgaben und das Verhalten verantwortlich ist | Setzt Budgets, entscheidet, welche Aktionen eine menschliche Approval brauchen, liest die Audit-Spur |
| **Der Entwickler** | Eine Person, nach der ersten Woche in Teilzeit | Führt die Installation durch, verbindet die Systeme, fügt eine Capability hinzu, wenn wirklich etwas Neues gebraucht wird |

Der Sinn der Aufteilung ist, dass der Builder nicht auf den Entwickler warten
muss. Wenn jede Änderung an dem, was ein Agent sagt, über die Person mit
Commit-Zugang laufen muss, haben Sie eine langsamere Fassung dessen gekauft, was
Sie schon hatten.

!!! info "Die Last des Entwicklers sinkt nach dem Aufsetzen"

    Ein System anzubinden ist [ein MCP-Server per URL](mcp.md), kein Connector,
    den jemand schreibt. Verhalten zu ändern ist eine Bearbeitung und ein
    Veröffentlichen, kein Release. In den meisten Wochen sind die
    Entwicklungskosten null.

## Realistische erste neunzig Tage { #a-realistic-first-ninety-days }

| | | Wie "fertig" aussieht |
|---|---|---|
| **Woche 1** | Installieren, einen Modell-Provider anbinden, drei Personen einladen | Ein Agent beantwortet eine echte Frage aus einem echten Dokument |
| **Wochen 2–4** | Ein Agent, ein Team, eine wiederkehrende Aufgabe. Budget absichtlich niedrig gesetzt | Das Team nutzt ihn, ohne dazu aufgefordert zu werden |
| **Wochen 5–8** | Bringen Sie ihn dorthin, wo die Arbeit ohnehin passiert — [Slack, ein Widget, E-Mail-getriebene Routines](channels.md) | Jemand außerhalb des Pilotteams nutzt ihn ohne Schulung |
| **Wochen 9–12** | Zweiter und dritter Agent, von einer anderen Person gebaut | Ein Nicht-Entwickler hat einen Agent von Anfang bis Ende veröffentlicht |

Der Meilenstein, auf den es ankommt, ist der letzte. **Ein Agent beweist die
Technik; der zweite Agent, von jemand anderem gebaut, beweist das Modell.** Wenn
jeder Agent weiterhin von derselben Person kommt, haben Sie ein Werkzeug, keine
Plattform.

## Was es kostet { #what-it-costs }

Drei Posten, und nur einer davon überrascht.

- **Infrastruktur.** Postgres, Redis und ein Container-Host. Eine kleine VM trägt
  einen Piloten; das ist der günstigste Posten und bleibt es.
- **Modellnutzung.** Pro Run und pro Agent gemessen und vor der Rechnung
  sichtbar. Das ist der Posten, den man im Auge behält, und der, für den es
  [Budgets](governance.md#budgets) gibt — geprüft *vor* jeder Modellanfrage,
  sodass ein Agent über Budget anhält, statt zu viel auszugeben.
- **Menschen.** Ein Entwickler für das Aufsetzen, danach in Teilzeit. Ein
  Builder pro Team, als Teil seiner bisherigen Aufgabe statt als neue.

Es gibt keine Lizenz pro Arbeitsplatz, weil es keine Lizenz gibt: Es ist
Apache-2.0, und Sie betreiben es. Das ändert die Form der Entscheidung — der elfte
Agent und der hundertste Nutzer kosten nichts außer den Token, die sie
verbrauchen.

!!! tip "Setzen Sie das erste Budget niedriger, als Sie denken"

    Ein Budget, das einen Run stoppt, lehrt viel besser als eine Rechnung. Fangen
    Sie mit einer Zahl an, die erreicht wird, schauen Sie, wohin es geht, und
    erhöhen Sie sie dann bewusst. [Ein Modell wählen](choosing-models.md)
    behandelt, was die Rechnung wirklich treibt.

## Was Ihre Sicherheitsprüfung fragen wird { #what-your-security-review-will-ask }

Die Fragen kommen in einer vorhersehbaren Reihenfolge, und die Antworten sind der
Grund, warum diese Architektur gewählt wurde.

| Sie fragen | Die Antwort |
|---|---|
| Wohin gehen unsere Daten? | In Ihr Postgres, auf Ihrer Infrastruktur. Nichts telefoniert nach Hause. Die einzigen ausgehenden Aufrufe gehen an Modell-Provider, die Sie konfiguriert haben — und [gar keine](choosing-models.md#closed-models-or-open-weights), wenn Sie das Modell selbst betreiben |
| Wer kann was sehen? | [Drei Schichten](permissions.md): ein Deployment-Admin, eine Organisationsrolle und Grants pro Ressource. Ein Bedienelement, das jemand nicht nutzen darf, wird nicht gerendert — nicht gerendert und dann abgelehnt |
| Was hindert einen Agent daran, Schaden anzurichten? | Nichts mit Nebenwirkung läuft ohne [Approval](governance.md#approvals), wenn Sie sie verlangen, und eine Approval wird genau einmal entschieden |
| Können wir beweisen, was passiert ist? | Jeder Run, jede Approval, jede Schlüsselrotation steht in der [Audit-Spur](governance.md#audit) — auch fehlgeschlagene Runs |
| Wo liegen die Zugangsdaten? | In [einem Vault](secrets.md), pro Organisation versiegelt. Keine API-Antwort, keine Logzeile und kein Audit-Eintrag trägt je einen Schlüssel im Klartext |
| Können wir den Code lesen? | Ja. Damit endet das Gespräch meistens |

## Drei Arten, wie das schiefgeht { #three-ways-this-goes-wrong }

Jede wurde schon gesehen; jede ist vermeidbar.

**Eine Person baut jeden Agent.** Die Plattform wird zur Warteschlange dieser
Person, und Sie sind wieder da, wo Sie angefangen haben. Abhilfe: Machen Sie den
zweiten Agent zur Sache von jemand anderem und setzen Sie sich dazu, während
diese Person ihn baut.

**Der erste Agent ist zu ehrgeizig.** Ein Agent, der vier Systeme berührt und
Entscheidungen trifft, scheitert auf eine Weise, die niemand debuggen kann, und
der Fehlschlag bleibt als "KI funktioniert hier nicht" in Erinnerung. Abhilfe:
Der erste Agent beantwortet Fragen aus Dokumenten. Er ist langweilig, er
funktioniert, und er verdient sich den zweiten.

**Niemand hat ein Budget oder eine Approval gesetzt.** Der Run, der jemanden
überrascht, ist der ohne Obergrenze und ohne Gate, und er kostet mehr Vertrauen
als Geld. Abhilfe: Setzen Sie beides am ersten Tag, bei jedem Agent, bevor
irgendwer sonst Zugang hat.

## Was zu messen ist { #what-to-measure }

Widerstehen Sie dem Zählen von Unterhaltungen. Messen Sie die vier Dinge, die
entscheiden, ob sich das gelohnt hat:

| | Warum das die richtige Zahl ist |
|---|---|
| **Ohne Menschen beantwortete Fragen** | Das eigentliche Ergebnis. Alles andere ist nur ein Stellvertreter dafür |
| **Kosten pro erledigter Aufgabe** | Sinken, während Sie Retrieval tunen und eine Modellstufe tiefer gehen — und sie sind pro Run sichtbar, nicht pro Monat |
| **Wie viele Personen einen Agent veröffentlicht haben** | Die Adoptionszahl, die vorhersagt, ob das seinen Fürsprecher überlebt |
| **Wartende Approvals** | Eine wachsende Schlange heißt, das Gate sitzt an der falschen Aktion, oder dem Agent wird noch nicht vertraut. Beides lohnt sich früh zu wissen |

## Hilfe bekommen { #getting-help }

Sie können das vollständig selbst betreiben. Es ist Apache-2.0, die Dokumentation
ist die ganze Geschichte statt eines Häppchens, und nichts hier steht hinter
einem Supportvertrag.

Zwei Orte zum Fragen, wenn etwas nicht abgedeckt ist:
[GitHub Issues und Discussions](https://github.com/vstorm-co/agenticos) für das
Projekt und [Ressourcen](resources/index.md) für die Leitfäden für Beitragende.

**[Vstorm](https://vstorm.co) baut AgenticOS und führt es auch ein.** Das ist
gut zu wissen, wenn die Arbeit, die vor Ihnen liegt, eine von diesen ist:

| | |
|---|---|
| **Es in Ihrer Infrastruktur in den Produktivbetrieb bringen** | Ihre Cloud, Ihr Rechenzentrum oder air-gapped, verdrahtet mit den Systemen, die Sie schon betreiben |
| **Lokale Modelle aufsetzen** | Damit Inferenz das Haus nie verlässt — die Hardware, die Laufzeit und die Profile, die darauf zeigen |
| **Die Plattform an einen Prozess anpassen** | Eine Capability, die noch niemand geschrieben hat, ein Ingestion-Pfad für Ihre Dokumentform, ein Channel, den Sie nutzen und sonst niemand |
| **Die ersten Agents mit Ihrem Team bauen** | Eingebettet, damit der zweite ihrer ist statt unserer |

Nichts davon ist eine Lizenz — die Plattform ist so oder so dieselbe Open Source,
und ein Deployment, das jemand anderes gemacht hat, bleibt Ihres zum Lesen,
Ändern und Weiterbetreiben.

[Sprechen Sie mit uns →](https://vstorm.co/contact-us/)

## Fazit { #recap }

- Es ersetzt **einen Rückstau kleiner Automatisierungen**, keinen Menschen.
- Die Aufteilung, die es funktionieren lässt: **der Builder wartet nicht auf den
  Entwickler.**
- Der Meilenstein, auf den es ankommt, ist der **zweite Agent, von jemand anderem
  gebaut.**
- **Keine Lizenz pro Arbeitsplatz** — der elfte Agent kostet nur die Token, die
  er verbraucht.
- Setzen Sie **am ersten Tag ein Budget und eine Approval**, bei jedem Agent,
  bevor irgendwer sonst Zugang hat.

[Installieren →](install.md) · [Den ersten Agent bauen →](first-agent.md) ·
[Was es verweigert →](about/index.md)
