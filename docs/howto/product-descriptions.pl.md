---
source_sha: "dfc8e7b908eb"
title: "Napisz opisy produktów z pliku katalogu"
description: "Załącz mały syntetyczny products.csv i niech agent napisze po jednym opisie oferty na wiersz, oznaczając wiersz bez wymaganego atrybutu, zamiast go wymyślać."
---

# Napisz opisy produktów z pliku katalogu { #write-product-descriptions-from-a-catalogue-file }

Załącz mały plik katalogu do zwykłego agenta czatu z przypisanym skillem do tekstów ofert i sprawdź, czy pisze jeden opis na produkt, nie wymyślając niczego, czego nie ma w specyfikacji. W jednym wierszu celowo brakuje wymaganego atrybutu, więc możesz sprawdzić, czy agent oznaczy lukę, zamiast ją uzupełnić. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Bez sandboksa i modelu embeddingów. Wystarczy zwykły agent czatu z [capability skills](../reference/capabilities.md#skills), a CSV jest na tyle mały, że trafi do promptu jako tekst.
- Opcjonalnie do przeczytania: **Skills → Skill gallery → e-commerce** ma skill `Product description writer` z tymi samymi zasadami, których używa ta strona, a szablon agenta `ecommerce/listing-writer` z tej samej galerii pokazuje pełniejszego agenta zbudowanego wokół niego, z dodaną wiedzą i połączeniami MCP. Skill z tej strony powstał na podstawie treści tamtego wpisu.

## Przygotuj dane wejściowe { #prepare-the-input }

Zapisz to jako `products.csv`. Cztery wiersze są kompletne, a kolumna `material` dla `FW-104` jest celowo pusta. To właśnie tę lukę ma sprawdzić przykład.

```csv
sku,name,category,material,size_run,weight_g,fit_note,care,box_contents
FW-101,Harbor Rain Jacket,Outerwear,recycled nylon 100%,S-XXL,410,true to size,machine wash cold,jacket and stuff sack
FW-102,Harbor Wool Beanie,Accessories,merino wool 100%,one size,80,one size fits most,hand wash cold,beanie only
FW-103,Harbor Steel Water Bottle,Drinkware,stainless steel,650 ml,320,not applicable,dishwasher safe lid only,bottle and lid
FW-104,Harbor Canvas Tote,Bags,,38 x 42 x 10 cm,260,not applicable,spot clean,tote bag only
FW-105,Harbor Trail Socks (2-pack),Apparel,merino wool blend 60%,S/M and L/XL,60,true to size,machine wash cold,two pairs of socks
```

Zapisz to jako skill w **Skills → New skill** pod nazwą `listing-copy-from-spec`, na podstawie `ecommerce/product-description-writer` z galerii:

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

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Skills** i przypisz `listing-copy-from-spec`.
3. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You write product listing descriptions from an attached catalogue file.
Follow the bound listing-copy-from-spec skill for shape and rules.
Write one description per row of the attached CSV.
If a row is missing an attribute the skill says to always include, do not
invent it: name it as missing in that product's description instead.
Return the result as a markdown table: sku, name, then the description.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem, załącz `products.csv` i wyślij:

```text
Write listing descriptions for every product in the attached catalogue.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Liczba wierszy | Pięć opisów, po jednym na SKU |
| Liczby | Waga, wymiary i pojemności dokładnie zgadzają się z CSV, z jednostkami |
| Brakujący materiał w FW-104 | Oznaczony w tym opisie jako brakujący, bez podania materiału |
| Informacja o rozmiarze | Przy FW-101, FW-102 i FW-105, czyli trzech rzeczach do noszenia |
| Atrybuty, których nigdy się nie podaje | Nigdzie żadnego certyfikatu, kraju pochodzenia, korzyści zdrowotnej ani deklaracji zgodności |
| To samo polecenie bez załączonego pliku | Agent mówi, że brakuje pliku, i nie wymyśla katalogu |

Najpierw sprawdź FW-104. Brakujący atrybut uzupełniony po cichu to dokładnie ten błąd, który ma wychwycić ten przykład.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wczytał przypisany skill, a potem w jednej odpowiedzi napisał pięć opisów, po jednym na wiersz. Każda liczba (650 ml, 320 g, 38 x 42 x 10 cm, 60% merino, S/M i L/XL) zgadzała się z CSV. Dla FW-104 napisał „Material composition is not specified in the product data and has not been stated in this listing”, zamiast podać tkaninę. Informacje o rozmiarze pojawiły się przy kurtce, czapce i skarpetach. Nigdzie nie pojawiły się deklaracje certyfikatu, pochodzenia ani zdrowia. Koszt: 0,053 USD.

    Bez załączonego pliku agent i tak wczytał skill, a potem napisał „I don't see any attached catalogue file or CSV in your message” i poprosił o plik, zamiast pisać opisy z niczego.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Dla FW-104 zostaje wymyślony materiał albo wymiar.** Sekcja „Never” skilla jest ignorowana. Powtórz to polecenie w polu instrukcji samego agenta, a nie tylko w skillu.
- **Agent wywołuje `load_capability` z błędnym id i tura kończy się błędem.** Zdarzyło się to podczas weryfikacji, gdy skill był przypisany pod dokładną nazwą i wielkością liter z wpisu w galerii (`Product description writer`). Model dwa razy zgadł inne id, a tura zakończyła się `UnexpectedModelBehavior` zamiast zwykłej odmowy. Odtworzenie tej samej treści jako nowego skilla pod prostą nazwą małymi literami z myślnikami rozwiązywało problem przy każdej ponownej próbie. Podanie dokładnej zapisanej nazwy skilla w instrukcjach agenta usuwa zgadywanie, jak opisuje [przegląd umowy](contract-review.md). Jeśli skill zainstalowany z galerii nadal to powoduje, skopiuj jego treść do nowego skilla o prostej nazwie.
- **Brakuje informacji o rozmiarze przy rzeczy do noszenia.** Zapytaj, który atrybut sekcja „Always include” skilla wymienia dla tego wiersza. Brak informacji o rozmiarze to przyczyna zwrotów, której skill ma zapobiegać.
- **Odpowiedź pomija wiersz.** Poproś o liczbę wierszy, zanim zaufasz tabeli: pięć wierszy na wejściu, pięć opisów na wyjściu.

## Zapisz próbę { #record-the-trial }

Zachowaj CSV, treść skilla, pięć opisów, wersję agenta i run w Activity. Jeśli zdarzy się run, w którym brakujący atrybut został wymyślony, zachowaj też jego. To najwyraźniejszy dowód, że sformułowanie skilla trzeba zaostrzyć.

Człowiek nadal decyduje, czy opis nadaje się do publikacji, i przed uruchomieniem oferty zajmuje się oznaczoną luką. Powyższe sprawdzenie wychwytuje wymyślony fakt, a nie nudny opis.

## Kolejne kroki { #next-steps }

Dla katalogu na żywo przypisz [kolekcję wiedzy](set-up-knowledge-base.md) ze specyfikacjami od dostawców zamiast wklejać wiersze i dodaj skill `ecommerce/review-response` z tej samej półki galerii, żeby odpowiadać na pytania klientów o produkt z tą samą dyscypliną źródeł.
