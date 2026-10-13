---
source_sha: "1176d12d1a25"
title: "Zamień CSV na wykres, który możesz sprawdzić"
description: "Dołącz mały syntetyczny plik sprzedaży, pozwól agentowi policzyć i narysować go w sandboksie, a potem uzgodnij każdą liczbę z wierszami źródła."
---

# Zamień CSV na wykres, który możesz sprawdzić { #turn-a-csv-into-a-chart-you-can-check }

Daj agentowi mały plik sprzedaży i poproś o sumy miesięczne, wykres oraz skrypt, który je wygenerował. Dane są na tyle małe, że da się je zsumować ręcznie, więc każdą liczbę podaną przez agenta można sprawdzić z wierszami źródła. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia. Nie mierzy dokładności na Twoich własnych danych.

## Przygotuj dane wejściowe { #prepare-the-input }

Użyj [działającej instalacji](../install.md) z profilem modelu. Zapisz to jako `sales.csv`:

```csv
month,product,revenue_eur
2026-01,A,120
2026-01,B,80
2026-02,A,150
2026-02,B,100
2026-03,A,90
2026-03,B,110
```

Liczby są zmyślone. Sumy referencyjne to 200 EUR za styczeń, 250 za luty i 200 za marzec, łącznie 650, z sześciu wierszy danych.

## Sprawdź sandbox { #check-the-sandbox }

Agent czyta plik i uruchamia skrypt w kontenerze. Do tego potrzebna jest usługa sandboksa i zarejestrowane połączenie:

- `make dev` i profil `sandbox` w Docker Compose uruchamiają usługę. Zobacz [instalację](../install.md).
- **Sandboxes → Add connection** rejestruje ją dla organizacji. Połączenie oferuje runtime `workbench`, który ma `pandas` i `matplotlib`. Zobacz [sandbox](../sandbox.md#which-environments-an-agent-may-ask-for).
- `agenticos cmd doctor` pokazuje, czy każde zarejestrowane połączenie odpowiada runtime'em.

Pierwsza sesja buduje obraz `workbench`, około 2 GB. Na świeżym hoście licz się z minutą lub dwiema na pierwszą turę.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Files & shell**. Wybierz **Container**, nie **Files**: workspace Files nie ma powłoki, więc agent nie może uruchomić skryptu. Wybierz połączenie i runtime `workbench`, a zakres zostaw na poziomie rozmowy.
3. Włącz **Charts**. Rysuje liczby, które agent już ma, więc wykres pokazuje to, co policzył skrypt.
4. Ustaw budżet i limit kroków na czas próby. Zapisany run użył 25 kroków i kosztował około 0,11 USD.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You analyse CSV files the user attaches.
Read the file from the workspace before calculating anything.
Show the totals as a table and state the number of rows you read.
Draw charts with create_chart from numbers you computed.
Save any code and output files in the workspace and give their paths.
Do not fetch data from the internet.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem, dołącz `sales.csv` i wyślij:

```text
Sum revenue_eur by month. Return the totals as a table, draw a bar chart of them, and save the calculation script and a PNG of the chart in the workspace.
```

Załącznik trafia do workspace'u w `uploads/`, a wiadomość mówi agentowi, gdzie go znaleźć. Trasowanie opisuje [przetwarzanie plików](../file-processing.md).

Gdy agent chce uruchomić skrypt, czat pokazuje **Tool approval required**. Uruchomienie polecenia powłoki to efekt uboczny, więc domyślnie zatwierdza je człowiek. Przeczytaj polecenie, a potem **Approve**. Run wznawia się tam, gdzie się zatrzymał. Żeby pominąć ten krok dla zaufanego agenta testowego, zmień ustawienie zatwierdzania `execute` w Builderze. Zobacz [zatwierdzenia](../governance.md#approvals).

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Sumy miesięczne w odpowiedzi, w wyniku skryptu i na wykresie | 200, 250 i 200 EUR, w kolejności miesięcy |
| Suma całkowita | 650 EUR |
| Przeczytane wiersze | 6 |
| Wykres | Słupki zaczynają się od zera, oś podaje jednostkę |
| Workspace | Skrypt i PNG istnieją i dają się otworzyć |
| Ta sama wiadomość bez załączonego pliku | Agent mówi, że brakuje pliku, i nie zmyśla danych |

Porównuj każdą liczbę z wierszami źródła, nie z podsumowaniem w samej odpowiedzi. Potem otwórz workspace z panelu plików czatu. Otwórz sam plik PNG i przeczytaj skrypt. Ścieżka w odpowiedzi nie dowodzi, że plik istnieje.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wywołał `read_file` na załączniku, `write_file` dla `analysis/revenue_by_month.py`, a potem `execute`, które zaparkowało do zatwierdzenia. Po zatwierdzeniu skrypt wypisał trzy sumy, `Total rows read : 6` i `Grand total (€) : 650`. `create_chart` narysował 200, 250 i 200. W workspace'ie był skrypt i PNG 1050×600. Koszt: 0,115 USD.

    Końcowa odpowiedź podała sumy prozą i wymieniła zapisane pliki, ale nie powtórzyła tabeli ani liczby wierszy. Były w wyniku skryptu. Bez pliku agent wylistował pusty workspace i poprosił o CSV.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent mówi, że nie ma powłoki.** Capability używa **Files** zamiast **Container**.
- **Pierwsza tura długo czeka.** Buduje się obraz `workbench`. Kolejne sesje używają go ponownie.
- **Run zatrzymuje się po tym, jak agent zapisze skrypt.** Czeka na zatwierdzenie `execute`. Otwórz czat albo zakładkę **Approvals** w **Activity**.
- **Błąd połączenia wskazuje sandbox.** Uruchom `agenticos cmd doctor`, a potem sprawdź połączenie w **Sandboxes**.
- **Któraś suma jest błędna.** Przeczytaj skrypt, zanim zmienisz prompt. Błąd obliczenia i brakujący runtime to różne problemy, a wyniki narzędzi w Activity pokazują, który wystąpił.

## Zapisz próbę { #record-the-trial }

Zachowaj dokładny plik CSV, prompt, wersję agenta, profil modelu, run w Activity, skrypt i PNG. Zachowaj też nieudane runy. Jeśli publikujesz wynik, zaznacz, że dane są syntetyczne, i pokaż tyle tabeli, żeby dało się sprawdzić wykres.

Człowiek zatwierdza polecenie, porównuje sumy ze źródłem i otwiera pliki. Agent nie zastępuje tego sprawdzenia. Daje Ci wszystko, czego potrzebujesz, żeby zrobić je szybko.

Gdy to działa, dodawaj po jednej trudności naraz: brakującą wartość, powtórzony miesiąc albo drugą walutę. Każda pokazuje, jak agent radzi sobie z danymi, które nie sumują się gładko. Żeby powtarzać raport według harmonogramu, przejdź do strony [Zaplanuj cotygodniowy raport](scheduled-report.md).
