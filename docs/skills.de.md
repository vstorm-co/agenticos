---
source_sha: "65dcefce4721"
---

# Skills { #skills }

Ein Klick auf einen Skill im Katalog öffnet Anweisungen, Beschreibung und Dateien in einem Dialog, ohne Suche, Filter oder Listenseite zu verlieren. **Vollständige Ansicht öffnen**, neben **Teilen** in der Fußleiste des Dialogs, öffnet den Tab Inhalt auf einer eigenen Seite; Agenten und Verlauf bleiben dort erreichbar. Beim Verlassen ungespeicherter Änderungen wird nachgefragt. Ohne Feedback zeigt Improve den nächsten Schritt statt eines nicht ausführbaren Kostenformulars.


Ein Skill ist Wissen, das einmal geschrieben und an viele Agents gebunden wird:
wie Rückerstattungen behandelt werden, was der Hausstil ist, welche Prüfungen ein
Bericht bestehen muss, bevor er herausgeht.

Ersetzt wird damit ein Instruktionsfeld, das immer weiter wächst.

Zwanzig Verfahren in einem Prompt bedeuten, dass jeder Run für alle zwanzig
bezahlt, und das einundzwanzigste schiebt die Unterhaltung aus dem Fenster.
Skills drehen das um:

```mermaid
flowchart LR
    A["available skills<br/><i>names + one-line descriptions only</i>"] --> B{is one relevant?}
    B -->|no| Z["no body loaded"]
    B -->|yes| C["read_skill - the body"]
    C --> D{does the body<br/>point at a file?}
    D -->|no| Z2[answer]
    D -->|yes| E["read_skill_resource - one file beside it"]
    E --> Z2
```

Zwanzig Skills kosten ungefähr zwanzig _Beschreibungen_ statt zwanzig
_Verfahren_.

!!! note "Discovery ist günstig, nicht kostenlos"

    Jeder gebundene Skill steht mit Name und einzeiliger Beschreibung im
    Capability-Katalog, den das Modell in jeder Runde liest — einen Skill zu binden
    kostet also Tokens, ganz gleich ob das Modell ihn jemals öffnet.

    Es ist eine Zeile pro Skill gegen einen Textkörper pro Skill, und deshalb geht
    die Rechnung auf. Es ist kein Grund, einen unbegrenzten Katalog zu binden.

Die andere Hälfte des Punktes ist, **wer sie schreibt**. Ein Skill ist eine Zeile
in der Datenbank, in der UI bearbeitbar, sodass eine Support-Leitung die
Rückerstattungsregel an einem Dienstagnachmittag korrigieren kann. Kein Deploy,
kein Pull Request, kein Entwickler.

!!! info "Skill, Context-Datei oder Knowledge-Collection?"

    Ein **Skill** ist ein Verfahren, das das Modell lädt, wenn es entscheidet, dass
    die Aufgabe angekommen ist. Eine [Context-Datei](context.md) ist ständiges
    Wissen — kurz, immer relevant, eingefügt oder bei Bedarf gelesen. Eine
    [Knowledge-Collection](file-processing.md) ist ein Korpus, der zu groß zum
    Lesen ist und über Suche erreicht wird.

Im Agent Builder öffnet **Skills → New skill** die Erstellung direkt im Fähigkeitspanel. Beim Speichern entsteht ein Bibliothekseintrag, der dem aktuellen Entwurf zugeordnet wird; zugleich wird die Fähigkeit Skills aktiviert. Das Veröffentlichen bleibt ein eigener Schritt. Die Aktion erfordert Bearbeitungsrechte für den Agenten und Skills.

## Die Form { #the-shape }

```markdown
---
name: refund-policy
description: When a refund is given without asking, when it needs approval, and how to say no.
category: support
---

# Refunds

Most refund questions are decided by the order date and one exception. Check
those before escalating anything.

Die Seite **Skills** zeigt auf jeder Karte den Anfang des Inhalts — ohne Front
Matter, ein paar Zeilen — und dahinter ein Blatt für jede Datei, die der Skill
mitbringt. `GET /api/v1/skills` liefert diesen Anfang als `excerpt`; den Inhalt
selbst lädt erst das Öffnen des Skills.

## Decide without asking

...
```

!!! tip "`description` ist das Feld, das darüber entscheidet, ob der Skill je geladen wird"

    Es ist der einzige Teil, den das Modell umsonst sieht. Schreiben Sie es als
    **wann man danach greift**, nicht als Titel.

Ein Skill kann **Ressourcen** mitbringen — weitere Dateien daneben, die bei
Bedarf geladen werden. `refund-policy` liefert eine `exceptions.md` mit, und der
Textkörper sagt, wann sie zu konsultieren ist.

Das ist dieselbe schrittweise Offenlegung eine Ebene tiefer: Details, die nur
manche Unterhaltungen brauchen, müssen nicht in dem Textkörper stehen, den jede
relevante Unterhaltung lädt.

`category` ist einer von zwanzig Vorschlägen (`support`, `engineering`,
`finance`, `legal`, `security`, `marketing`, …) und steuert den Filter in der
Skill-Liste. Auf das, was der Agent sieht, hat sie keine Wirkung — das Modell
wählt über `description`, nie über die Kategorie.

Lange Textressourcen werden seitenweise gelesen, damit nicht jedes Modell-Request das ganze Handbuch enthält: standardmäßig 8.000, höchstens 20.000 Zeichen. Übergib `args` mit `offset` und `limit` an `read_skill_resource`; die Antwort nennt den nächsten Offset. Lies nur relevante Bereiche und verwende bereits geladenes Material erneut.

## Wie ein Agent einen liest { #how-an-agent-reads-one }

Über die [Capability `skills`](reference/capabilities.md#skills). Jeder Skill, den
ein Agent bekommt, wird zu einer **eigenen Capability** — dem Modell mit Name und
Beschreibung aufgelistet und bei Bedarf geöffnet:

| Wie | Was es tut |
| --- | --- |
| Verfügbare Skills | Namen und einzeilige Beschreibungen von allem, was an diesen Agent gebunden ist |
| `read_skill` | Der vollständige Textkörper eines Skills, in die Unterhaltung geholt |
| `read_skill_resource` | Eine Datei neben einem Skill |

`read_skill` gibt dem nativen verzögerten Loader des Frameworks Skill-spezifische
Namen. Freigaberichtlinien behalten den stabilen Schlüssel `load_capability`,
damit veröffentlichte Specs und ausstehende Freigaben weiter funktionieren. Der
alte Freigabeschlüssel `load_skill` wird weiterhin darauf migriert. Es gibt kein
separates Auflistungstool. `read_skill_resource` liest Begleitdateien erst nach
dem Öffnen des Skills.

Ein Spec bindet Skills über ihre Id in `skill_ids`, sodass ein Agent genau die
sieht, die ihm gegeben wurden, und sonst nichts.

**Direkt vom Skill aus.** Jede Karte auf der Skills-Seite hat **Zu einem
Agenten hinzufügen**: Agent wählen, und der Skill landet in dessen Entwurf, mit
eingeschalteter Skills-Capability, bereit zum Veröffentlichen im Builder. Die
Karte sagt auch, welche Agents den Skill nutzen - oder dass es noch keiner tut.
Kontextdateien und Wissensdatenbanken bieten dasselbe.

**Der Name eines Skills ist die id, unter der ein Modell ihn lädt**, also hat
er die Form, in der Modelle ids schreiben: Kleinbuchstaben und Ziffern, verbunden
durch einzelne Bindestriche, etwa `refund-policy`. Die Konsole formatiert Großbuchstaben,
Leerzeichen, Satzzeichen und lateinische Akzente beim Verlassen des Feldes oder Speichern
automatisch: `Refund Policy` wird zu `refund-policy`. Die API verlangt weiterhin das
kanonische Format. Vorhandene Namen und Capability-Namen werden abgelehnt, ohne den
Entwurf zu verwerfen.

Einen Namen, den das Modell
exakt wiedergeben müsste, wie `Refund policy`, lud es stattdessen als
`refund-policy`, und zwei falsche Vermutungen beenden die Runde
([#1911](https://github.com/vstorm-co/agenticos/issues/1911)).

**Ein Skill darf nicht heißen wie eine Capability.** Jeder liegt unter seinem
eigenen Namen im selben Namensraum wie `knowledge`, `planning` und der Rest - ein
Skill namens `planning` auf einem Agent, der auch die Planning-Capability hat, ist
also ein Duplikat, das das Framework vor dem ersten Token ablehnt. Einen solchen
anzulegen wird abgewiesen, und einen Agent zu veröffentlichen, der an einen so
benannten Skill gebunden ist, ebenfalls.

Die Capability ohne gebundene Skills zu aktivieren ist nutzlos — geben Sie dem
Agent Skills, oder lassen Sie die Capability aus.

### Welche Skills eine Antwort verwendet hat { #which-skills-an-answer-used }

Einen Skill zu binden heißt nicht, dass das Modell ihn gelesen hat. Jeder Run
zeichnet die Skills auf, die er tatsächlich verwendet hat, nach der ID des Skills:
ob das Modell einen mit `read_skill` geöffnet hat und wie viele seiner
Dateien es mit `read_skill_resource` gelesen hat. Ein Run zeichnet das auf, wie
auch immer er endet, auch wenn er nach dem Öffnen des Skills fehlgeschlagen ist.
Ein Skill, den ein Delegate verwendet hat, wird beim delegierenden Run unter dem
Agent des Delegates aufgezeichnet, weil die bewertete Antwort die dieses Runs ist.

Ein Tool-Aufruf, der einen Pfad im Workspace-Ordner eines Skills nennt, etwa
`cat /workspace/skills/refund-policy/SKILL.md`, zählt getrennt als
wahrscheinliche Verwendung. Den Ordner aufzulisten zählt nicht. Ein Pfad, den eine
Shell zusammensetzt, ein Glob über mehrere Skills oder ein Skript, das die Datei
selbst liest, wird nicht erkannt.

`GET /api/v1/skills/{id}/usage?days=30` liefert pro Agent, wie viele Runs den
Skill in diesem Zeitraum verwendet haben, mit der Version, die jeder bekam, und
der Zahl für jeden Tag des Zeitraums in UTC, auch wenn sie null ist. Runs
von Evals und vom Testbereich des Builders werden nicht gezählt. Die Zahlen werden
aus Runs gelesen und brauchen daher `runs:view`; ein Agent, den der Aufrufer nicht
sehen darf, wird gezählt, aber nie genannt.

Runs aus der Zeit vor dieser Aufzeichnung melden „Verwendung unbekannt“, und das
ist nicht dasselbe wie „nicht verwendet“. Wird ein Skill verbessert, stammen seine
Belege nur aus Runs, die ihn verwendet haben; negativ bewertete oder
fehlgeschlagene Runs, die ihn verwendet haben könnten, zählen getrennt als
unbekannt.

## In einem Workspace ist ein Skill auch Dateien { #in-a-workspace-a-skill-is-also-files }

Ein Agent, der sowohl Skills als auch einen
[Workspace](reference/capabilities.md#files-shell) hat, bekommt jeden Skill
zusätzlich dort hineingeschrieben:

```
/workspace/skills/<name>/SKILL.md      the body, with its name and description
/workspace/skills/<name>/<resource>    each resource, beside it
```

Das ist es, was das Skript eines Skills nützlich macht. Ein Skill, dessen
Ressource `reconcile.py` ist, wurde dem Modell bisher als Text übergeben, den es
zitieren, aber nicht ausführen konnte, während derselbe Agent `execute` einen
einzigen Tool-Aufruf entfernt hatte. Auf der Platte läuft es.

!!! note "Es gibt kein `run_skill_script`"

    Das `execute` des Sandbox trägt die Berechtigungsregeln des Workspace und die
    Obergrenzen des Betreibers bereits mit sich. Ein zweiter Weg, Dinge
    auszuführen, wäre ein zweiter Satz Regeln, den man falsch machen kann.

## Ein Agent kann eine Änderung vorschlagen; vornehmen tut sie ein Mensch { #an-agent-can-propose-a-change-a-person-makes-it }

Diese Dateien sind beschreibbar, und was der Agent schreibt, wird **nicht**
übernommen.

Ein Skill ist eine Anweisung, der jeder daran gebundene Agent in jedem Run folgt.
Ein Agent, der einen direkt bearbeiten könnte, könnte umschreiben, was ein
anderer Agent tut, innerhalb einer Unterhaltung, die niemand prüft, und der
nächste Leser hätte keine Möglichkeit, eine durchdachte Verbesserung von einer
halluzinierten zu unterscheiden.

Ein Schreibvorgang wird deshalb zu einem **Vorschlag**, und dieser erscheint über
der Liste auf der Seite Skills für jeden, der diesen Skill bearbeiten darf. Ein
Vorschlag für einen neuen Skill erscheint für jeden, der `skills:edit` hält.
Niemand sonst kann ihn auflisten oder öffnen:

- **Check on agents** führt die Änderung auf jedem Agent der Linie aus, für die
  sie geschrieben wurde, und angewendet wird sie - als nächste Version dieser
  Linie, die deren Agents beim nächsten Run lesen - aus dem Ergebnis dieser
  Prüfung. Siehe
  [Eine Änderung auf jedem Agent prüfen](#checking-a-change-on-every-agent).
- **Discard** behält den Eintrag. Ein Agent, der wiederholt dieselbe Änderung
  vorschlägt, sagt jemandem etwas über den Skill, und eine gelöschte Zeile macht
  das unsichtbar.

!!! warning "Eine Entscheidung über einen Vorschlag ist endgültig"

    Zweimal anzuwenden würde eine zweite Version eines bereits gespeicherten
    Textkörpers speichern, und etwas Angewendetes zu verwerfen würde einem Leser
    sagen, es sei nie gelandet.

Der Vorschlag trägt den **ganzen Textkörper** statt eines Diffs, sodass jemand,
der Wochen später prüft, zwei vollständige Versionen vergleicht, statt einen
Patch dort anzuwenden, wohin er nie gehörte.

Zwei Dinge werden abgelehnt statt geraten: ein vom Agent angelegtes Verzeichnis
ohne `SKILL.md` darin, und eines, dessen Frontmatter er verstümmelt hat. Und eine
_gelöschte_ Ressource ist bewusst keine Änderung, denn eine Datei, die das Modell
nie angefasst hat, und eine, die es löschen wollte, hinterlassen dieselbe
Abwesenheit.

Drei Runden einer Unterhaltung, die denselben Skill verfeinern, hinterlassen
**einen** Vorschlag, nicht drei. Wer dreimal dieselbe Frage gestellt bekommt, hat
mehr Arbeit bekommen statt mehr Information.
Vorschläge aus dem Workspace haben dieselben Metadatenlimits wie gespeicherte
Skills: 1–64 Zeichen für den Namen und höchstens 500 für die Beschreibung.
Änderungen außerhalb dieser Grenzen werden mit einer Warnung übersprungen;
die ursprünglichen Dateien bleiben erhalten. Ein Savepoint schützt den Lauf:
ein abgelehnter Vorschlag verhindert weder Status- noch Kostenaufzeichnung.

Eine Änderung hält fest, für welche Version des Skills sie geschrieben wurde:
bei einem Run die Version, die dieser Run bekommen hat, und ein späterer Turn,
der die Änderung überschreibt, hält seine eigene fest. Apply lehnt sie ab, sobald
jemand den Skill seitdem geändert hat, sodass eine Bearbeitung, die während des
Wartens entstand, nicht überschrieben wird. Vergleiche beide und bearbeite den
Skill von Hand, oder frage erneut.

Der [Authoring-Assistent](authoring.md#skills) schlägt Skill-Änderungen auf
dieselbe Weise vor, mit seiner Begründung und den Runs, auf die sie sich stützt,
und das Anwenden lehnt sie auf dieselbe Weise ab.

Jede Änderung sagt, welche veröffentlichten Agent-Versionen den Skill lesen,
welche Eval-Suites ihr Anwenden in die Warteschlange stellt und welche Wächter
sie erst bei der nächsten Promotion prüfen. Das Anwenden benachrichtigt die
Besitzer dieser Agents. Eine Entscheidung nennt die Version der Änderung, die Sie
gelesen haben: Eine seitdem umgeschriebene Änderung - durch eine spätere Runde
oder eine neue Anfrage - wird mit „The proposal changed since you opened it“
abgelehnt, und von zwei gleichzeitig getroffenen Entscheidungen zählt nur eine.
Ein Skill, den der Agent neu geschrieben hat, hat noch keine Agents, also legt
**Apply** ihn sofort an.

## Eine Änderung auf jedem Agent prüfen { #checking-a-change-on-every-agent }

Ein Skill wird geteilt, also wird eine Änderung auf jedem Agent beurteilt, der sie
lesen würde: auf main an den Agents, die der neuesten main-Version folgen; auf
einem Fork an den Agents dieses Forks. Agents, die auf eine ältere Version
festgesetzt sind, und die Agents anderer Forks werden nicht ausgeführt - die
Änderung erreicht sie nicht. Die veröffentlichte Version jedes Agents beantwortet
ihre Fragen zweimal, mit dem Skill, wie er ist, und mit der Änderung, und sonst
unterscheidet sich nichts.

Eine Änderung, die der Workspace eines Agents geschrieben hat, eine, die der
Assistent vorgeschlagen hat, und ein
[Bibliotheks-Update](#getting-skills-into-an-organization) eines Skills, dem
Agents folgen, gehen nur über diese Prüfung live. Wer den Skill von Hand
bearbeitet, speichert sofort eine neue Version, und diese Bearbeitung wird nicht
geprüft.

### Was sie fragt { #what-a-check-asks }

Zuerst die eigenen **Testfragen** des Skills, auf jedem Agent dieselben. Jeder
Skill hat einen Satz, begonnen auf der Skill-Seite unter **Testfragen** - aus
jüngsten Antworten, die den Skill geladen haben, oder leer - oder über die API,
`POST /api/v1/skills/{id}/test-set`, oder mit **Testfragen hinzufügen** neben einem
Agent, den [Verbessern](#improving-a-skill) nicht prüfen konnte, und bearbeitet wie
jedes andere [Dataset](datasets.md), das Datasets als das des Skills kennzeichnet.

Ein Judge bewertet den Satz und vergleicht jede Antwort mit der, die Personen
positiv bewertet haben. Aus jüngsten Antworten angelegt, wird jede Frage einmal
gestellt: Eine Antwort, die jemand bewertet hat, gewinnt gegen eine, die nur
fehlschlug, so verlangt eine Frage nie eine Antwort und verbietet sie zugleich.

Dann die eigenen Fragen des Agents:

- **Quick**, der Standard: vier Fragen aus dem Dataset des Agents - mehr, wenn die
  eigenen Held-out-Fragen des Skills für die fünf, die ein Ergebnis braucht, nicht
  reichen -
  deren neueste Antwort den Skill geladen hat - die, die die meisten Wörter mit
  den geänderten Zeilen teilen. Ein Agent ohne solche Fragen wird nur mit dem
  Satz des Skills geprüft, und seine Zeile sagt das. Ein Agent, den die Fragen
  des Skills als schlechter zeigen, wird nicht nach seinen eigenen gefragt, und
  seine Zeile sagt, dass sie nicht gestellt wurden.
- **Thorough**: das ganze Dataset des Agents, gefragt auch dann, wenn die Fragen
  des Skills den Agent als schlechter zeigten, damit seine Zeile sagt, wo die
  Änderung ihn gebrochen hat. Eine Änderung der Beschreibung
  des Skills wird immer so geprüft, denn die Beschreibung entscheidet, wann ein
  Agent den Skill überhaupt öffnet.

!!! note "Die Fragen des Skills sagen, was der Skill tun soll"

    Sie werden auf jedem Agent gleich bewertet, also fangen sie eine Änderung,
    die die eigene Regel des Skills bricht. Eine Änderung, die einem Agent wegen
    seiner eigenen Lage schadet, zeigt sich an dessen eigenen Fragen. Und eine
    gewollte Regeländerung besteht keine Frage, die noch die alte Antwort
    erwartet: Aktualisieren Sie zuerst die Testfragen.

Ein Satz von Fragen, den nichts bewerten kann oder dessen Fragen alle aus den
Unterhaltungen stammen, aus denen die Änderung gelernt hat, wird für diesen Agent
ausgelassen, und der Rest wird trotzdem gefragt. Ein Agent, für den nichts zu
fragen bleibt, ist unbekannt, mit diesem Grund. Jeder Satz zählt nur die Fragen,
die er stellt, und eine schnelle Stichprobe wählt nie eine Frage aus diesen
Unterhaltungen. Hat in einer Improve-Sitzung kein Agent eine Frage außerhalb ihrer
eigenen Belege, wird der Schritt vor dem Start abgelehnt, mit dem Dataset, dem
andere Fragen hinzuzufügen sind.

### Die Regel { #the-rule }

- Kein Agent darf **schlechter** werden, durch eine Regression, die erneutes
  Fragen bestätigt hat.
- Mindestens ein Agent muss **besser** werden.
- Ein Unterschied, den die Prüfung nicht bestätigen konnte, liegt **im
  Rauschen**: eine Warnung, keine Sperre.
- Ein Agent, der nicht geprüft werden konnte - keine Fragen, Fragen, die nichts
  bewerten kann oder die alle aus den Unterhaltungen der Änderung selbst stammen,
  kein Zugriff, kein Budget mehr, keine veröffentlichte Version, ein
  fehlgeschlagener Run, eine angehaltene Prüfung - ist **unbekannt**, und eine
  Person bestätigt das vor dem Anwenden.

Eine Prüfung, in der kein Agent geprüft werden kann, startet trotzdem und endet
sofort, mit jedem Agent unbekannt, damit eine Person das bestätigt. Der Dialog sagt das vor dem Start und bietet die Testfragen des Skills an oder die Bewertung, die seinen Fragen fehlt.
Eine Änderung
an einer Linie, die kein Agent liest, besteht sofort: Sie erreicht niemanden, und
die Prüfung sagt, dass es niemanden zu prüfen gab.

Ein Agent wird einmal beurteilt, auf den Held-out-Fragen aller seiner Stufen
zusammen: Ein Ergebnis braucht fünf davon für den Agent, nicht fünf pro Stufe,
und eine Regression, die eine Stufe allein bestätigt, zählt, was immer die andere
fand.
Jede Frage des Skill-Sets ist held-out, und eine schnelle Prüfung zieht nur die
Held-out-Fragen des Agents.

Eine Prüfung schickt ihre bestätigten Regressionen und die Antworten, die der
Judge nicht bewerten konnte, in die [Prüfwarteschlange](datasets.md#review), jede
als Antwort mit der vorgeschlagenen Änderung markiert, und nie anstelle einer
Antwort, die auf diese Frage schon wartet. Das Urteil einer Person
dort über eine Antwort, die eine Prüfung bewertet hat, beurteilt diesen Agent neu:
seine Zahlen, das Urteil der Prüfung und das Ergebnis des Improve-Versuchs, den
die Prüfung gemessen hat, folgen diesem Urteil.

Das Urteil gilt dieser einen
Antwort; das erneute Fragen behält seine eigenen Bewertungen, also bleibt eine
Regression, die es bestätigt hat. Ein Agent, den eine schnelle Prüfung nicht nach
seinen eigenen Fragen gefragt hat, weil die des Skills ihn als schlechter zeigten,
ist unbekannt, wenn diese Regression zurückgenommen wird. Eine entschiedene
Prüfung behält ihre Entscheidung, und ein Agent, den die Prüfung nicht ausführen
konnte, bleibt unbekannt.

Der Anteil jedes Agents sind seine eigenen Eval-Runs, abgerechnet über sein
Budget. Die Schätzung nennt einen Preis, wahrscheinlich und höchstens, und vor
dem Start die Agents, deren Budget ihn nicht deckt. Dieselbe Prüfung noch einmal
gestartet, während sie läuft, gibt diese Prüfung zurück, sodass sie nie doppelt
bezahlt wird. Starten braucht `runs:view`
und Bearbeitungszugriff auf den Skill. Ein Agent, den Sie nicht ausführen dürfen,
wird nicht ausgeführt, und einer, den Sie nicht sehen dürfen, ist eine Zahl, nie
ein Name.

### Wenn ein Agent schlechter wurde { #when-an-agent-got-worse }

**Check on agents** unter Skills schätzt die Prüfung, führt sie aus, zeigt das
Ergebnis jedes Agents und bietet dann genau an, was die Prüfung erlaubt. Während sie
läuft, zählt ein Balken die fertigen Agents. Danach öffnet sich jeder Agent zu dem,
was er behoben und kaputt gemacht hat, Stufe für Stufe, mit einem Link zum Run jeder
Stufe; die Seite dieses Runs sagt, dass er eine Stufe der Prüfung ist, und verweist
zurück auf sie. Sie können den Dialog schließen: Die Seite des Skills zeigt dann
**Prüfung läuft**, und **Anzeigen** öffnet die Prüfung wieder, bis Sie entscheiden.
Der Verlauf des Skills listet die Prüfungen der Linie, die neueste zuerst, mit dem,
was jede fand und was mit ihr geschah, und **Details** öffnet eine davon. Eine
Prüfung, die eine [Verbessern-Sitzung](#improving-a-skill) gestartet hat, wird in
dieser Sitzung entschieden, und Check on agents verweist dorthin.

**Zurück zum Bearbeiten** bringt den geprüften Text zurück in den Editor - den, in
dem er geschrieben wurde, oder einen neuen, geöffnet aus Anzeigen oder Details auf
der Linie der Prüfung selbst -, sodass nichts Eingetippte verloren geht, und das
Speichern wird abgelehnt, sobald die Linie eine neuere Version hat als die geprüfte;
die Prüfung eines Vorschlags bietet
stattdessen **Weiter verbessern** an, das eine Sitzung startet. Auf main kann eine
Person dennoch:

- **die Änderung anwenden und die schlechteren Agents lassen, wo sie sind** -
  jeder wird, als neue veröffentlichte Version, auf die Version festgesetzt, die
  er jetzt liest, bevor die Änderung live geht, sodass keiner sie auch nur einmal
  ausliefert. Das Festsetzen erfordert, jeden von ihnen veröffentlichen zu dürfen,
  und eine Umgebung, die auf Beförderung wartet, muss zuerst die festgesetzte
  Version übernehmen;
- **einen Fork anlegen** und main lassen, wie es ist - angeboten, was immer das
  Ergebnis ist, im Dialog der Prüfung, im Schritt Annehmen von
  [Verbessern](#improving-a-skill) oder über
  die API, `POST /api/v1/skills/{id}/checks/{check_id}/fork`. Auf den Fork wechseln
  die Agents, denen sie geholfen hat, außer Sie wählen andere mit `agent_ids`; eine
  leere Liste verschiebt keinen, und ein Agent, der den Skill über einen
  Spezialisten liest, wird in seinem Builder verschoben;
- sie **verwerfen**, nach einer Bestätigung: Über eine verworfene Prüfung lässt
  sich nicht mehr entscheiden, und ihr Eintrag bleibt im Verlauf.

Auf einem Fork bleiben nur Weiterverbessern und Verwerfen: Ein Festsetzen nennt
eine main-Version, und ein Fork beginnt nie bei einem anderen Fork. Eine Prüfung
verweigert das Anwenden, sobald die Linie eine neuere Version hat oder ein Agent
ihr zu folgen begonnen hat, denn sie hat keines von beiden gemessen.

## Versionen und Forks { #versions-and-forks }

Jede gespeicherte Änderung an einem Skill erzeugt eine neue Version, und eine
Version wird danach nie mehr geändert. Eine Version entsteht beim Bearbeiten des
Textes oder der Beschreibung, beim Hinzufügen, Ändern oder Entfernen einer Datei,
bei einer Aktualisierung aus der Bibliothek und bei einer angewendeten Änderung aus
dem Workspace eines Agents oder vom [Authoring-Assistenten](authoring.md#skills).
Eine neue Kategorie allein erzeugt keine, weil kein Agent sie liest.

**History** auf der Skill-Seite listet die Versionen, die neueste zuerst. Jede sagt,
was sie erzeugt hat (`backfill`, `created`, `edit`, `resources`, `library`,
`workspace`, `improve`, `restore`, `catch_up` oder `from_fork`) und wann, und wer sie gespeichert hat, für
alle, die die Mitglieder der Organisation sehen dürfen. Eine Version behält ihre
Dateien, wie sie waren; eine spätere Änderung an einer Datei ändert keine frühere
Version.

Ein Skill, der schon vor den Versionen existierte, hat eine Version, v1: Text und
Dateien zu dem Zeitpunkt, als die Versionierung begann. Davor wurde nichts
festgehalten.

**Restore** holt eine frühere Version als neue Version zurück. So bleibt die
History vollständig, und die neue Version sagt, aus welcher sie stammt.

Eine Bearbeitung wird gegen die Version gespeichert, die die bearbeitende Person
gelesen hat. Hat inzwischen jemand eine neuere Version gespeichert, wird die
Bearbeitung abgelehnt, statt sie zu überschreiben.

### Forks { #forks }

Ein Fork ist eine benannte Linie eines Skills, die von einer Main-Version ausgeht.
Er hat eigene Versionen und eine eigene neueste Version, sodass sich ein Skill für
manche Agents ändern kann, während main bleibt, wie es ist. Solange ein Fork keine
eigene Version hat, liefert er die Main-Version aus, von der er ausging.

- Ein Fork geht nur von main aus. Ein Fork eines Forks wird abgelehnt, der Baum hat
  also eine Ebene.
- Der Name eines Forks ist innerhalb seines Skills eindeutig, archivierte Forks
  eingeschlossen.
- Die Dateien eines Forks sind die der Version, aus der er entstand. Dateien werden
  nur auf main bearbeitet und erreichen einen Fork, wenn er aufholt.
- **Archive** sorgt dafür, dass ein Fork keine neuen Versionen mehr annimmt. Er
  behält seine Versionen und wird nie gelöscht. Ein Fork, den 30 Tage lang kein Run
  gelesen hat, wird zum Archivieren vorgeschlagen; nichts wird automatisch
  archiviert. Eine ältere Version eines Agents, die noch einen archivierten Fork
  liest, wird in keine Umgebung befördert: Verschieben Sie den Agent auf eine
  andere Version und befördern Sie die Version, die dabei veröffentlicht wird.

### Welche Version ein Agent liest { #which-version-an-agent-reads }

Jeder Agent liest einen gebundenen Skill auf eine von drei Arten:

| Zustand | Was er liest |
|---|---|
| Main | Die neueste Main-Version. So liest jeder Agent, der keine andere nennt |
| Festgesetzt | Eine Main-Version, bis jemand ihn verschiebt |
| Fork | Die neueste Version eines Forks |

Die Wahl gehört zum Spec des Agents, in `skill_bindings`, und wird daher
veröffentlicht, zwischen Umgebungen befördert und mit dem Rest des Agents
exportiert. Ein Spec ohne das Feld liest bei jedem Skill main, wie es jeder Agent
vor den Skill-Versionen tat. Das Veröffentlichen lehnt eine Version ab, die die
Main-Linie des Skills nicht hat, einen Fork eines anderen Skills, einen
archivierten Fork und alles einer anderen Organisation. Jeder Run hält die
Skill-Versionen fest, die er ausgeliefert hat, die seiner Inline-Spezialisten
eingeschlossen.

Eine neue Version erreicht nur die Agents ihrer Linie. Eine neue Main-Version
erreicht die Agents auf main, eine neue Fork-Version die Agents dieses Forks: Ihre
Eval-Suites laufen, die Änderung nennt die Umgebungen, in denen sie live geht, und
ihre Besitzer werden benachrichtigt. Ein festgesetzter Agent wird von keiner
erreicht.

**Die Agents eines Skills** sind die, die ihn ausführen: Eine Version, die eine
ihrer Umgebungen ausliefert, bindet ihn, selbst oder über einen Inline-Spezialisten.
Ein Agent und jeder seiner Spezialisten lesen den Skill auf ihre eigene Art, daher
ist jeder eine eigene Zeile: Die Skill-Seite listet ihn mit der Version, die er
liest, wie viele Main-Versionen er zurückliegt und jeder Umgebung, die ihn anders
liest. Ein Agent, der den Skill nur im Entwurf bindet, ist als solcher
gekennzeichnet. Agents, die Sie nicht sehen, werden gezählt, nicht genannt. „Hinter
main“ zählt die Main-Versionen danach, die geändert haben, was der Skill sagt:
Denselben Text erneut wiederherzustellen ist keine Änderung, und ist main zu dem
Text zurückgekehrt, den er liest, liegt er gar nicht zurück.

**Change version** verschiebt einen Agent auf main, eine Main-Version oder einen
Fork, und das ist eine Änderung am Agent. Ob der Agent den Skill selbst nutzt,
ergibt sich aus seinem Entwurf, wie der Builder ihn zeigt; einen Skill, den nur
einer seiner Spezialisten bindet, ändert man im Builder. Mit dem Recht, ihn zu
veröffentlichen, geht der neueste veröffentlichte Spec des Agents, in dem sich nur
diese Bindung ändert, als seine nächste Version live, und die Umgebungen folgen
ihren üblichen Follow- und Beförderungsregeln. Der Entwurf übernimmt dieselbe
Änderung und behält seine übrigen unfertigen Bearbeitungen, die nicht live gehen.
Mit dem Recht, den Agent nur zu bearbeiten, bei einem nie veröffentlichten Agent
oder bei einem, dessen veröffentlichte Version den Skill noch nicht bindet, wartet
die Änderung im Entwurf, und nur die neue Bindung wird geprüft. Ein bereits auf dem
Agent geöffneter Builder sieht die Änderung erst nach dem Neuladen, und ein
Speichern davor stellt die alte Bindung wieder her.

**Hinter main.** Wenn main weitergeht, bewegt das weder einen festgesetzten Agent
noch einen Fork: Nichts holt von selbst auf, denn Aufholen kostet eine Prüfung auf
den Agents, die es bewegt. `GET /api/v1/skills/behind-main` listet die festgesetzten
Agents und die Forks, an denen main vorbeigezogen ist, über die ganze Organisation,
die am weitesten zurückliegenden zuerst. Ein festgesetzter Agent zählt nach dem, was
seine Standardumgebung ausliefert, ein Fork nur, solange ein Agent ihn liest.
Skills, die du nicht sehen darfst, fehlen, und festgesetzte Agents, die du nicht
siehst, werden gezählt, nicht genannt.

**Zurück zu main** verschiebt die Agents eines Forks zurück auf die neueste
Main-Version, alle oder die ausgewählten, jeden so, wie Change version ihn
verschiebt. Einer, der sich nicht verschieben lässt, bleibt mit dem Grund auf dem
Fork. Sobald niemand den Fork mehr liest, wird er archiviert. Ein Agent, dessen
Umgebung auf eine Beförderung wartet, liest den Fork bis dahin weiter, daher bleibt
der Fork bis dahin bestehen. Auf der Seite des Skills bietet ein Fork ohne eigene
Version das an und sagt danach, wer gewechselt hat und wer geblieben ist.

**Auf main aktualisieren.** Ein festgesetzter Agent hinter main wird erst nach
einer Prüfung nachgezogen: `POST /api/v1/skills/{id}/agents/{agent_id}/update-check`
fragt nur diesen Agent, mit seinen eigenen Fragen und denen des Skills, mit der
Version, auf der er steht, und mit der neuesten Version von main samt ihren Dateien,
abgerechnet über das Budget des Agents; `…/update-check/estimate` nennt vorher den
Preis. Die Prüfung braucht das Recht, den Skill zu bearbeiten und Runs zu lesen.
Angenommen wird sie, indem der Agent verschoben wird: `PUT …/agents/{agent_id}/binding`
mit `state: main` und ihrer `check_id`. Das Verschieben wird abgelehnt, wenn die neuere
Version den Agent verschlechtert hat, wenn ein Ergebnis, das nicht gemessen werden
konnte, nicht bestätigt ist (`acknowledge_unknown`), und wenn der Agent seit der
Prüfung erneut veröffentlicht wurde oder main weitergezogen ist; es schließt die
Prüfung ab und markiert den Agent auf dieser Version als geprüft. Einen Agent ohne
Prüfung zu verschieben bleibt möglich, wie jeder Versionswechsel: Der Agent zeigt
dann auf der neuen Version „unbekannt“, und dafür steht ein, wer ihn verschoben hat.
Auf der Skill-Seite bietet **Version ändern** für genau diesen Wechsel **Zuerst
prüfen** an: Es startet die Prüfung und kommt mit ihrem Ergebnis zurück, das der
Wechsel dann mitträgt.

**Einen Fork aufholen lassen.** Die Änderungen von main erreichen einen Fork in einer
Sitzung. Auf der Seite des Skills bietet ein angezeigter Fork das Nachziehen an,
solange main an ihm vorbeigezogen ist, und die Übernahme nach main, sobald er eine
eigene Version hat; die Karte im Dashboard listet die Forks, die main zurückgelassen
hat. Über die API: `POST /api/v1/skills/{id}/forks/{fork_id}/catch-up`, vorher bepreist mit
`…/catch-up/estimate`. Die Sitzung führt drei Versionen zusammen: die main-Version,
auf der der Fork basiert, die neueste des Forks und die neueste von main. Ein Teil,
den nur eine Seite geändert hat, nimmt den Text dieser Seite, und ein Teil, den beide
gleich geändert haben, wird einmal übernommen. Ein Teil, den beide verschieden
geändert haben, ist ein Konflikt, und das Modell schlägt einen Text dafür vor. Unter
**Changes** kann eine Person jeden Teil umschreiben, auch den des Modells
(`GET …/improvements/{run_id}/merge`, dann `PATCH …/merge/description` oder
`…/merge/parts/{index}`). Bei einer Datei, die beide Seiten verschieden geändert
haben, behält eine Person eine Seite (`PATCH …/merge/files`); das Modell schreibt nie
eine Datei. Die Prüfung startet erst, wenn nichts mehr offen ist. Sie fragt die
Agents des Forks nach dem Ergebnis und, sofern `main_alone` nicht beim Bepreisen
der Prüfung unter Changes abgeschaltet wird, nach der neuesten Version von main
allein. Diese zweite Prüfung sagt, ob der Fork noch gebraucht wird, und die Schätzung
nennt ihren Preis in einer eigenen Zeile (`main_alone_usd`). Sie entfällt, wenn die
Zusammenführung ohnehin die neueste Version von main ist. Annehmen
erzeugt eine Fork-Version (`catch_up`), die die übernommene main-Version nennt. Ab
dann basiert der Fork auf dieser main-Version und ist nicht mehr hinter main. Hat
main allein keinen Agent verschlechtert, bietet das Ergebnis außerdem an, den Fork
aufzugeben und seine Agents zu main zurückzuholen; Agents, an denen main allein nicht
geprüft werden konnte, kehren erst nach einer Bestätigung zurück (`acknowledge_unknown`).

**Einen Fork nach main übernehmen.** Dieselbe Zusammenführung in die andere Richtung,
über `…/forks/{fork_id}/to-main`. Die Prüfung fragt die Agents von main nach der
[Regel](#the-rule) für jede Änderung an main. Annehmen erzeugt eine main-Version
(`from_fork`), die die übernommene Fork-Version nennt, samt Dateien. Die Agents des
Forks können danach zu main zurückkehren.

Beides wird abgelehnt (400), wenn der Fork archiviert ist, und (409), wenn er keine
eigene Version hat (seine Agents kehren dann zu main zurück) oder wenn die
Zusammenführung nichts ändern würde. Abgelehnt wird auch (422), wenn ein Text zu lang ist oder seine
Zeilen zu oft wiederholt, um in vertretbarer Zeit Zeile für Zeile zusammengeführt zu
werden; die Änderungen werden dann von Hand übernommen. Annehmen wird abgelehnt, sobald main oder der Fork eine neuere
Version hat als die, die die Zusammenführung gelesen hat, und eine Sitzung, deren
Linien weitergezogen sind, während sie wartete, endet als veraltet: Starten Sie eine
neue, um die neuere Version einzubeziehen.

### Einen Skill löschen { #deleting-a-skill }

Ein Skill, den ein Agent verwendet, lässt sich nicht löschen. Das ist ein Skill,
den der Entwurf eines aktiven Agents bindet oder eine Version, die eine seiner
Umgebungen ausliefert, beim Agent selbst oder bei einem Inline-Spezialisten. Die
Ablehnung nennt die Agents, die Sie sehen können, und zählt die übrigen. Ein Skill,
den niemand verwendet, wird mit seinen Versionen und Forks gelöscht.

Sie können ihn auch in einem Schritt aus diesen Agents entfernen und löschen
(`DELETE /api/v1/skills/{id}?remove_from_agents=true`). Jeder Agent verliert den
Skill in seinem Entwurf, bei sich selbst und in jedem Inline-Spezialisten. Wo eine
Umgebung, die Veröffentlichungen folgt, eine Version ausliefert, die ihn verwendet,
wird die neueste veröffentlichte Version des Agents ohne ihn erneut veröffentlicht,
wie es Version ändern tut.

Entweder verliert jeder Agent ihn und der Skill wird gelöscht, oder nichts ändert
sich. Die ganze Anfrage wird abgelehnt, mit den Namen der Agents, wenn:

- ein Agent, der ihn verwendet, für Sie verborgen ist;
- Sie einen davon nicht bearbeiten oder einen, der veröffentlicht werden muss, nicht
  veröffentlichen dürfen;
- eine Umgebung, die auf eine Beförderung wartet, eine Version ausliefert, die ihn
  verwendet. Eine solche Umgebung bewegt nur eine Beförderung, und das entscheidet
  ihr Eigentümer.

Ein [API-Schlüssel der Organisation](api.md#organization-api-keys) erreicht die
Versionen, Forks und Agents eines Skills, wie die Tabelle unten sie aufführt.

Checks
(`…/checks…` und `…/update-check`), die Testfragen (`…/test-set`) sowie
Improve-Sitzungen, das Nachziehen von main und das Verschieben nach main samt ihren
Zusammenführungen antworten nur einer angemeldeten Person oder dem Architect oder einem
MCP-Client, der für sie handelt; Änderungsvorschläge (`/api/v1/skill-changes`)
antworten nur einer Person in der Konsole. Ein Schlüssel erhält `403` "API keys are
not accepted on this endpoint": Jede davon gibt Geld im Namen von jemandem aus oder
endet in einer Entscheidung, die diese Person selbst trifft.

| Pfad | Was er tut |
|---|---|
| `GET /api/v1/skills/{id}/versions` | Die Versionen von main oder mit `?fork_id=` eines Forks, die neueste zuerst |
| `GET /api/v1/skills/{id}/versions/{version_id}` | Eine Version mit Text und Liste ihrer Dateien, jede mit SHA-256 |
| `GET /api/v1/skills/{id}/versions/{version_id}/resources/{name}` | Eine Datei, wie diese Version sie hatte |
| `POST /api/v1/skills/{id}/versions` | Speichert eine Bearbeitung auf main oder einem Fork, gegen `base_version_id` |
| `POST /api/v1/skills/{id}/versions/{version_id}/restore` | Stellt eine Version auf ihrer eigenen Linie wieder her |
| `GET`, `POST /api/v1/skills/{id}/forks` | Listet Forks oder legt einen von einer Main-Version an |
| `PATCH /api/v1/skills/{id}/forks/{fork_id}`, `POST …/archive` | Benennt einen Fork um oder archiviert ihn |
| `GET /api/v1/skills/{id}/agents` | Die Agents des Skills, die Version, die jeder liest, und wie viele verborgen sind |
| `PUT /api/v1/skills/{id}/agents/{agent_id}/binding` | Verschiebt einen Agent auf main, eine Main-Version oder einen Fork |
| `GET /api/v1/skills/behind-main` | Festgesetzte Agents und Forks, an denen main vorbeigezogen ist, über die ganze Organisation |
| `POST /api/v1/skills/{id}/forks/{fork_id}/return-to-main` | Verschiebt die Agents eines Forks zurück auf main und archiviert den Fork, sobald ihn niemand mehr liest |
| `POST /api/v1/skills/{id}/agents/{agent_id}/update-check`, `…/estimate` | Prüft die neueste Version von main an einem festgesetzten Agent oder nennt den Preis dafür |
| `POST /api/v1/skills/{id}/improvements/estimate`, `POST /api/v1/skills/{id}/improvements` | Berechnet den Preis einer Verbessern-Sitzung auf main oder einem Fork und startet sie |
| `POST /api/v1/skills/{id}/improvements/{session_id}/apply`, `…/fork`, `…/discard` | Übernimmt das Ergebnis einer Sitzung, mit oder ohne Festsetzen der schlechteren Agents, macht daraus einen Fork für die gewählten Agents oder verwirft es |
| `POST /api/v1/skills/{id}/improvements/{session_id}/recheck` | Prüft ein Ergebnis erneut auf der Linie, wie sie jetzt ist |
| `GET /api/v1/skill-improvements/awaiting` | Die Skill-Sitzungen, die auf einen Menschen warten |
| `GET /api/v1/skill-checks/awaiting` | Die Prüfungen, die eine Person gestartet hat und die noch laufen oder auf eine Entscheidung warten, auf Skills, die der Aufrufer bearbeiten darf |

## Skills in eine Organisation bekommen { #getting-skills-into-an-organization }

**Schreiben Sie einen.** Skills → New, in der UI. Das ist der normale Weg.

**Die mitgelieferte Bibliothek wird automatisch installiert.** Neue
Organisationen erhalten Verfahren für Plattformaufbau, längere Arbeit, Recherche,
Visualisierung, Apps und Präsentationen. Skills kennzeichnet die Kopien als
`built-in`. Es sind gewöhnliche Skills der Organisation, keine Registry-Verweise.

Das Kennzeichen `built-in` gilt auch für installierte Kopien aus der mitgelieferten Skill-Galerie, einschließlich der von Starteragenten hinzugefügten Skills. Es bezeichnet die Herkunft aus der Plattform, nicht eine automatische Installation. Galerie-Skills werden weiterhin gezielt installiert; vorhandene Anpassungen bleiben editierbar.

Bestehende Installationen erhalten neue Built-ins beim Aktualisieren der
mitgelieferten Agenten nach dem Öffnen der Konsole. Auch ein neuer Agent aus der
Standardvorlage synchronisiert die Bibliothek. Ein manueller Seed ist nicht nötig.
Unveränderte Kopien samt Ressourcen werden aktualisiert; bearbeitete und
abweichende unprotokollierte Kopien bleiben erhalten. Installationsbelege erkennen
bewusst gelöschte Skills, die automatische Aktualisierung stellt sie nicht wieder
her. Der ausdrückliche Seed-Befehl kann sie zurückbringen. Die Skill-Liste selbst
bleibt schreibgeschützt.

Die Skill-Seite kennzeichnet außerdem die Skills, die der [AI Architect](console.md)
bindet, mit einem `Architekt`-Abzeichen, weil eine Änderung an einem davon
verändert, wie der Architect arbeitet.

AgenticOS, Architect und neue Standardagenten binden:
`platform-agents`, `platform-workflows`, `platform-automation`, `durable-work`, `document-production`, `research-and-evidence`.

Die optionalen `platform-tables`, `platform-context`, `platform-skills` und API-Leitfäden der Galerie bleiben in der Bibliothek verfügbar, sind aber nicht mehr standardmäßig gebunden. Gewöhnliche MCP-Lese- und Schreibvorgänge erfordern keinen Skill. Aktuelle Tool-Beschreibungen bestimmen Operationen, Parameter und Berechtigungen; Skills ergänzen Entwurfsentscheidungen und Prüfmethoden. Ausführliche visuelle Rezepte werden nur bei Bedarf als Ressourcen geladen.

Dazu kommen App-, Visualisierungs- und Präsentationsverfahren einschließlich
Storyline und Review. Zunächst laden nur Namen und Beschreibungen, bei Bedarf
Inhalte und Ressourcen. Skills gewähren weder Tools noch Konten oder Compiler.
Architect erhält auch Apps und Charts.

Die Aktualisierung schützt angepasste Felder für Prompt, Tools und Skill-Bindungen
getrennt. Eine reine Modelländerung verhindert keine Aktualisierung anderer
unveränderter Vorgaben. Neue Vorgaben gelten für neue Agenten; bestehende eigene
Agenten werden nicht umgeschrieben.

Plattform-MCP kann Context-Dateien suchen, anlegen und bearbeiten, `context_ids`
an Agentenentwürfe binden sowie Skills lesen, bearbeiten und Textressourcen
hinzufügen. Context verwendet `inject` für ständige Prompt-Inhalte und `link` zum
Lesen bei Bedarf. Änderungen einer gebundenen Datei gelten beim nächsten Lauf;
eine geänderte Entwurfsbindung muss veröffentlicht werden. Berechtigungen und
Freigaben gelten weiterhin.

Der Dokument-Skill enthält LaTeX-Ausgangsdateien und ein Build-/Render-Verfahren.
HTML-Apps und Browserfolien sind keine kompilierten PDFs oder editierbaren PPTX.
Der Agent prüft verfügbare Compiler, Generatoren und Renderer und nennt fehlende
Builds oder visuelle Prüfungen ausdrücklich.

Der Seed-Befehl tut dasselbe vom Terminal aus, für skriptgesteuerte Installationen:

```bash
uv run agenticos cmd seed-skills                    # every organization
uv run agenticos cmd seed-skills --org <org-id>     # one
uv run agenticos cmd seed-skills --dry-run          # say what would happen, do nothing
uv run agenticos cmd seed-skills --replace          # also overwrite copies edited here
```

Er installiert, was fehlt, und **aktualisiert, was niemand bearbeitet hat**. Jede
Kopie hält fest, aus welcher mitgelieferten Version sie geschrieben wurde;
verbessert ein Release einen mitgelieferten Skill, wird die unberührte Kopie einer
Organisation durch die neue ersetzt — samt Dateien, als neue Version und mit einem
Audit-Eintrag `skill.refreshed`. Es sei denn, Agents folgen ihr: Dann wartet die
mitgelieferte Version unter Skills als Änderung und geht live, sobald eine
[Prüfung auf diesen Agents](#checking-a-change-on-every-agent) es erlaubt.

Eine hier bearbeitete Kopie bleibt genau so, wie sie ist, sodass eine bearbeitete
Rückerstattungsregel ein erneutes Seeding überlebt; `--replace` ist der einzige
Weg, die mitgelieferte Version über solche Bearbeitungen zu legen, und der
Audit-Eintrag hält fest, dass es geschah. Eine Kopie von vor der
Versionserfassung, die von der mitgelieferten abweicht, wird ebenfalls gemeldet
und in Ruhe gelassen, denn nichts kann sagen, ob sie bearbeitet wurde.

Der Befehl gibt für jeden Skill aus, was er getan hat, und `--dry-run` gibt
denselben Plan aus, ohne zu schreiben.

`e2e/seed.setup.ts` legt ebenfalls einen über die UI an, und genau dagegen prüft
die E2E-Suite.

### Die Gallery — siebzig weitere, und keiner kommt ungebeten { #the-gallery-seventy-more-and-none-of-them-arrive-uninvited }

**Skills → Skill gallery** öffnet einen Katalog fertiger Skills, gruppiert nach
Branche: Gesundheitswesen, Finanzen und Versicherung, E-Commerce und Print on
Demand, Softwareteams, öffentlicher Sektor und Versorger, Recht und
professionelle Dienstleistungen, Fertigung und Logistik. Jeweils zehn.

Wählen Sie eine Branche, dann installieren Sie einen Skill oder das ganze Regal.
Von diesem Moment an ist es ein gewöhnlicher Skill, den die Organisation besitzt
und bearbeitet, genau wie ein mitgelieferter. **Vorschau** zeigt die Anweisungen
eines Skills und die Dateien, die er mitbringt, bevor Sie ihn installieren, und
**Installiert** öffnet die eigene Kopie der Organisation.

!!! info "Die Gallery ist opt-in, und das ist der ganze Unterschied"

    Die mitgelieferte Bibliothek liegt in `app/core/catalog/skills/` und wird
    automatisch in **jede** Organisation kopiert. Die Gallery liegt in
    `app/core/catalog/skill_gallery/` und wird in **keine** kopiert — sie wird vom
    selben Parser gelesen, aus einem zweiten Verzeichnis, und nie geseedet.

    Siebzig Branchen-Skills im ersten Verzeichnis wären siebzig Zeilen gewesen, um
    die niemand gebeten hat, in jedem Tenant, beim nächsten Deploy.

Ein Regal zu installieren, von dem Sie einen Skill bereits haben, installiert den
Rest und lässt diesen einen in Ruhe: ein vorhandener Name wird übersprungen statt
überschrieben, und die Anfrage antwortet damit, was sie installiert hat, was sie
übersprungen hat, und welchen Schlüssel dieses Deployment nicht mitliefert.

Etwas zur Gallery hinzuzufügen ist dasselbe wie einen mitgelieferten Skill
hinzuzufügen — ein Ordner mit einer `SKILL.md`, unter der Branche, zu der er
gehört — mit einer zusätzlichen Regel: **sein Name darf weder mit einem
mitgelieferten Skill noch mit einem anderen Gallery-Skill kollidieren,** und er
ist der Name seines Ordners. Die Installation gleicht über den Namen ab, eine
Kollision würde also für immer stillschweigend übersprungen. Ein Test liest alle
siebzig und schlägt bei einem der beiden Fehler fehl.

### Kopien beim Seeding { #seeding-copies }

Ein geseedeter Skill ist ein gewöhnlicher Skill im Besitz der Organisation, vom
Moment ihrer Existenz an bearbeitbar. Er ist eine **Kopie**, keine Verknüpfung.

Das ist Absicht. Der Sinn eines Skills ist, dass eine Support-Leitung die
Rückerstattungsregel ohne Deploy korrigieren kann, und eine lebende Verknüpfung
zurück zur Kopie im Repository würde genau das wegnehmen — die Organisation würde
eine Datei lesen, die nur ein Entwickler ändern kann.

Bearbeiten und Löschen sind beide auf gewöhnliche Weise endgültig. Deaktivieren
gibt es weiter für einen Skill, den eine Organisation behalten, aber nicht
ausführen will — jeder Agent respektiert es —, es ist nur nicht mehr der einzige
Weg, einen Built-in loszuwerden.

### Warum die Bibliothek mitgeliefert und nicht geholt wird { #why-the-library-is-bundled-and-not-fetched }

Einen Skill zur mitgelieferten Bibliothek oder zur Gallery hinzuzufügen ist ein
Deploy.

Die Alternative — der Import von einer Git-URL — kostet ausgehenden
Netzwerkverkehr vom Backend, einen Parser, der auf fremde Repositories gerichtet
ist, und ein Versprechen über Inhalte, die hier niemand gelesen hat. Jeder Ordner
in `app/core/catalog/skills/` und `app/core/catalog/skill_gallery/` ist dasselbe
kleine Versprechen, das auch der [MCP-Katalog](mcp.md#the-catalog) gibt: jemand
hat es sich angesehen.

## Die Seite eines Skills { #a-skills-page }

Öffnen Sie einen Skill in der Liste, um seine Seite zu sehen. Sie hat vier Tabs.

**Agents** listet jeden Agent, der den Skill nutzt, mit der Version, die er bekommt:

- `v12 · main` - der Agent folgt main und bekommt jede neue Version sofort.
- `v9 · festgesetzt · 3 hinter main` - der Agent bleibt auf einer älteren main-Version.
- `Fork „Returns“ · ab v7 · 2 Änderungen` - der Agent nutzt einen Fork: eine Linie
  von Versionen mit eigenen Änderungen, gestartet von einer main-Version.

Eine Umgebung, die eine andere Version ausliefert, steht unter dem Agent, und ein
Inline-Spezialist, der den Skill bindet, hat eine eigene Zeile - siehe
[Welche Version ein Agent liest](#which-version-an-agent-reads). Ein Agent, der den
Skill nur in seinem Entwurf bindet, ist mit **Nur im Entwurf** markiert und folgt
keiner Linie. Agents, die Sie nicht sehen, werden gezählt, nicht genannt. Die Chips
über der Tabelle zeigen alle, die Agents auf main, die festgesetzten, einen Fork oder
die Agents nur im Entwurf, sodass ihre Zahlen zusammen alle ergeben. Ein dort
gewählter Fork ist auch die Linie, die der Verlauf zeigt und in die Bearbeiten
speichert.

Jede Zeile sagt, ob eine [Prüfung](#checking-a-change-on-every-agent) die
Version gemessen hat, die der Agent ausliefert, und mit welchem Ergebnis. Eine
Version, die keine Prüfung gemessen hat, ist **unbekannt**, wo eine Änderung den
Agent ungeprüft erreicht hat - seine Antworten nutzten eine frühere Version - und
**noch nicht geprüft**, wo der Agent mit keiner anderen geantwortet hat.

Darunter zählt **Testfragen** die eigenen [Testfragen](#what-a-check-asks) des
Skills und verlinkt ihr Dataset oder beginnt sie. Ein Skill, den kein Agent nutzt,
bietet anstelle der Tabelle **Zu einem Agenten hinzufügen** an.

Unter der Tabelle sieht, wer Runs ansehen darf, wie oft jeder Agent den Skill in den
letzten 30 Tagen geöffnet hat: ein Diagramm nach Tagen mit den Agents, die Sie in
der Liste darüber auswählen, jeder in seiner Farbe, darunter eine Tabelle
mit den Ladevorgängen jedes Agents, den gelesenen Dateien und wann er den Skill
zuletzt genutzt hat. Runs von Evals und vom Testbereich des Builders zählen nicht.

**Version ändern** setzt einen Agent auf main, auf eine festgesetzte main-Version
oder auf einen Fork, wie [Welche Version ein Agent
liest](#which-version-an-agent-reads) beschreibt: was live geht, was im Entwurf
wartet und was im Builder geändert wird. Eine andere Version als die, die der Agent
gerade ausliefert, die keine Prüfung auf ihm gemessen hat und mit der er noch nicht
geantwortet hat, wurde dort nicht geprüft, deshalb bestätigen Sie das zuerst oder
drücken **Zuerst prüfen**, wenn es der Wechsel eines festgesetzten Agents auf die
neueste main-Version ist; bei einer gemessenen nennt der Dialog das Ergebnis. Der Dialog sagt auch, wann der Agent keine neuen main-Versionen mehr
bekäme, und datiert jede main-Version, die er zum Festsetzen anbietet, mit einem
Link zu ihren Änderungen. Das Steuerelement sehen Personen, die den Agent bearbeiten
dürfen.

**Inhalt** zeigt, was die gewählte Linie jetzt ausliefert - Beschreibung,
Anweisungen und Dateien - zum Lesen, ohne den Editor zu öffnen.

**Verlauf** listet die Versionen der gewählten Linie, die neueste zuerst: woher jede
kam (eine Bearbeitung, eine Dateiänderung, die Bibliothek, der Workspace eines
Agents, Improve oder eine Wiederherstellung), wer sie gemacht hat und wann.
**Änderungen zeigen** vergleicht Beschreibung und Anweisungen mit der Version davor -
bei der ersten Version eines Forks mit seiner Basis auf main - und nennt die
hinzugefügten, entfernten oder geänderten Dateien. **Wiederherstellen** holt eine
frühere Version als neueste auf ihre eigene Linie zurück, und die Agents, die dieser
Linie folgen, bekommen sie sofort. Ein Fork nummeriert seine Versionen ab 1 wie
main, deshalb tragen sie seinen Namen - „Returns v2“ -, und der Verlauf von main
markiert die Version, bei der jeder Fork beginnt.

Unter den Versionen sieht, wer Runs ansehen darf, die **Improve-Sitzungen** der
Linie: wann jede lief und wer sie begann, wie sie endete - als Version übernommen,
ein Fork, verworfen, abgelaufen - und was sie kostete. **Fortsetzen** öffnet eine
Sitzung, die noch auf Sie wartet; **Öffnen** zeigt eine beendete. Eine Version, die
eine Sitzung übernommen hat, verweist auf sie.

**Bearbeiten** speichert eine neue Version auf der angezeigten Linie. Auf main
bekommen die Agents, die main folgen, sie sofort; festgesetzte Agents und Forks
behalten ihre Version. Ein geänderter Text wird nicht beim ersten Klick gespeichert:
Der Dialog nennt die Agents, die er bei ihrem nächsten Run erreicht, und bietet
neben dem sofortigen Speichern **Zuerst an Agents prüfen** an, das den
ungespeicherten Text auf ihnen prüft und anhand des Ergebnisses übernimmt. Speichert
jemand die Linie inzwischen, wird die Prüfung abgelehnt und Ihr Text bleibt im Editor.
Dateien
und Kategorie gehören zu main, deshalb ändert das Bearbeiten eines Forks nur seine
Beschreibung und Anweisungen. Wiederherstellen und Version ändern sehen nur
Personen, die diese Änderung vornehmen dürfen; alle anderen öffnen den Skill nur
lesend.

**Neuer Fork** beginnt einen Fork ab der neuesten Version von main, unter einem Namen,
den Sie vergeben, und kann sofort Agents auf ihn verschieben, jeden als Version ändern.
Der Fork liest sich wie seine Basis, bis er bearbeitet wird.

**Löschen**, neben Bearbeiten im Seitenkopf, löscht den Skill mit seinen Versionen
und Forks. Solange Agents ihn verwenden, nennt der Dialog sie. Dürfen Sie jeden von
ihnen ändern, bietet er **Von N Agents entfernen und löschen** an, das sie zur
zweiten Bestätigung noch einmal aufführt. Dann entfernt er den Skill von jedem Agent
und löscht ihn. Sind Agents darunter, die Sie nicht ändern dürfen oder nicht sehen,
sagt der Dialog das und bietet kein Löschen an: Entfernen Sie den Skill zuerst im
Builder von diesen Agents, oder bitten Sie jemanden, der es darf. Eine Umgebung, die
auf Promotion wartet und den Skill noch ausliefert, wird ebenfalls genannt, denn nur
eine Promotion verschiebt sie.

### Einen Skill verbessern { #improving-a-skill }

**Verbessern** auf der Seite eines Skills öffnet eine Sitzung für die angezeigte
Linie - main oder den in den Chips gewählten Fork - in denselben fünf Schritten wie
das [Verbessern eines Agents](authoring.md#the-improve-wizard): Verstehen, Änderungen, Prüfung,
Ergebnis und Annehmen. Sie hält nach Verstehen, nach Änderungen und beim Ergebnis
für Sie an und ändert nichts, bevor Sie annehmen.

Der Start sagt, wie viele negativ bewertete oder fehlgeschlagene Antworten sie liest
und wie vielen Agents die Linie dient. Er nennt
auch, was der Weg bis zum ersten Vorschlag und jeder Versuch danach kostet. Das
Ausgabenlimit ist so ausgefüllt, dass es den ersten Vorschlag und jeden Versuch der
Sitzung deckt, und deckelt die ganze Sitzung. Bevor die
Änderungen geprüft werden, nennt der nächste Schritt jeden Agent der Linie, auf dem
die Prüfung läuft, und die, bei denen das nicht geht, mit Grund - keine Testfragen,
kein Recht zum Ausführen, kein Budget mehr, keine veröffentlichte Version oder ein
Run, der nicht jede Antwort bewerten konnte. Agents, die Sie nicht sehen, werden
gezählt.

Das Ergebnis beginnt mit einem Balken, der die Agents zählt, die besser,
unverändert, schlechter oder unbekannt herauskamen. Darunter steht eine Zeile pro
Agent: besser, unverändert, im Rauschen, schlechter oder unbekannt, die wichtigsten
zuerst. Jede Zeile hat einen kleinen Balken der behobenen gegen die
verschlechterten Fragen.

Eine ganze Zeile öffnet sich zu ihren Details, mit einem Klick irgendwo darauf
oder mit Enter oder Leertaste: für jede Fragenmenge, die der Agent bekam - die
Fragen des Skills, seine eigene Menge oder eine Stichprobe daraus - wie viele
besser, gleich, schlechter oder unbekannt herauskamen, mit einem Link zu diesem
Run, und ob er nur auf den Fragen des Skills geprüft wurde. Eine geöffnete Zeile
ist als **Angesehen** markiert.

Über den Zeilen zählt **Noch anzusehen** die schlechteren und unbekannten Agents,
die Sie noch nicht geöffnet haben. Jede Zahl auf dem Balken filtert die Zeilen auf
ihre Agents, ein Suchfeld findet einen Agent nach Namen, und **Nur nicht
angesehene** blendet die geöffneten aus.

Die Zeilen sind nach Ergebnis gruppiert:
zuerst die schlechteren, die am stärksten verschlechterten oben, dann die
unbekannten nach dem Grund, warum sie nicht geprüft werden konnten - mit einem Weg,
Testfragen hinzuzufügen, wenn das der Grund ist - dann die noch laufenden,
unveränderten und besseren. Ab acht Agents sind unverändert und besser
zugeklappt und nur gezählt, bis Sie sie öffnen.

Was Annehmen anbietet, folgt aus dem Ergebnis:

- **Niemand schlechter** und jemand besser: als nächste Version der Linie anwenden.
- **Jemand schlechter:** anwenden und diese Agents auf ihrer Version festsetzen,
  weiter verbessern oder verwerfen. Auf einem Fork bleiben nur Weiterverbessern
  und Verwerfen, weil ein Fork nicht festgesetzt werden kann.
- **Niemand besser:** Das Ergebnis wartet trotzdem auf Ihre Entscheidung und bietet
  **Weiter verbessern** und **Verwerfen**, auf main auch **Als Fork speichern**.
- **Was immer das Ergebnis ist**, legt **Als Fork speichern** auf main einen Fork
  mit der Änderung an: Sie benennen ihn und wählen die Agents, die auf ihn
  wechseln - zu Beginn die, denen sie half, andere oder keine. Ein Fork wird nie
  erneut geforkt.
- **Unbekannte Agents** müssen bestätigt werden, bevor etwas angewendet wird.
  **Testfragen hinzufügen** daneben schreibt die eigenen Fragen des Skills aus
  Antworten, in denen Agents ihn geladen haben, damit sie beim nächsten Mal
  geprüft werden können.

Bekommt die Linie nach der Prüfung eine neue Version oder ändern sich ihre
Agents, gilt das Ergebnis nicht mehr und bietet statt des Anwendens **Erneut
prüfen** an: dieselben gewählten Änderungen, gemessen an der Linie, wie sie
jetzt ist, zu einem Preis, der zuerst angezeigt wird. Verwerfen bleibt
möglich; Weiterverbessern setzt voraus, dass die Änderungen erneut geprüft wurden. Ändert sich die Linie, während die Sitzung bei Changes
wartet, wird neu bepreist: Der nächste Schritt prüft die Änderungen auf der
neuesten Version.

Der [Architekt](console.md#the-assistant) liest die Agents, Versionen und
Sitzungen eines Skills und die festgesetzten Agents und Forks, an denen main
vorbeigezogen ist. Er startet eine Sitzung, führt einen Schritt aus oder
wiederholt ihn, nimmt ein Ergebnis an, beendet eine Sitzung, verschiebt einen
Agent auf eine andere Version oder holt einen festgesetzten Agent oder einen Fork
zu main auf, nur wenn Sie darum bitten, jeweils über eine Freigabekarte.

## Skills oder Knowledge? { #skills-or-knowledge }

Sie beantworten verschiedene Fragen, und der Unterschied zählt, wenn ein Agent
das Falsche bekommt.

|  | Skills | [Knowledge](file-processing.md) |
| --- | --- | --- |
| Enthält | Verfahren — wie wir das machen | Dokumente — was wir wissen |
| Geschrieben von | Einem Menschen, absichtlich | In großer Zahl eingelesen |
| Gefunden über | Das Modell, das einen Namen wählt | Semantische Suche über Chunks |
| Zitiert | Nichts; er _ist_ die Anweisung | Die Passage und ihre Quelle |
| Größenordnung | Zehner | Tausende von Dokumenten |

!!! example "Was ist was"

    "Rückerstattungen über 500 £ brauchen eine Freigabe durch die Leitung" ist ein
    **Skill**. Der unterschriebene Vertrag, der das sagt, ist **Knowledge**.

    Ein Agent, der Rückerstattungen bearbeitet, will meist beides, und die zwei
    Capabilities lassen sich kombinieren — `skills` für das Verfahren, `knowledge`
    für den Beleg.

## Zugriff { #access }

Skills sind Ressourcen im Umfang einer Organisation und werden wie Agents und
Collections geregelt: Sichtbarkeit plus zeilenweise Grants über der Rolle hinaus.
Siehe [Berechtigungen](permissions.md#layer-3-visibility-and-grants).

!!! important "Einen Skill zu binden heißt, ihn zu verleihen"

    Jeder Run des Agents liest den Textkörper und die Dateien, wer ihn auch
    gestartet hat — deshalb verlangt das Veröffentlichen, dass die **Person, die
    veröffentlicht**, `skills:view` auf dieser Zeile hält.

Diese Prüfung geht durch `resolve_access`, ein Grant zählt also: ein Mitglied,
dem ein Skill geteilt wurde, kann ihn binden, ohne befördert zu werden.

Ein Skill, den sie nicht erreichen können, wird als `Skill not found: <id>`
abgelehnt, wortgleich mit einer Id, die es nicht gibt. Skills werden über UUID
gebunden, aus der API und aus einem handbearbeiteten Entwurf, nicht nur aus der
Liste des Builders gewählt, und eine Ablehnung, die sich anders liest, würde die
privaten Skills der Organisation Rateversuch für Rateversuch kartieren.

Dieselbe Prüfung läuft auf den `skill_ids` eines
[Inline-Spezialisten](concepts.md#delegate-vs-inline-specialist) und wird mit dem
Namen des Spezialisten gemeldet.

Zur Laufzeit wird nichts erneut geprüft. Die Skills des eingefrorenen Specs
werden innerhalb der Organisation des Runs aufgelöst und dem Agent übergeben —
nach der Regel, der Collections und Delegates bereits folgen, dass
[die Referenz einmal geprüft wird, beim Veröffentlichen](permissions.md#delegation-is-not-a-privilege-boundary).

Die Alternative ist auf zwei konkrete Weisen schlechter:

- Jeder Kontext ohne Subjekt — ein API-Key, ein eingebettetes Widget, eine
  Kanalnachricht — wird von `resolve_access` konstruktionsbedingt abgelehnt, eine
  Prüfung pro Runner würde also genau diesen Oberflächen jeden Skill entziehen.
- Wo es _doch_ ein Subjekt gibt, würde ein und dieselbe veröffentlichte Version
  einem Mitglied — dessen Rolle nur geteilte Skills erreicht — dünnere Anweisungen
  geben als einer bauenden Person, und der Unterschied wäre nirgends sichtbar.

Skills haben keinen eigenen Aktivierungsschalter: Ein Agent kann seine gebundenen
Skills verwenden. Entfernen Sie die Bindung und veröffentlichen Sie den Agenten,
um einen Skill nicht mehr zu verwenden. Ein nach der Veröffentlichung gelöschter
Skill wird mit einer Warnung übersprungen, ohne den Run abzubrechen.

## Zusammenfassung { #recap }

- Ein Skill ist ein **Verfahren**, von einem Menschen geschrieben, und wird nur
  geladen, wenn das Modell entscheidet, dass seine _description_ relevant ist —
  Discovery kostet eine Zeile pro Skill, und der Textkörper kostet nichts, bis er
  geöffnet wird.
- In einem Workspace ist ein Skill auch **Dateien**, und das macht seine Skripte
  ausführbar.
- Ein Agent **schlägt** eine Änderung vor; ein Mensch wendet sie an, einmal, und
  die Entscheidung ist endgültig.
- Einen Skill zu binden heißt, ihn zu **verleihen**, die veröffentlichende Person
  muss ihn also sehen können — und zur Laufzeit wird nichts erneut geprüft.
- Die **Gallery** sind siebzig fertige Skills nach Branche, auf Anfrage
  installiert — anders als die mitgelieferte Bibliothek, die von allein ankommt.

### Einen neuen Skill vorschlagen { #proposing-a-new-skill }

Der Assistent kann **Ein Skill wäre sinnvoll** vorschlagen, wenn ein wiederverwendbarer Ablauf in mindestens drei verschiedenen Quellantworten vorkommt. Jede Textstelle muss in der Antwort selbst stehen; Kommentare allein belegen keinen wiederholten Ablauf. Die Karte zeigt Name, Beschreibung, vollständigen Inhalt, Begründung und geprüfte Belege. Eine Evaluation bindet einen temporären Skill nur an den Kandidaten: Sie erstellt weder einen Skill-Datensatz noch eine veröffentlichte Version.

**Accept** erstellt den privaten Skill und bindet ihn in derselben Transaktion an den Draft des Agenten. Dafür sind `skills:edit` und Bearbeitungszugriff auf den Agenten nötig. Ohne Erstellungsrecht bleibt der Vorschlag lesbar und prüfbar; die deaktivierte Annahme erklärt den Grund. **Dismiss** erstellt nichts. **Undo** entfernt die Bindung und behält den unabhängigen Skill. Erneutes Annehmen verwendet ihn nur bei unverändertem Namen und Inhalt. Skills enthalten Anweisungen und gewähren keine Tools. Zusätzlicher Tool-Zugriff benötigt eigene Richtlinienprüfungen; schreibende Tools erfordern eine Freigabe.

Ein Ablauf aus weniger als drei verschiedenen Antworten wird nicht als Vorschlag aufgenommen. Er steht mit vollständigem Text unter **weitere Ideen warten auf Ihre Entscheidung**. **Create skill** öffnet eine Vorschau: Name, Beschreibung und Inhalt lassen sich bearbeiten, und ein Hinweis nennt, auf wie vielen Antworten er beruht. **Create skill** in der Vorschau legt den Skill in der Bibliothek an und bindet ihn an den Entwurf des Agenten, nie an eine veröffentlichte Version. Dafür gelten dieselben Berechtigungen wie für Accept, und es gibt keinen Modellaufruf. Ein zweiter Klick liefert den bereits erstellten Skill.

Die Kostenschätzung berücksichtigt den vollständigen vorgeschlagenen Inhalt für jede Kandidatenantwort und bestätigende Wiederholungen zusätzlich zum historischen Antwortpreis.
