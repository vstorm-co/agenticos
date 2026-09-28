---
source_sha: "dfc8e7b908eb"
title: "Produktbeschreibungen aus einer Katalogdatei schreiben"
description: "Hängen Sie eine kleine synthetische products.csv an und lassen Sie einen Agent eine Angebotsbeschreibung pro Zeile schreiben, wobei die Zeile mit fehlendem Pflichtattribut markiert statt ergänzt wird."
---

# Produktbeschreibungen aus einer Katalogdatei schreiben { #write-product-descriptions-from-a-catalogue-file }

Hängen Sie eine kleine Katalogdatei an einen einfachen Chat-Agent an, der an einen Skill für Angebotstexte gebunden ist, und prüfen Sie, dass er eine Beschreibung pro Produkt schreibt, ohne etwas zu erfinden, das nicht im Datenblatt steht. In einer Zeile fehlt absichtlich ein Pflichtattribut, damit Sie prüfen können, ob der Agent die Lücke markiert, statt sie zu füllen. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Sandbox und kein Embedding-Modell. Ein einfacher Chat-Agent mit der [Skills-Capability](../reference/capabilities.md#skills) genügt; die CSV ist klein genug, um als Text in den Prompt eingefügt zu werden.
- Optional zum Lesen: **Skills → Skill gallery → e-commerce** hat einen Skill `Product description writer` mit denselben Regeln, die diese Seite nutzt, und die Agent-Vorlage `ecommerce/listing-writer` aus derselben Galerie zeigt einen vollständigeren Agent, der darum herum gebaut ist, mit zusätzlichem Wissen und MCP-Verbindungen. Der Skill dieser Seite basiert auf dem Inhalt dieses Eintrags.

## Die Eingabe vorbereiten { #prepare-the-input }

Speichern Sie dies als `products.csv`. Vier Zeilen sind vollständig; die Spalte `material` von `FW-104` ist absichtlich leer. Genau diese Lücke soll das Beispiel prüfen.

```csv
sku,name,category,material,size_run,weight_g,fit_note,care,box_contents
FW-101,Harbor Rain Jacket,Outerwear,recycled nylon 100%,S-XXL,410,true to size,machine wash cold,jacket and stuff sack
FW-102,Harbor Wool Beanie,Accessories,merino wool 100%,one size,80,one size fits most,hand wash cold,beanie only
FW-103,Harbor Steel Water Bottle,Drinkware,stainless steel,650 ml,320,not applicable,dishwasher safe lid only,bottle and lid
FW-104,Harbor Canvas Tote,Bags,,38 x 42 x 10 cm,260,not applicable,spot clean,tote bag only
FW-105,Harbor Trail Socks (2-pack),Apparel,merino wool blend 60%,S/M and L/XL,60,true to size,machine wash cold,two pairs of socks
```

Speichern Sie dies als Skill unter **Skills → New skill** mit dem Namen `listing-copy-from-spec`, angepasst aus `ecommerce/product-description-writer` der Galerie:

```text
Copy that describes a product the customer does not receive is the most
expensive sentence in e-commerce.

## Work only from the spec

Every claim traces to the spec sheet, the supplier data or a photograph. If
the material is not stated, the description does not name a material.

## The shape

One line saying what it is and who it is for; three to five bullets of
concrete attributes with numbers; one short paragraph on use; then the full
specification as given.

## Concrete beats enthusiastic

"320 gsm, pre-shrunk, fits true to size" outperforms "premium quality".
Numbers survive translation, reduce returns and answer the question that
would otherwise become a support ticket.

## Always include

Dimensions with units, materials, care, what is in the box, and — for
anything worn — the fit note. Missing fit information is the single largest
driver of apparel returns.

## Never

Claim a certification, a country of origin, a health benefit or a
compatibility that the source does not state.
```

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Skills** und binden Sie `listing-copy-from-spec`.
3. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You write product listing descriptions from an attached catalogue file.
Follow the bound listing-copy-from-spec skill for shape and rules.
Write one description per row of the attached CSV.
If a row is missing an attribute the skill says to always include, do not
invent it: name it as missing in that product's description instead.
Return the result as a markdown table: sku, name, then the description.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent, hängen Sie `products.csv` an und senden Sie:

```text
Write listing descriptions for every product in the attached catalogue.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Anzahl der Zeilen | Fünf Beschreibungen, eine pro SKU |
| Zahlen | Gewichte, Maße und Volumina stimmen genau mit der CSV überein, mit Einheiten |
| Fehlendes Material bei FW-104 | In dieser Beschreibung als fehlend markiert, kein Material genannt |
| Passformhinweis vorhanden | Bei FW-101, FW-102 und FW-105, den drei tragbaren Artikeln |
| Nie behauptete Attribute | Nirgends ein Zertifikat, Herkunftsland, Gesundheitsnutzen oder eine Kompatibilitätsaussage |
| Dieselbe Anfrage ohne angehängte Datei | Der Agent sagt, dass die Datei fehlt, und erfindet keinen Katalog |

Prüfen Sie zuerst FW-104. Ein fehlendes Attribut, das still ergänzt wurde, ist genau der Fehler, den dieses Beispiel erkennen soll.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent lud den gebundenen Skill und schrieb dann in einer Antwort fünf Beschreibungen, eine pro Zeile. Jede Zahl (650 ml, 320 g, 38 x 42 x 10 cm, 60 % Merino, S/M und L/XL) stimmte mit der CSV überein. Für FW-104 schrieb er "Material composition is not specified in the product data and has not been stated in this listing", statt einen Stoff zu nennen. Passformhinweise erschienen bei der Jacke, der Mütze und den Socken; nirgends tauchte eine Zertifikats-, Herkunfts- oder Gesundheitsaussage auf. Kosten: 0,053 USD.

    Ohne angehängte Datei lud der Agent trotzdem den Skill, schrieb dann "I don't see any attached catalogue file or CSV in your message" und bat um die Datei, statt Beschreibungen aus dem Nichts zu schreiben.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Für FW-104 wird ein Material oder ein Maß erfunden.** Der Abschnitt "Never" des Skills wird ignoriert. Wiederholen Sie die Anweisung im Instruktionsfeld des Agents selbst, nicht nur im Skill.
- **Der Agent ruft `load_capability` mit der falschen ID auf, und die Runde endet mit einem Fehler.** Das geschah bei der Prüfung, als der Skill unter genau dem Namen und der Schreibweise des Galerie-Eintrags (`Product description writer`) gebunden war: Das Modell riet zweimal eine andere ID, und die Runde endete mit `UnexpectedModelBehavior` statt einer normalen Ablehnung. Denselben Inhalt als neuen Skill unter einem schlichten, kleingeschriebenen Namen mit Bindestrichen anzulegen, behob es bei jedem neuen Versuch. Den genauen gespeicherten Namen des Skills in den Instruktionen des Agents zu nennen, beseitigt das Raten, wie [Vertragsprüfung](contract-review.md) beschreibt. Wenn ein aus der Galerie installierter Skill trotzdem daran scheitert, kopieren Sie seinen Inhalt in einen neuen Skill mit einem schlichten Namen.
- **Bei einem tragbaren Artikel fehlt der Passformhinweis.** Fragen Sie, welches Attribut der Abschnitt "Always include" des Skills für diese Zeile nennt. Ein fehlender Passformhinweis ist der Rücksendegrund, den der Skill verhindern soll.
- **Die Antwort überspringt eine Zeile.** Fragen Sie nach der Zeilenzahl, bevor Sie der Tabelle vertrauen: fünf Zeilen hinein, fünf Beschreibungen heraus.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die CSV, den Skill-Inhalt, die fünf Beschreibungen, die Agent-Version und den Run in Activity auf. Bewahren Sie auch einen Run auf, in dem das fehlende Attribut erfunden wurde, falls es dazu kommt. Er ist der deutlichste Beleg, dass die Formulierung des Skills verschärft werden muss.

Ein Mensch entscheidet weiterhin, ob eine Beschreibung veröffentlichungsreif ist, und kümmert sich um die markierte Lücke, bevor das Angebot online geht. Die Prüfung oben erkennt eine erfundene Tatsache, keine langweilige Beschreibung.

## Nächste Schritte { #next-steps }

Für einen echten Katalog binden Sie eine [Wissenssammlung](set-up-knowledge-base.md) mit Datenblättern der Lieferanten, statt Zeilen einzufügen, und fügen Sie den Skill `ecommerce/review-response` aus demselben Galerie-Regal hinzu, um Kundenfragen zu einem Produkt mit derselben Quellendisziplin zu beantworten.
