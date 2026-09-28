---
source_sha: "95d57516d759"
title: "Einen Vertrag gegen Ihre Checkliste prüfen"
description: "Binden Sie einen Erstprüfungs-Skill an einen Agent, hängen Sie einen kurzen synthetischen Dienstleistungsvertrag an und prüfen Sie, dass er beide platzierten Probleme und die fehlende Klausel findet, ohne Rechtsberatung zu geben."
---

# Einen Vertrag gegen Ihre Checkliste prüfen { #review-a-contract-against-your-checklist }

Bauen Sie einen Agent, der einen angehängten Vertrag liest und einen
strukturierten Auszug sowie eine Liste von Abweichungen von einer Checkliste
erstellt — keine Meinung dazu, ob unterschrieben werden soll. Die Testdaten
sind ein kurzer synthetischer Dienstleistungsvertrag mit zwei platzierten
Problemen und einer Klausel, die vollständig fehlt. Dies ist eine Anleitung
zum Durchführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Die Capability **Skills**, gebunden an einen Checklisten-Skill für die
  Prüfung. Diese Seite installiert `legal/document-review-first-pass` aus
  der Gallery — siehe [Skills](../skills.md#getting-skills-into-an-organization),
  um stattdessen einen eigenen zu schreiben. Die Gallery enthält außerdem
  `legal/contract-clause-library`, um eine genehmigte Klausel und ihre
  Fallback-Position nachzuschlagen, sobald Sie eine haben, gegen die geprüft
  werden soll; diese Testdaten brauchen das nicht. Eine fertige
  Agent-Vorlage `legal/contract-reviewer` kombiniert beide.
- Keine Sandbox. Eine angehängte Textdatei wird direkt aus dem Prompt
  gelesen; siehe [Dateiverarbeitung](../file-processing.md#chat-file-uploads).

## Die Eingabe vorbereiten { #prepare-the-input }

Ein kurzer Dienstleistungsvertrag, erfunden für diese Seite, gespeichert als
`services-agreement.txt` und im Chat angehängt:

```text
MASTER SERVICES AGREEMENT

This Agreement is made between Acme Consulting Ltd ("Provider") and Nimbus
Retail Ltd ("Client"), effective 1 January 2027.

1. Term
The initial term is 12 months from the effective date.

2. Services
Provider will deliver monthly analytics reporting as described in Schedule A.

3. Fees and Payment
Client will pay Provider 5,000 EUR per month, payable within 30 days of
invoice.

4. Confidentiality
Each party will keep the other's confidential information confidential
during the term and for 3 years after termination.

5. Liability
Each party's liability under this Agreement is unlimited.

6. Termination
Either party may terminate this Agreement for uncured material breach on 30
days' written notice.

7. Renewal
This Agreement automatically renews for successive 12-month terms.

8. Assignment
Neither party may assign this Agreement without the other party's prior
written consent.
```

Zwei platzierte Probleme: Klausel 5 begrenzt nichts (unbegrenzte Haftung), und
Klausel 7 verlängert sich automatisch, ohne ein Kündigungsfenster, um das zu
stoppen. Eine Klausel fehlt vollständig: Nirgends im Vertrag wird ein
anwendbares Recht oder ein Gerichtsstand genannt.

## Den Agent bauen { #build-the-agent }

1. Installieren Sie unter **Skills → Skill gallery** `Document review first
   pass` aus dem Bereich legal.
2. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr
   Modellprofil.
3. Aktivieren Sie unter **Toolbox** **Skills** und binden Sie den Skill, den
   Sie gerade installiert haben.
4. Setzen Sie die folgenden Instruktionen und klicken Sie dann auf
   **Publish**.

```text
You produce a structured extract and a list of deviations from the bound
review checklist skill. You do not advise, do not conclude a clause is
acceptable, and do not redraft. Everything you produce is checked by the
person who reviews it before it is relied on.

Use the Document review first pass skill for what to extract and how to flag
deviations. Cite the clause number for every extracted term and every
deviation. Flag anything the checklist expects that the agreement does not
contain.
```

## Ausführen { #run-it }

Hängen Sie `services-agreement.txt` in einer neuen Konversation an und
senden Sie:

```text
Review this services agreement against the checklist.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Haftung | Als Abweichung markiert — keine Begrenzung, Kl. 5 |
| Verlängerung | Als Abweichung markiert — kein Kündigungsfenster, Kl. 7 |
| Anwendbares Recht und Gerichtsstand | Als vollständig fehlend markiert, nicht erfunden |
| Jeder extrahierte Begriff und jede Abweichung | Nennt eine Klauselnummer |
| Tonfall | Nennt Fakten und Abweichungen; schließt nicht, dass der Vertrag sicher, riskant oder unterschriftsreif ist |
| Eine Frage, ob unterschrieben werden soll | Lehnt eine Beratung ab und verweist zurück auf den Sachbearbeiter, der die Ausgabe prüft |

Lesen Sie die Abweichungen selbst gegen die Quellklauseln. Eine Abweichung,
die die falsche Klauselnummer zitiert, oder eine Liste fehlender Klauseln,
die einen Punkt erfindet, den der Vertrag tatsächlich enthält, wirken im
Chat beide gründlich.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Auszug nannte die Haftung
    aus Kl. 5 als „unlimited" mit „no exclusion of indirect/consequential
    loss," die Verlängerung aus Kl. 7 als ohne „opt-out/break notice
    mechanism," und führte „Governing law & jurisdiction" sowohl unter den
    Abweichungen als auch in einer separaten Tabelle fehlender Punkte auf,
    neben Freistellungen (indemnities) und Kontrollwechsel (change of
    control) — Punkte, die die Checkliste erwartet, die dieser kurze
    Testvertrag nie enthielt. Er schloss mit der Feststellung, dass der
    Auszug „requires verification by the fee earner responsible for this
    matter before being relied upon." Kosten: 0,0249 USD.

    Der erste Versuch scheiterte, bevor irgendetwas entstand: Das Modell rief
    `load_capability` mit der geratenen id `document-review-first-pass` auf
    (mit Bindestrichen, passend zur eigenen Benennung der Gallery), die
    nicht existiert — die id eines gebundenen Skills ist sein exakter
    gespeicherter Name, „Document review first pass" — versuchte es erneut
    mit einer zweiten falschen Vermutung, und der Run endete mit „the agent
    could not finish this turn," für 0,0083 USD, ausgegeben für die zwei
    Vermutungen. Ein neuer Versuch in einer neuen Konversation verwendete
    beim ersten Aufruf die richtige id. Ein erneuter Versuch ist die
    praktische Lösung; rät das Modell weiterhin falsch, entfernt das Nennen
    des Skills mit seinem exakten gespeicherten Namen in den Instruktionen
    das Raten vollständig.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Run scheitert mit „could not finish this turn," bevor irgendeine
  Ausgabe entsteht.** Siehe den festgehaltenen Run oben — ein Modellaufruf
  von `load_capability` riet die id des Skills, statt sie aus dem Katalog zu
  übernehmen. Versuchen Sie es in einer neuen Konversation erneut, oder
  nennen Sie den exakten Namen des Skills in den Instruktionen.
- **Der Agent sagt Ihnen, ob Sie unterschreiben sollen.** Verschärfen Sie
  „you do not advise" und testen Sie es direkt mit einer Anschlussfrage —
  ein Checklisten-Tool, das „yes, this is fine" antwortet, sobald jemand
  fragt, beantwortet mehr, als sein Auftrag vorsieht.
- **Eine Abweichung hat keine Klauselnummer.** Die Instruktionen verlangen
  eine bei jedem Punkt; ein fehlendes Zitat bei einem sonst korrekten Befund
  ist trotzdem markierenswert, da der nächste Leser es sonst nicht prüfen
  kann.
- **Die Liste fehlender Klauseln erfindet etwas, das der Vertrag enthält.**
  Lesen Sie die Quelle direkt. Die Checkliste erwartet etwa ein Dutzend
  Standardpunkte; kurzen Testdaten fehlen immer mehrere, und das Modell muss
  die tatsächlich fehlenden richtig benennen, statt nur eine lange Liste zu
  erzeugen.
- **Zwei Agents, die an denselben Skill gebunden sind, liefern
  unterschiedliche Checklisten.** Der Skill ist eine Zeile, geteilt nach
  Namen; prüfen Sie unter **Skills**, dass niemand einen unveröffentlichten
  Vorschlag dafür offen hat. Siehe
  [ein Agent kann eine Änderung vorschlagen; eine Person setzt sie um](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie den exakten Vertragstext, die Antwort, die Agent-Version, die
eigene Version des Skills und das Modell auf. Eine Person prüft weiterhin
jedes Zitat gegen die Quelle und entscheidet, was mit jeder Abweichung
geschieht — der Auftrag des Agents ist, sie sichtbar zu machen, nicht sie zu
klären.

## Nächste Schritte { #next-steps }

Fügen Sie `legal/contract-clause-library` hinzu, sobald Sie eine genehmigte
Position haben, gegen die Klauseln geprüft werden — dann kann eine Abweichung
mit dem tatsächlichen Fallback gemeldet werden statt nur mit „this differs
from standard." Für einen längeren Vertrag mit mehreren gegenzuprüfenden
Dokumenten beantwortet [Knowledge search](knowledge-base-assistant.md) eine
andere Frage als diese Seite: das Abrufen einer Passage aus einem großen
Korpus statt das durchgehende Prüfen eines einzelnen angehängten Dokuments.
