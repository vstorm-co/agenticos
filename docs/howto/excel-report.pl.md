---
source_sha: "5b846962a129"
title: "Zbuduj raport w Excelu i prezentację z danych"
description: "Załącz mały syntetyczny CSV i niech agent w sandboksie przygotuje skoroszyt z formułami i wykresem oraz prezentację z trzech slajdów, a potem otwórz oba pliki i sprawdź liczby."
---

# Zbuduj raport w Excelu i prezentację z danych { #build-an-excel-report-and-a-slide-deck-from-data }

Daj agentowi sandbox i mały plik CSV ze sprzedażą, a potem niech zbuduje skoroszyt z arkuszem podsumowania opartym na formułach i wykresem, a następnie prezentację z trzech slajdów z tymi samymi liczbami. Przykład jest na tyle mały, że zsumujesz go ręcznie, więc każdą komórkę sprawdzisz z wierszami źródła. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia. Jeśli potrzebujesz tylko raportu, zacznij od [Zamień CSV na wykres, który możesz sprawdzić](csv-chart.md). Ta strona dokłada do tego wzorca pełny skoroszyt i prezentację.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu i zarejestrowanym [połączeniem sandboksa](../sandbox.md), którego domyślnym runtime'em jest `workbench`. Ma on `openpyxl` i `python-pptx`, więc nie trzeba niczego doinstalowywać.
- Syntetyczny CSV poniżej, na tyle mały, że sprawdzisz go ręcznie.

## Przygotuj dane wejściowe { #prepare-the-input }

Zapisz to jako `sales.csv`. Cztery kwartały, cztery regiony, szesnaście wierszy.

```csv
quarter,region,revenue_usd,units
Q1,North,12000,300
Q1,South,9000,250
Q1,East,15000,320
Q1,West,8000,200
Q2,North,13000,310
Q2,South,9500,260
Q2,East,16000,330
Q2,West,8500,210
Q3,North,14000,320
Q3,South,10000,270
Q3,East,17000,340
Q3,West,9000,220
Q4,North,15000,330
Q4,South,10500,280
Q4,East,18000,350
Q4,West,9500,230
```

Sumy referencyjne policzone ręcznie: według regionów North 54 000, South 39 000, East 66 000, West 35 000; według kwartałów Q1 44 000, Q2 47 000, Q3 50 000, Q4 53 000; suma całkowita 194 000.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Files & shell**. Wybierz **Container**, swoje połączenie sandboksa i runtime `workbench`, a zakres zostaw na poziomie rozmowy.
3. Ustaw budżet na czas próby, a potem wpisz poniższe instrukcje i kliknij **Publish**.

```text
You build spreadsheets and slide decks in your workspace from data the user
attaches.
Read the attached file before calculating anything.
Use openpyxl to build the workbook and python-pptx to build the deck.
Save every output file in the workspace and give its path.
Do not fetch data from the internet.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem, załącz `sales.csv` i wyślij:

```text
Using the attached CSV, build report.xlsx with a summary sheet totalling
revenue by region and by quarter (use SUM formulas over a raw-data sheet, not
hand-typed numbers) plus a bar chart of revenue by region. Then build a
3-slide summary.pptx: a title slide, a slide with the totals table, and a
slide with the chart or its key numbers. Save both files in the workspace.
```

Gdy agent uruchamia swój skrypt, czat pokazuje **Tool approval required**. Przeczytaj polecenie, a potem **Approve**. Zobacz [zatwierdzenia](../governance.md#approvals).

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Sumy regionów | North 54 000, South 39 000, East 66 000, West 35 000 |
| Sumy kwartałów | Q1 44 000, Q2 47 000, Q3 50 000, Q4 53 000 |
| Suma całkowita | 194 000 |
| Arkusz podsumowania używa formuł | Kliknij komórkę z sumą i zobacz `=SUM(...)`, a nie wpisaną liczbę |
| Wykres | Słupki dla regionów, oś opisana walutą |
| Prezentacja | Trzy slajdy: tytuł, tabela sum, wykres albo kluczowe liczby |
| Liczby w skoroszycie i prezentacji się zgadzają | Sumy w prezentacji są równe sumom ze skoroszytu, a nie osobno zaokrąglone |

Otwórz `report.xlsx` i `summary.pptx` z panelu plików czatu i sprawdź je sam. Ścieżka w odpowiedzi nie dowodzi, że plik istnieje ani że jego formuły liczą właściwą wartość.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent przeczytał CSV, napisał skrypt budujący z 460 linii i go uruchomił: jedno wywołanie `execute`, zatwierdzone. Potem wykonał jeszcze trzy wywołania `execute`, żeby przekonwertować prezentację przez LibreOffice na obrazy PNG dla każdego slajdu i obejrzeć własną pracę. Każde zatwierdzono po kolei.

    `report.xlsx` zawierał arkusz `Raw Data` ze wszystkimi 16 wierszami i arkusz `Summary`, w którym każda komórka regionu i kwartału była działającą formułą `SUMPRODUCT` odwołującą się do `Raw Data`, z sumami wierszy i kolumn przez `SUM` oraz grupowanym wykresem słupkowym, bez żadnej ręcznie wpisanej liczby. Obliczenie tych formuł na danych źródłowych daje North 54 000, South 39 000, East 66 000, West 35 000 oraz 44 000/47 000/50 000/53 000 według kwartałów i 194 000 łącznie, czyli dokładnie sumy referencyjne.

    `summary.pptx` miał trzy slajdy: slajd tytułowy z sumą całkowitą, pełną tabelę regionów i kwartałów zgodną ze skoroszytem co do komórki oraz slajd z wykresem i wskaźnikami powtarzający cztery sumy regionów. Koszt: 0,37 USD przy czterech rundach zatwierdzeń.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent mówi, że nie ma powłoki.** Capability używa **Files** zamiast **Container**. Przełącz na Container i wybierz runtime `workbench`.
- **Suma jest wpisaną liczbą, a nie formułą.** Poproś agenta, żeby przebudował arkusz podsumowania z formułami `SUM` albo `SUMPRODUCT` odwołującymi się do arkusza z danymi. Ręcznie wpisana liczba nie zmieni się, gdy zmieni się wiersz.
- **Workspace przez chwilę odrzuca każdy zapis.** Zdarzyło się to raz podczas weryfikacji, gdy host sandboksa stracił uprawnienia do gniazda Dockera. Każde `write_file` kończyło się błędem, a agent zamiast uruchomić skrypt, wypisał go jako tekst. `agenticos cmd doctor` i status połączenia w **Sandboxes** pokazują, czy usługa faktycznie może uruchomić sesję.
- **Liczby w prezentacji nie zgadzają się ze skoroszytem.** Agent mógł wpisać sumy do prezentacji osobno. Poproś go, żeby liczby w prezentacji brał z tych samych wartości, które dają formuły skoroszytu.
- **Pierwsza tura jest powolna.** Buduje się obraz `workbench`. Kolejne sesje używają go ponownie.

## Zapisz próbę { #record-the-trial }

Zachowaj CSV, prompt, wersję agenta, run w Activity i oba pliki wynikowe. Zanim zaufasz sumie, otwórz formuły skoroszytu, a nie tylko wyświetlane liczby.

Człowiek sprawdza, czy formuły są prawdziwymi formułami, czy oś wykresu znaczy to, co mówi, i czy prezentację naprawdę dałby komuś do ręki. Agent daje Ci pliki, ale nie zastępuje ich otwarcia.

## Kolejne kroki { #next-steps }

Jeśli raport ma powstawać co tydzień, a nie raz, przejdź do strony [Zaplanuj cotygodniowy raport](scheduled-report.md). Publikuje ona wynik jako stabilny, udostępniany artefakt zamiast pliku w workspace'ie.
