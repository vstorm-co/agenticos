---
source_sha: "f0e7bf18f180"
---

# Nachweis-Szenario { #proof-scenario }

Eine Änderung ist erst fertig, wenn der Agent den Fehler reproduziert, ihn
nach der Korrektur bestehen sieht und die Belege zeigen kann. Grüne gemockte
Tests beweisen nicht, dass die Nutzererfahrung funktioniert. Nachweis sind
Belege, die in der Sitzung beobachtet wurden - Befehlsausgabe, eine
Reproduktion, ein Bildschirmfoto - für jede Änderung im Diff.

Das ist Theos tstack-`full-send`-Prinzip „Nachweis, nicht Diffs" als
Capability. Das Vorgehen steht im Skill `proof-scenario`
(`backend/app/core/catalog/skills/proof-scenario/SKILL.md`); diese Seite sagt,
was die Capability mit den Belegen macht.

## Wie ein Szenario funktioniert { #how-a-scenario-works }

Der Agent zeichnet ein Szenario mit `proof_scenario_record` auf, **bevor er
etwas korrigiert**: was es reproduziert, wie es läuft - ein Befehl, eine
Reproduktion oder ein UI-Ablauf -, welche Diff-Dateien es abdeckt und den
Versuch vor der Korrektur, der den Fehler zeigt. Nach der Korrektur führt er
**dieselbe** Reproduktion erneut aus und zeichnet den Versuch nach der
Korrektur mit dem auf, was er tatsächlich gesehen hat.

Ein Szenario ist nur dann nachgewiesen, wenn dieselbe Reproduktion vor der
Korrektur fehlschlug und danach bestand, beide Male mit beobachteten Belegen.
Eine Hälfte allein beweist nichts: ein Fehler ohne bestehenden erneuten Lauf
ist ein Fehlerbericht, und ein Bestehen ohne fehlenden Vorlauf hat nie
gezeigt, dass die Korrektur etwas korrigiert hat. Ein Versuch, der lief, aber
nichts bewies - der Befehl scheiterte, bevor er das Verhalten erreichte, das
Bildschirmfoto zeigte den falschen Bildschirm -, ist `inconclusive` und zählt
als keine der beiden Hälften.

Ein Unit-Test-Lauf wird aufgezeichnet, wenn der Agent ihn übergibt, mit der
Belegart `unit_test`, und zählt nie zur Abdeckung. Bei UI-Änderungen sind die
Belege ein Bildschirmfoto oder ein beobachteter UI-Ablauf - die App ausführen
und hinschauen -, kein Komponententest.

## Das Abdeckungsurteil { #the-coverage-verdict }

Bevor er um eine Zusammenführung bittet, ruft der Agent
`proof_scenario_verdict` mit den geänderten Dateien auf, ob die erforderlichen
Checks auf dem aktuellen Head grün sind, wie viele noch ausstehen und wie
viele Review-Befunde noch offen sind. Das Urteil meldet, welche geänderten
Dateien einen beobachteten Nachweis haben und welche nicht:

| Urteil | Bedeutung |
|---|---|
| `proven` | Jede geänderte Datei ist durch ein nachgewiesenes Szenario abgedeckt. |
| `partial` | Einige Dateien sind abgedeckt; der Bericht nennt die übrigen. |
| `unproven` | Keine Datei ist abgedeckt. |
| `no_scenarios` | Es wurde überhaupt nichts aufgezeichnet. |

Derselbe Aufruf meldet die Nachweishälfte des Merge-Gates: Nachweis, Checks
und Befunde. Alle drei müssen gelten, damit das Gate als bereit gilt - ein
Nachweis, der den Diff abdeckt, erforderliche Checks grün ohne ausstehende und
kein offener Review-Befund. Bereit führt trotzdem keine Zusammenführung aus:
Dafür braucht es die ausdrückliche Bitte des Nutzers, auf dem aktuellen Head,
ohne dass noch ein menschliches Review Änderungen verlangt, und mit einem
aktuellen, zusammenführbaren Branch. Niemals `--admin` oder einen anderen
Bypass verwenden.

Wenn sich keine Möglichkeit findet, eine Änderung nachzuweisen, sagt der
Agent das und fragt den Nutzer, statt einen Nachweis zu behaupten, den er
nicht hat. Eine nicht nachgewiesene Änderung, die als nicht nachgewiesen
eingereicht wird, ist ehrliche Arbeit; eine nicht nachgewiesene Änderung, die
als nachgewiesen eingereicht wird, ist es nicht.

## Wo der Nachweis liegt { #where-the-proof-lives }

Szenarien liegen im Run-Manifest, neben den Anfragen und den Korrekturen des
Run-Reviewers, und der Run-Drawer zeigt jedes Szenario mit seinen Versuchen
und ob es nachgewiesen ist. Es gibt keine Migration: Szenarien sind JSONB im
Manifest, keine Tabelle. Ein Run-Manifest hält höchstens zwanzig Szenarien
und sechs Versuche je Szenario, und beobachtete Ausgabe wird vor dem Speichern
gekürzt.

## Was sie bewusst nicht tut { #what-it-deliberately-does-not-do }

- **Keine Zusammenführung, kein Kommentar, keine Aktion an der Änderung.**
  Nur Nachweis und Meldung.
- **Kein Nachweis aus Unit-Tests.** Eine Änderung, deren einziger Beleg eine
  grüne Test-Suite ist, meldet sich als nicht nachgewiesen.
- **Kein erfundener Nachweis.** Was der Agent nicht gesehen hat, hat er nicht
  aufgezeichnet.
- **Kein Ausführen.** Die Capability führt selbst keinen Befehl aus: Der
  Agent führt die Reproduktion aus und übergibt, was er beobachtet hat.
