---
source_sha: "7588e57ff61c"
title: "Eine Änderung in einem Repository überprüfen"
description: "Lassen Sie einen Agent in seiner Sandbox ein winziges Git-Repository anlegen, einen Diff mit dem eingebauten code-review-Skill prüfen und kontrollieren Sie, dass er beide eingebauten Fehler an den richtigen Zeilen findet."
---

# Eine Änderung in einem Repository überprüfen { #review-a-change-in-a-repository }

Geben Sie einem Agent eine [Sandbox](../sandbox.md) und den mitgelieferten Skill `code-review`, lassen Sie ihn ein kleines Git-Repository anlegen und dann den Diff eines Commits prüfen. Der Diff enthält zwei eingebaute Fehler, einen Off-by-one und ein unbehandeltes `None`, an file:line-Stellen, die Sie von Hand prüfen können. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil und einer registrierten [Sandbox-Verbindung](../sandbox.md), deren Standard-Runtime `workbench` ist, denn sie enthält `git`.
- Den Skill `code-review`, den jede Organisation mitbringt. Siehe [Skills](../skills.md#getting-skills-into-an-organization).
- Nichts weiter zum Anhängen: Das Repository legt der Agent selbst in der Sandbox an, aus dem genauen Dateiinhalt im Prompt unten.

## Die Eingabe vorbereiten { #prepare-the-input }

Hier gibt es keine Datei zum Anhängen. Das "Repository" sind zwei kleine Python-Dateien, die der Agent auf Ihre Anweisung selbst schreibt, sodass Sie genau bestimmen, was der Diff enthält. Version 1 ist ein einfacher Warenkorbrechner:

```python
# utils.py (version 1)
def compute_total(prices):
    total = 0
    for p in prices:
        total += p
    return total


def find_discount_tier(count):
    tiers = [(10, 0.05), (20, 0.10), (50, 0.15)]
    for threshold, rate in tiers:
        if count >= threshold:
            return rate
    return 0.0
```

```python
# main.py (version 1)
from utils import compute_total, find_discount_tier


def checkout(cart):
    prices = [item["price"] for item in cart]
    total = compute_total(prices)
    rate = find_discount_tier(len(cart))
    return total * (1 - rate)
```

Version 2 fügt einen Mitgliederrabatt und eine Hilfsfunktion `apply_discount` hinzu, mit zwei eingebauten Fehlern: Der neue Parameter `member_rate` in `main.py` ist standardmäßig `None` und wird ohne Prüfung verwendet, und `apply_discount` in `utils.py` rabattiert jede Position einschließlich der teuersten und hängt dieselbe Position dann noch einmal an, sodass sie doppelt gezählt wird.

```python
# utils.py (version 2, adds apply_discount)
def apply_discount(prices, rate):
    """Discount every item except the single most expensive one."""
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    discounted = [sorted_prices[i] * (1 - rate) for i in range(n)]
    discounted.append(sorted_prices[-1])
    return discounted
```

```python
# main.py (version 2)
from utils import compute_total, find_discount_tier, apply_discount


def checkout(cart, member_rate=None):
    prices = [item["price"] for item in cart]
    tier_rate = find_discount_tier(len(cart))
    discounted_prices = apply_discount(prices, tier_rate)
    total = compute_total(discounted_prices)
    return total * (1 - member_rate)
```

Referenz: Der Diff zwischen den Versionen hat genau zwei echte Fehler. `return total * (1 - member_rate)` in `main.py` löst immer dann `TypeError` aus, wenn `member_rate` auf dem Standardwert bleibt, und `apply_discount` in `utils.py` gibt eine Position zu viel zurück, weil die Schleife den letzten Index schon enthält, bevor dieselbe Position erneut angehängt wird. Weder `compute_total` noch `find_discount_tier` ändern sich zwischen den Versionen, also sagt ein korrektes Review nichts über sie.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Files & shell**. Wählen Sie **Container**, Ihre Sandbox-Verbindung und die Runtime `workbench`, und behalten Sie den Konversations-Scope bei.
3. Aktivieren Sie **Skills** und binden Sie `code-review`.
4. Legen Sie ein Budget für den Versuch fest. Der festgehaltene Run nutzte etwa 40 Schritte und kostete etwa 0,18 USD, vor allem durch die wiederholten Shell-Genehmigungen.
5. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You review a change in a git repository using the bound code-review skill.
Follow that skill: read the whole change before commenting, say what is wrong
and why it matters, and separate what blocks from what does not.
Only report issues that are actually in the diff. Do not report a problem in a
line the diff did not touch.
Cite every finding as file:line and give a concrete fix.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat und fügen Sie die beiden Versionen oben zusammen mit der Anweisung ein, das Repository anzulegen und die Änderung zu prüfen:

```text
Set up a tiny git repository in your workspace and review one change in it.

1. Create a directory `grocery_calc`, write utils.py and main.py exactly as
   given above (version 1), then git init, configure a throwaway user, and
   commit them as the initial version.
2. Replace both files with version 2 exactly as given above, and commit that
   as a second commit.
3. Run `git diff HEAD~1 HEAD` to get the exact change, then review that diff
   using the bound code-review skill. Report every real defect the diff
   introduces, each as file:line with a concrete fix. Do not report anything
   about a line the diff did not change.
```

Jeder `execute`-Aufruf des Agents (`git init`, jeder Commit, der Diff) zeigt im Chat **Tool approval required**. Lesen Sie den Befehl und klicken Sie jeweils auf **Approve**. Der Run setzt dort fort, wo er angehalten hat. Um das für einen vertrauenswürdigen Test-Agent zu überspringen, ändern Sie die Genehmigungseinstellung von `execute` im Builder. Siehe [Genehmigungen](../governance.md#approvals).

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Unbehandeltes `None` gefunden | `main.py:9`, `return total * (1 - member_rate)` stürzt ab, wenn `member_rate` auf dem Standardwert `None` bleibt |
| Off-by-one gefunden | `utils.py:20-21`, die Comprehension deckt bereits jeden Index einschließlich des letzten ab, dann wird diese Position ein zweites Mal angehängt |
| Beide als file:line angegeben | Nicht nur "in apply_discount ist ein Fehler" |
| Die Korrektur ist konkret | Ein korrigierter Codeausschnitt, nicht nur eine Beschreibung des Problems |
| Unveränderter Code | Keine Anmerkung zu `compute_total` oder `find_discount_tier`, die der Diff nicht berührt hat |
| Blockierend oder nicht | Die beiden Fehler sind als blockierend markiert, alles Stilistische hat das Präfix "nit" |

Lesen Sie den Diff selbst, bevor Sie dem Review vertrauen. `git diff HEAD~1 HEAD` im Dateibereich des Workspaces zeigt genau das, was der Agent geprüft hat.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent lud den Skill `code-review`, dann per `read_skill_resource` dessen `checklist.md` und `review-comment.md`, schrieb danach beide Dateien, committete zweimal und führte den Diff aus. Das waren drei `execute`-Aufrufe, jeder zur Genehmigung geparkt. Nach der Genehmigung antwortete er mit drei blockierenden Befunden und einem Nit.

    Er nannte `main.py:9` für den `TypeError` bei fehlendem `member_rate` mit einer zweizeiligen Korrektur und `utils.py:20-21` für die doppelt gezählte Position mit einer korrigierten `apply_discount`, genau passend zu beiden eingebauten Fehlern. Außerdem markierte er den Diff als ungetestet, nach der Regel aus der Checkliste des Skills, dass eine Verhaltensänderung einen Test braucht. Zu `compute_total` und `find_discount_tier` sagte er nichts. Kosten: 0,18 USD über 40 Schritte, das meiste davon für die drei Genehmigungsrunden.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent sagt, er habe keine Shell.** Die Capability nutzt **Files** statt **Container**. Wechseln Sie zu Container und wählen Sie die Runtime `workbench`.
- **Der Run hält nach `git init` oder einem Commit an.** Er wartet auf die Genehmigung von `execute`. Öffnen Sie den Chat oder den Tab **Approvals** in **Activity**.
- **Das Review meldet etwas in unverändertem Code.** Verschärfen Sie die Instruktionen: Es soll nur prüfen, was `git diff` zeigt, nicht die ganze Datei.
- **Ein Befund hat kein file:line.** Bitten Sie den Agent, die Kommentarvorlagen der Checkliste erneut zu lesen, die immer eine Stelle nennen.
- **Der erste Durchgang ist langsam.** Das `workbench`-Image wird gebaut. Spätere Sessions verwenden es wieder. Siehe [die Sandbox](../sandbox.md#when-a-build-is-paid-for).

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die beiden genauen Versionen, den Diff, das Review, die Agent-Version und jeden genehmigten Befehl in Activity auf. Ein Mensch entscheidet weiterhin, ob die Korrekturen stimmen und ob "kein Test dafür" den Merge wirklich blockieren soll. Der Skill formuliert diese Regel, aber sie auf einen echten Pull Request anzuwenden, ist die Entscheidung eines Menschen, genauso wie beim [lokalen Review-Standard](../code-review.md), dem dieses Projekt bei seinen eigenen PRs folgt.

## Nächste Schritte { #next-steps }

Verbinden Sie denselben Agent mit einer Sandbox mit Netzwerkzugang und lassen Sie ihn einen Diff aus einem geklonten öffentlichen Repository prüfen statt eines diktierten. Die Runtime `workbench` hat `git` und ein Netzwerk, also funktioniert `git clone` genauso wie hier `git diff`.
