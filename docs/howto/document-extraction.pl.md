---
source_sha: "d1faa4de619f"
title: "Wyciągnij dane z faktur do arkusza"
description: "Załącz trzy syntetyczne faktury PDF, niech agent przeczyta je w sandboksie i zapisze CSV ze stałymi kolumnami, a potem sprawdź, czy fakturę z brakującym polem oznaczył, zamiast je uzupełnić."
---

# Wyciągnij dane z faktur do arkusza { #extract-invoice-data-into-a-spreadsheet }

Zbuduj agenta, który czyta paczkę faktur i zapisuje jeden plik CSV z tymi samymi kolumnami w każdym wierszu. Przykładem są trzy małe syntetyczne faktury, z których jedna nie ma daty, więc liczy się to, czy agent zgłosi brak, zamiast wymyślić wiarygodnie wyglądającą datę. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu i zarejestrowanym [połączeniem sandboksa](../sandbox.md) z runtime'em `workbench`, który ma `liteparse` (`lit`) i `pdftotext` do czytania PDF-ów oraz środowisko Pythona do zapisania CSV.
- Bez wiedzy i bez wykresów.

## Przygotuj dane wejściowe { #prepare-the-input }

Trzy krótkie faktury, wygenerowane jako PDF-y, żeby przykład wyglądał jak prawdziwy upload. Zapisz ten skrypt jako `make_invoices.py` w katalogu roboczym:

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

def draw_invoice(path, number, date, vendor, lines, tax_rate, include_date=True):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 30 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "INVOICE")
    y -= 10 * mm
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, y, f"Invoice number: {number}")
    y -= 6 * mm
    if include_date:
        c.drawString(20 * mm, y, f"Date: {date}")
        y -= 6 * mm
    c.drawString(20 * mm, y, f"Vendor: {vendor}")
    y -= 6 * mm
    c.drawString(20 * mm, y, "Bill to: Meridian Analytics BV")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Description")
    c.drawString(130 * mm, y, "Qty")
    c.drawString(150 * mm, y, "Amount")
    y -= 6 * mm
    c.setFont("Helvetica", 11)
    subtotal = 0.0
    for desc, qty, amount in lines:
        c.drawString(20 * mm, y, desc)
        c.drawString(130 * mm, y, str(qty))
        c.drawString(150 * mm, y, f"{amount:.2f}")
        subtotal += amount
        y -= 6 * mm
    y -= 4 * mm

    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    c.drawString(120 * mm, y, "Subtotal:")
    c.drawString(150 * mm, y, f"{subtotal:.2f} EUR")
    y -= 6 * mm
    c.drawString(120 * mm, y, f"Tax ({int(tax_rate*100)}%):")
    c.drawString(150 * mm, y, f"{tax:.2f} EUR")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(120 * mm, y, "Total:")
    c.drawString(150 * mm, y, f"{total:.2f} EUR")
    c.showPage()
    c.save()
    return subtotal, tax, total

s1 = draw_invoice("INV-1001.pdf", "INV-1001", "2027-01-15", "Nordic Office Supplies",
                   [("Desk chairs, ergonomic", 3, 420.00), ("Standing desks", 2, 260.00)], 0.21)
print("INV-1001", s1)

s2 = draw_invoice("INV-1002.pdf", "INV-1002", "2027-01-22", "Blue Ridge Logistics",
                   [("Freight, Rotterdam-Warsaw", 1, 780.00), ("Customs handling", 1, 195.00)], 0.21)
print("INV-1002", s2)

s3 = draw_invoice("INV-1003.pdf", "INV-1003", None, "Summit Cleaning Services",
                   [("Monthly office cleaning, January", 1, 227.27)], 0.21, include_date=False)
print("INV-1003", s3)
```

Potem uruchom go tam. Zapisze obok siebie `INV-1001.pdf`, `INV-1002.pdf` i `INV-1003.pdf`:

```bash
uv run --with reportlab python make_invoices.py
```

`make_invoices.py` rysuje każdą fakturę za pomocą `reportlab`: numer faktury, dostawcę, tabelę pozycji, sumę netto, podatek 21% i sumę brutto. `INV-1001` i `INV-1002` są kompletne, a `INV-1003` celowo nie ma w ogóle linii z datą.

Wartości referencyjne do sprawdzenia wyciągu:

| Faktura | Data | Dostawca | Netto | Podatek | Brutto |
| --- | --- | --- | --- | --- | --- |
| INV-1001 | 2027-01-15 | Nordic Office Supplies | 680.00 | 142.80 | 822.80 |
| INV-1002 | 2027-01-22 | Blue Ridge Logistics | 975.00 | 204.75 | 1179.75 |
| INV-1003 | *(brak)* | Summit Cleaning Services | 227.27 | 47.73 | 275.00 |

Każda suma brutto to netto plus 21% podatku, więc błędną sumę da się sprawdzić ręcznie.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Sandbox**. Wybierz **Container**, swoje połączenie sandboksa i runtime `workbench`.
3. Ustaw budżet i limit kroków. Przeczytanie trzech krótkich PDF-ów i zapisanie jednego CSV to kilka wywołań narzędzi.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You extract structured data from attached invoices.
Read each invoice from the workspace before extracting anything - use lit
or pdftotext to get its text; do not guess from the filename.
Write invoices.csv in the workspace with exactly these columns: invoice_number,
date, vendor, subtotal, tax, total, currency.
If a field is not present on an invoice, leave that cell empty and name the
invoice and the missing field in your reply. Never invent a value that is
not on the document.
Check that subtotal plus tax equals total for each invoice, and say so if one
does not.
```

## Uruchom { #run-it }

Załącz `INV-1001.pdf`, `INV-1002.pdf` i `INV-1003.pdf` do nowej rozmowy i wyślij:

```text
Extract the invoice data from these three files into invoices.csv, with one row per invoice.
```

Odczytanie tekstu PDF-a na runtime'ie `workbench` uruchamia `lit` albo `pdftotext` przez `execute`, które prosi o zatwierdzenie tak samo jak polecenie powłoki w [Zamień CSV na wykres, który możesz sprawdzić](csv-chart.md#run-it). Przeczytaj polecenie, a potem **Approve**. Samo zapisanie CSV nie wymaga zatwierdzenia. Agent może w tej samej turze zaparkować na `execute` więcej niż raz. Jednym z możliwych przebiegów jest pierwsza próba, która zapisuje wynik `lit` do pliku poza workspace'em, i druga, która wypisuje go od razu na wyjście polecenia. Zobacz zapisany run poniżej.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Wiersze w `invoices.csv` | Trzy, po jednym na fakturę, te same siedem kolumn w tej samej kolejności |
| INV-1001 i INV-1002 | Każde pole dokładnie zgadza się z tabelą referencyjną |
| Komórka z datą dla INV-1003 | Pusta, a nie zgadnięta albo wymyślona data |
| Odpowiedź | Wymienia `INV-1003` i „date” jako brakujące, a nie tylko zostawia pustą komórkę |
| Sumy | W każdym wierszu netto plus podatek równa się brutto. Agent mówi o tym, jeśli sprawdzał, a któraś się nie zgadza |
| Czwarty plik, który w ogóle nie jest fakturą | Agent mówi, że nie dał rady wyciągnąć z niego pól faktury, zamiast wymyślić wiersz |

Otwórz `invoices.csv` z workspace'u i sprawdź go bezpośrednio. Odpowiedź, która prozą podaje właściwe liczby, podczas gdy plik zawiera coś innego, to luka widoczna tylko w samym pliku.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, runtime `workbench`. Pierwsze wywołanie `execute` uruchomiło `lit parse <file> -o /tmp/inv*.md` dla wszystkich trzech PDF-ów, a potem agent spróbował `read_file` na `/tmp/inv1001.md` i dwóch pozostałych. Wszystkie trzy próby się nie udały, bo `/tmp` jest poza workspace'em, do którego sięga `read_file`, choć samo `execute` może tam pisać. Agent poradził sobie sam: drugie wywołanie `execute` ponownie uruchomiło `lit parse` dla wszystkich trzech plików bez `-o`, wypisując wynik na wyjście polecenia, które agent odczytał bezpośrednio z wyniku narzędzia. Oba wywołania `execute` wymagały osobnych zatwierdzeń w tej samej turze.

    `invoices.csv` zawierał wszystkie trzy wiersze i kolumny referencyjne. Każde pole INV-1001 i INV-1002 dokładnie zgadzało się ze źródłowymi PDF-ami, a komórka `date` dla INV-1003 była pusta. Odpowiedź wymieniła „`INV-1003` — `date`” jako brakujące pole. Przed zakończeniem agent sam sprawdził arytmetykę jednorazowym `execute`: `python3 -c "..."` odczytał CSV i porównał netto plus podatek z sumą brutto, a następnie zgłosił, że wszystkie trzy wiersze się zgadzają. Łączny koszt runu: 0,1302 USD, przy 37 246 tokenach wejściowych i 1233 wyjściowych.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent zgaduje datę dla INV-1003.** Instrukcje każą zostawić komórkę pustą i nazwać brak. Jeśli i tak ją uzupełnia, dopisz „do not infer a date from context” i przetestuj ponownie z tym samym plikiem.
- **Run zatrzymuje się po przeczytaniu plików.** Czeka na zatwierdzenie `execute` dla `lit` albo `pdftotext`. Otwórz czat albo **Approvals** w **Activity**. W tej samej turze może zaparkować dwa razy; zobacz zapisany run powyżej.
- **`read_file` nie działa na ścieżce, którą właśnie zapisał `lit`.** `execute` może pisać w dowolnym miejscu kontenera, także poza `/workspace`, ale `read_file` jest ograniczone do workspace'u. Niech agent wypisuje wynik parsowania na wyjście polecenia albo zapisuje plik `-o` z `lit` w workspace'ie, a nie w `/tmp`.
- **Suma różni się o kwotę podatku.** Sprawdź, czy agent przeczytał sumę wydrukowaną na fakturze, czy przeliczył ją sam. Tak mały przykład nigdy nie powinien wymagać przeliczania, a rozbieżność zwykle oznacza źle odczytaną pozycję.
- **CSV za każdym razem ma inne kolumny.** Instrukcje nazywają je dokładnie. Jeśli model nadal zmienia kolejność albo dodaje kolumnę, podaj je jako dosłowną linię nagłówka, a nie prozą.
- **PDF ze zeskanowaną stroną czyta się jako pusty.** `lit` robi OCR tylko dla strony bez warstwy tekstowej, a skan kosztuje kilka sekund na stronę. Zanim skierujesz tego agenta na zeskanowane faktury zamiast wygenerowanych, przeczytaj [co jest w runtime'ie, a czego celowo nie ma](../sandbox.md#what-is-in-it-and-what-is-deliberately-not).

## Zapisz próbę { #record-the-trial }

Zachowaj trzy źródłowe PDF-y, dokładny prompt, wersję agenta, zatwierdzone wywołania `execute` z Activity i wynikowy `invoices.csv`, a nie tylko odpowiedź w czacie. Człowiek nadal sprawdza zgłoszony brak ze źródłowym PDF-em i decyduje, co z nim zrobić. Zadaniem agenta jest go wskazać, a nie rozwiązać.

## Kolejne kroki { #next-steps }

Gdy to działa na paczce trzech faktur, dodawaj po jednej trudności naraz: czwartą fakturę w innej walucie albo z innym układem, tak jak dla własnego przykładu proponuje [Zamień CSV na wykres, który możesz sprawdzić](csv-chart.md).
