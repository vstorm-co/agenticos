---
source_sha: "7babbb247d78"
title: "Trzymaj dane osobowe z dala od promptów i odpowiedzi agenta"
description: "Skonfiguruj capability guardrails tak, żeby redagowała adresy e-mail, numery kart i sekrety, a potem porównaj to, co faktycznie dostał model, z tym, co zobaczył odwiedzający."
---

# Trzymaj dane osobowe z dala od promptów i odpowiedzi agenta { #keep-personal-data-out-of-an-agents-prompts-and-answers }

Włącz [capability guardrails](../reference/capabilities.md#guardrails) w małym testowym agencie i wyślij mu syntetyczne dane osobowe. Szukasz dwóch różnych tekstów: tego, co transkrypcja runu pokazuje dla modelu, i tego, za przeczytanie czego run faktycznie zapłacił dostawcy. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

[Działająca instalacja](../install.md) z profilem modelu. Nie potrzeba sandboksa ani modelu embeddingów. Capability nie dodaje narzędzi, więc w Toolbox potrzebne jest tylko **Guardrails**.

## Przygotuj dane wejściowe { #prepare-the-input }

Tym razem bez pliku: danymi wejściowymi jest sama wiadomość w czacie. Użyj tej linii, która łączy wzorzec rozpoznawany przez capability z takim, którego celowo nie rozpoznaje:

```text
My email is jane.doe@example.com, my card number is 4111 1111 1111 1111,
my SSN is 123-45-6789, and my phone number is 415-555-0132.
```

Fakty referencyjne: `redact_pii_*` usuwa adresy e-mail, IBAN, numery kart (ze sprawdzeniem sumy Luhna) i amerykański SSN, czyli stałą listę wzorców w stylu wyrażeń regularnych. Nie usuwa numerów telefonów: ta capability nie ma detektora telefonów. To luka, którą celowo sprawdzamy, a nie błąd w danych testowych.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Guardrails**. Nie dodaje żadnego narzędzia: nie ma tu nic do zatwierdzania przez człowieka, jest tylko sprawdzanie tekstu.
3. W konfiguracji capability włącz **Redact API keys and tokens from the user's prompt**, **Redact emails, IBANs, cards and SSNs from the prompt**, **Redact API keys and tokens from the agent's answer** i **Redact emails, IBANs, cards and SSNs from the answer**. Ustaw **Block the run if the prompt contains any of these terms (comma or newline separated)** na `wire transfer`.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You are a signup-support assistant.
When the user gives you account details, confirm receipt by repeating them back in a bulleted list.
End every answer with a new line reading exactly: Reference key: sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
```

Prośba, żeby agent powtórzył dane, daje krawędzi wejściowej coś do pokazania: to, co dotarło do modelu zredagowane, może zostać powtórzone tylko w zredagowanej postaci. Stały klucz referencyjny jest po to, żeby krawędź wyjściowa miała coś deterministycznego do wychwycenia, bo zmuszanie modelu do wymyślenia własnego sekretu nie jest niezawodne.

## Uruchom { #run-it }

Wyślij wiadomość z danymi testowymi w nowej rozmowie testowej, a potem drugą, niezwiązaną wiadomość:

```text
I need to send a wire transfer today, can you help?
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Odpowiedź | Nie powtarza jawnie adresu e-mail, numeru karty ani SSN |
| Numer telefonu w odpowiedzi | Powtórzony bez zmian, bo żaden detektor go nie redaguje |
| Linia `Reference key:` w odpowiedzi | Brzmi `Reference key: [redacted:openai_key]`, a nie prawdziwa wartość |
| Transkrypcja runu (Activity) dla tury użytkownika | Pokazuje oryginalną, niezredagowaną wiadomość, którą wpisałeś, razem z numerem telefonu |
| Wiadomość o przelewie | Status runu to `guardrail_blocked`, koszt `0` i brak odpowiedzi |
| Ta sama wiadomość o przelewie bez ustawionego słowa kluczowego | Wykonuje się normalnie; blokuje słowo kluczowe, a nie temat |

Nad drugim wierszem tabeli warto się zatrzymać: redakcja działa na krawędziach, dla których zbudowano capability, a wartość bez pasującego wzorca trafia do modelu dokładnie tak, jak ją wpisano. Czwarty wiersz to drugi taki przypadek: osoba przeglądająca Activity, żeby zobaczyć, „co się stało”, widzi prawdziwe dane odwiedzającego, bo guardrail przepisuje to, co czyta *model*, a nigdy zapisanej tury rozmowy.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Pierwsza odpowiedź: *"some of your details were automatically redacted for your security before they reached me, so I was not able to see your email, card number, or SSN"*, a po niej `Phone Number: 415-555-0132` przytoczone bez zmian i `Reference key: [redacted:openai_key]`. Koszt: 0,003 USD.

    Transkrypcja runu zapisała turę użytkownika jako `My email is jane.doe@example.com, my card number is 4111 1111 1111 1111, my SSN is 123-45-6789, and my phone number is 415-555-0132.`, czyli pełny, oryginalny, niezredagowany tekst, podczas gdy zapisana tura asystenta miała już `[redacted:openai_key]`.

    Jeszcze jedna rzecz była widoczna tylko na łączu: ramki `text_delta` w WebSockecie przesyłały prawdziwy klucz referencyjny znak po znaku, zanim ramka `final_result` zastąpiła całą odpowiedź wersją zredagowaną. Redakcja działa na gotowej odpowiedzi, a nie na każdym streamowanym tokenie. `widget.js` właśnie z tego powodu nadpisuje wyświetlany tekst przez `final_result.output`, ale klient, który tylko dokleja delty, pokazałby sekret przez sekundę czy dwie przed podmianą.

    Wiadomość o przelewie: `error`, *"This request was blocked by an input guardrail."*, bez ramki `complete` po niej. Run zapisał status `guardrail_blocked`, `0` tokenów wejściowych i wyjściowych, koszt `0.000000`.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Wartość, która miała zostać zredagowana, przechodzi nietknięta.** Porównaj ją z czterema wzorcami: e-mail, IBAN, numer karty (ze sprawdzeniem sumy kontrolnej), amerykański SSN. Numer telefonu, adres fizyczny ani imię i nazwisko nie są objęte: to warstwa wyrażeń regularnych, a nie model, który rozumie, czym są dane osobowe. Wzorzec dla telefonów jest śledzony w [#1901](https://github.com/vstorm-co/agenticos/issues/1901).
- **Klient streamujący na chwilę pokazuje sekret.** Redakcja odpowiedzi działa na gotowej odpowiedzi, gdy ramki `text_delta` już wyszły. Wyświetlaj tekst z `final_result`, tak jak `widget.js`, zamiast tylko doklejać delty. Buforowanie odpowiedzi przy włączonym sprawdzaniu wyjścia jest śledzone w [#1900](https://github.com/vstorm-co/agenticos/issues/1900).
- **Blokada nie zadziałała.** `blocked_keywords_*` dopasowuje dosłowny podciąg bez rozróżniania wielkości liter. Blokada wymaga też włączenia przełącznika danej krawędzi: lista słów kluczowych na krawędzi wyjściowej nic nie robi z wejściem.
- **Transkrypcja nadal pokazuje surową wartość.** Na krawędzi wejściowej tak ma być: przepisywane jest tylko to, co trafia do modelu, a nie zapisana tura, którą człowiek przegląda później. Redagowanie przed zapisem to inna funkcja, a nie ta.
- **Run pokazuje `guardrail_blocked`, którego się nie spodziewałeś.** Przeczytaj pole `error` runu. Podaje krawędź (`input`, `output` albo `tool_result`), ale celowo nigdy dopasowanego tekstu, więc sprawdź samą listę słów kluczowych.
- **Sprawdzanie wyników narzędzi wygląda na nieużywane.** Ma znaczenie dopiero wtedy, gdy agent ma narzędzie czytające niezaufane treści: pobraną stronę, plik, odpowiedź MCP. Ta próba żadnego nie ma, więc ta krawędź była skonfigurowana, ale nigdy nie użyta.

## Zapisz próbę { #record-the-trial }

Zachowaj dokładną wiadomość, wersję agenta, informację, które krawędzie i słowa kluczowe skonfigurowano, transkrypcję runu dla obu tur oraz `status` i koszt runu z Activity. Człowiek decyduje, czy cztery wzorce wystarczą dla danego agenta, czy luka z numerami telefonów ma dla niego znaczenie i czy sprawdzanie wyników narzędzi ma być włączone, zanim zostanie dodane jakiekolwiek narzędzie czytające świat zewnętrzny.

## Kolejne kroki { #next-steps }

[Opis guardrails w referencji](../reference/capabilities.md#guardrails) podaje dokładne wzorce i trzy krawędzie w jednej tabeli. Jeśli agent będzie czytać cokolwiek pobranego z zewnątrz, czyli stronę internetową, serwer MCP albo przesłany plik, włącz krawędź wyników narzędzi, zanim ta capability trafi do użytku, a nie po fakcie.
