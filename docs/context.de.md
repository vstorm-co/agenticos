---
source_sha: f5fcd6aff7b4
---

# Context-Dateien { #context-files }

Eine **Context-Datei** ist ein Stück stehendes Wissen, einmal geschrieben und an
viele Agents gebunden: ein Glossar, eine Markenstimme, eine Eskalationsmatrix,
die Liste der Produkte, die Sie wirklich verkaufen.

Sie ist die Antwort auf ein Problem, das jedes Unternehmen bei seinem dritten
Agent trifft — dieselben drei Absätze, in drei Sätze von Instruktionen kopiert
und dann in einem davon bearbeitet.

## Wo sie zwischen Skills und Wissen sitzt { #where-it-sits-between-skills-and-knowledge }

Drei Dinge legen einem Modell Text vor, und die falsche Wahl ist die übliche
Ursache für einen Agent, der entweder ignoriert, was man ihm gesagt hat, oder
überhaupt nichts liest.

| | Sie hält | Das Modell sieht es |
|---|---|---|
| **Context-Datei** | Stehende Fakten, klein und stabil — ein Glossar, ein Tonfall-Leitfaden, ein Organigramm | Immer oder auf Anforderung — Sie entscheiden |
| **[Skill](skills.md)** | Ein Vorgehen für eine Art von Aufgabe — wie eine Rückerstattungsanfrage behandelt wird | Wenn das Modell entscheidet, dass genau diese Aufgabe gerade ansteht |
| **[Wissens-Collection](file-processing.md)** | Ein Korpus, der zu groß zum Lesen ist — jedes Richtliniendokument, jedes Ticket | Nur die Chunks, die eine Suche zurückgibt |

Die Faustregel: **Wenn es kurz und immer relevant ist, ist es eine Context-Datei.
Wenn es lang ist, ist es Wissen. Wenn es ein Vorgehen ist, ist es ein Skill.**

## Zwei Modi, und der Unterschied sind die Kosten { #two-modes-and-the-difference-is-cost }

Jede Context-Datei trägt einen Modus, und der entscheidet, wie die Datei das
Modell erreicht.

=== "`inject` — immer da"

    Der Text wird wortwörtlich in die Instruktionen des Agents eingefügt. Das
    Modell kennt ihn immer, ohne sich zum Nachschauen zu entscheiden und ohne
    einen Tool-Aufruf.

    Nehmen Sie das für Dinge, die der Agent nie falsch machen darf: wie Ihre
    Produkte heißen, an wen eskaliert wird, wie das Unternehmen zu nennen ist.

    **Er wird bei jedem einzelnen Zug gelesen**, gehört also zu den Kosten jeder
    Nachricht. Halten Sie injizierte Dateien kurz.

=== "`link` — auf Anforderung gelesen"

    Der Text bleibt aus dem Prompt heraus und wird über ein Tool angeboten. Das
    Modell liest ihn nur, wenn es die Datei für relevant hält, und wählt dafür
    anhand des Namens und einer einzeiligen Beschreibung, die Sie schreiben.

    Nehmen Sie das für Nachschlagewerke, die manchmal zählen: eine selten
    gebrauchte Richtlinie, eine regionale Abweichung, eine lange Liste.

    Kostet nichts bei Zügen, die sie nicht brauchen, und gar nichts, wenn das
    Modell nie hineinsieht — was zugleich das Risiko ist.

!!! tip "Schreiben Sie die Beschreibung für ein Modell, nicht für einen Menschen"

    Eine verlinkte Datei wird allein anhand ihres Namens und ihrer Beschreibung
    gewählt. "Rückgaberichtlinie" sagt einem Modell weniger als "wann eine Kundin
    einen Artikel zurückgeben darf, die Fristen und die drei Ausnahmen" — und der
    Unterschied entscheidet, ob die Datei je geöffnet wird.

## Sie an einen Agent binden { #attaching-them-to-an-agent }

Context-Dateien gehören einer Organisation, nicht einem Agent. Sie schreiben eine,
und beliebig viele Agents binden sich daran.

Schalten Sie am Agent die Capability **Context** ein und binden Sie dann die
Dateien, die er haben soll. Die Datei danach zu bearbeiten ändert, was jeder
gebundene Agent **bei seinem nächsten Run** weiß — ohne Neuveröffentlichung, bei
keinem davon.

Das ist der ganze Sinn und zugleich das, womit man vorsichtig sein muss: Eine
Änderung an einer injizierten Datei ist eine Änderung an jedem Agent, der sie
trägt. Behandeln Sie sie als den gemeinsamen, tragenden Text, der sie ist.

Die Capability hat eine Einstellung, die zu kennen lohnt. Das Lese-Tool
**abzuschalten** heißt, dass nur injizierte Dateien das Modell erreichen und
nichts auf Anforderung gelesen wird — eine vernünftige Wahl, wenn Sie die Eingaben
eines Agents vollständig vorhersehbar haben wollen.

## Zugriff { #access }

Eine Context-Datei hat einen Owner und eine Sichtbarkeit wie jede andere
Ressource hier, und `context:view` regelt das Lesen des Katalogs. Eine Datei, die
jemandem nicht gewährt wurde, ist eine Datei, die er nicht binden kann, und das
entscheiden [dieselben drei Schichten](permissions.md) wie überall sonst.

Was wirklich geheim ist, gehört nicht in eine — eine Context-Datei ist Text, den
ein Agent auf die richtige Frage hin laut vorliest. Zugangsdaten gehören in
[den Vault](secrets.md).

## Fazit { #recap }

- Eine Context-Datei ist **einmal geschriebenes stehendes Wissen, an viele Agents
  gebunden**.
- **`inject`** steht immer im Prompt und kostet bei jedem Zug; **`link`** wird auf
  Anforderung gelesen und kostet nichts, bis es so weit ist.
- Eine verlinkte Datei wird über ihre **Beschreibung** gewählt, schreiben Sie
  diese also für das Modell.
- Eine Datei zu bearbeiten aktualisiert **jeden gebundenen Agent bei seinem
  nächsten Run**, ohne dass etwas neu veröffentlicht wird.
- Kurz und immer relevant → Context. Lang → [Wissen](file-processing.md).
  Ein Vorgehen → [ein Skill](skills.md).
