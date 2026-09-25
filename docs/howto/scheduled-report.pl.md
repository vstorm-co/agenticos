---
source_sha: "c64d022dd8b0"
title: "Zaplanuj cotygodniowy raport"
description: "Daj agentowi samowystarczalne zadanie raportowe, uruchom je na żądanie, opublikuj wynik jako artefakt i ustaw cotygodniowy harmonogram."
---

# Zaplanuj cotygodniowy raport { #schedule-a-weekly-report }

Zbuduj agenta, który pisze krótki raport z danych zawartych w zadaniu i publikuje go jako [artefakt](../artifacts.md) pod stałym linkiem. Potem ustaw mu cotygodniowy harmonogram. Dane zawierają wiersz, którego nie da się użyć, więc możesz sprawdzić, czy agent go zgłasza, zamiast ukrywać. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

Strona rozdziela dwa pytania. Czy raport wychodzi poprawnie? To sprawdzasz przyciskiem **Run now**. Czy harmonogram go dostarcza? Na to odpowiada dopiero zaplanowane odpalenie.

## Zbuduj agenta { #build-the-agent }

Użyj [działającej instalacji](../install.md) z profilem modelu. Nie potrzebujesz sandboksa ani modelu embeddingów.

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Charts** i **Artifacts**.
3. Ustaw budżet i limit kroków na czas próby. Zapisane runy użyły 15 kroków i kosztowały około 0,05 USD każdy.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You write short reports from data given in the task.
Use only the rows in the task. Report totals per category and name any row you could not use.
Label the report as synthetic when the task says the data is synthetic.
Publish the finished report with publish_artifact under the name weekly-report.
```

Nazwa artefaktu jest jego tożsamością. Każdy run tego agenta, który publikuje `weekly-report`, aktualizuje ten sam artefakt, więc udostępniany link się nie zmienia. Run dodaje wersję tylko wtedy, gdy strona się zmieniła. Identyczna treść zwraca `unchanged` i zostawia ostatnią wersję.

## Utwórz harmonogram { #create-the-schedule }

Otwórz **Routines → New schedule** albo zakładkę **Availability** agenta i wybierz agenta. Umieść dane w wiadomości, żeby późniejszy run nie zależał od pliku, który ktoś wgrał do wcześniejszego czatu:

```text
Create a report for the synthetic period Demo Week.
Use only these CSV rows:
category,amount
Supplies,20
Supplies,30
Travel,15
Travel,abc
Report totals by category in a fictional demo currency and draw a bar chart.
Label the report synthetic and name any row you could not use.
```

Jako rytm wybierz **At a set time**, potem **Days of the week**, zaznacz **Mon** i ustaw **Time (UTC)** na 09:00. Odpowiadające temu wyrażenie cron to `0 9 * * 1`. Scheduler działa w UTC, więc przelicz swój czas lokalny. Zapisz, a potem sprawdź czas następnego odpalenia, który pokazuje harmonogram.

Harmonogram wykonuje się jako członek organizacji, który go utworzył, z jego dostępem, a jego runy obciążają budżet agenta jak każde inne. Dlaczego tak jest, wyjaśniają [Koncepcje](../concepts.md#trigger).

## Uruchom teraz { #run-it-now }

Naciśnij **Run now** na harmonogramie. Powoduje jedno dodatkowe odpalenie i nie zmienia cotygodniowego rytmu. Żądanie wraca, gdy tylko worker przyjmie odpalenie. Run pojawia się potem we własnej rozmowie harmonogramu, w sekcji **Routines** na pasku bocznym czatu.

| Sprawdzenie | Kryterium |
| --- | --- |
| Sumy | Supplies 50, Travel 15 |
| Wiersz `Travel,abc` | Wskazany jako nieużyteczny i niepoliczony |
| Oznaczenie | Raport mówi, że dane są syntetyczne |
| Artefakt | **Artifacts** wymienia `weekly-report`, prywatny dla Ciebie |
| Run w Activity | Powierzchnia `schedule`, status completed |
| Drugie Run now | Ten sam artefakt i link: nowa wersja, jeśli strona się zmieniła, albo `unchanged` przy identycznej treści |

Otwórz stronę artefaktu i przeczytaj raport tam, nie tylko w odpowiedzi w czacie. To tę stronę będą otwierać ludzie. Pozostaje prywatna, dopóki jej nie udostępnisz albo nie utworzysz publicznego linku.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Harmonogram podał następne odpalenie na poniedziałek 28 września, 09:00 UTC. Run now został przyjęty z `202`, a run zakończył się na powierzchni `schedule` około 30 sekund później, za 0,044 USD.

    Agent wywołał `publish_artifact` z nazwą `weekly-report` i dostał wersję 1, prywatną. Potem wywołał `create_chart`. Artefakt pokazywał Supplies 50 i Travel 15, oznaczenie danych syntetycznych oraz „Rows excluded (could not be used): Travel, abc”. Drugie Run now dodało wersję 2 do tego samego artefaktu i linku.

    Wykres pojawił się w rozmowie runa, nie w artefakcie. Strona artefaktu nie ma dostępu do sieci, a agent napisał raport bez osadzonego wykresu.

## Czego harmonogram nie rozstrzyga za Ciebie { #what-the-schedule-does-not-decide-for-you }

- **Skąd pochodzą dane.** Tutaj dane są wpisane na stałe w wiadomość. Prawdziwy raport potrzebuje źródła, do którego agent sięga przy każdym runie, takiego jak [kolekcja wiedzy](set-up-knowledge-base.md), [połączenie MCP](../mcp.md) albo workspace sandboksa. Harmonogram nie zgadnie, który nowo wgrany plik zastępuje plik z zeszłego tygodnia.
- **Okres raportu.** Nazwij go w wiadomości albo każ agentowi odczytać datę. Plik nazwany „weekly” nie mówi modelowi, które daty uwzględnić.
- **Kto go czyta.** Nowy artefakt jest prywatny dla osoby, dla której wykonał się run. Udostępnij go albo utwórz publiczny link na stronie artefaktu. Widoczność i granty opisują [Artefakty](../artifacts.md).
- **Zatwierdzenia.** Żadne z użytych tu narzędzi ich nie wymaga. Jeśli dodasz narzędzie, które wymaga, zaplanowany run parkuje, dopóki ktoś nie zdecyduje, więc wskaż, kto pilnuje [kolejki zatwierdzeń](../governance.md#approvals).

## Obserwuj prawdziwe odpalenie { #watch-a-real-fire }

Run now dowodzi zadania, nie harmonogramu. Po pierwszym poniedziałku o 09:00 UTC sprawdź, czy w Activity sam pojawił się nowy run, czy artefakt zyskał wersję i czy osoby, które mają go czytać, mogą go otworzyć. Karta **Routines** na dashboardzie pokazuje ostatni wynik każdej rutyny, więc harmonogram, który zaczyna zawodzić, jest widoczny.

Harmonogram, którego twórca nie może już uruchamiać agenta, sam się wyłącza i zapisuje powód. Zobacz [Koncepcje](../concepts.md#it-runs-as-a-person).

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Po Run now nic się nie dzieje.** Harmonogram jest wstrzymany albo worker w tle nie działa. Worker wykonuje każde zaplanowane odpalenie i każde Run now.
- **Raport nie ma artefaktu.** Sprawdź, czy **Artifacts** jest włączone i czy instrukcje podają `weekly-report`. Wywołania narzędzi runa w Activity pokazują, czy `publish_artifact` zostało wywołane i co zwróciło.
- **Każdy run tworzy nowy artefakt.** Nazwa zmieniła się między runami. Trzymaj ją na stałe w instrukcjach.
- **Któraś suma jest błędna albo zły wiersz zniknął.** Doprecyzuj instrukcje, zanim cokolwiek zaplanujesz. Harmonogram powtarza błąd co tydzień.

## Zapisz próbę { #record-the-trial }

Zachowaj wiadomość, wersję agenta, profil modelu, wyrażenie cron, każdy run w Activity i każdą wersję artefaktu. Zapisz, które odpalenia były z Run now, a które zaplanowane. Człowiek sprawdza sumy, decyduje, kto może czytać artefakt, i obserwuje pierwsze prawdziwe odpalenie.
