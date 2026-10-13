---
source_sha: "94fe4ff073a5"
title: "Segreguj skrzynkę i przygotowuj szkice odpowiedzi"
description: "Podłącz skrzynkę jako odpytywany trigger zdarzeń i niech agent przygotowuje szkice odpowiedzi albo wyciąga zadania, nigdy niczego nie wysyłając."
---

# Segreguj skrzynkę i przygotowuj szkice odpowiedzi { #triage-your-inbox-and-draft-replies }

Podłącz skrzynkę Gmail jako [trigger zdarzeń](../triggers.md#gmail-1-minute-and-no-secret-anywhere) i niech agent czyta każdą nową wiadomość i przygotowuje szkic odpowiedzi albo listę zadań. To instrukcja wykonania, a nie raport z pomiaru wdrożenia. Wymaga prawdziwego konta Gmail i klienta Google OAuth, którego tu nie skonfigurowano we wdrożeniu, więc nic z tej strony nie zostało uruchomione na działającej skrzynce.

## Co agent może, a czego nie może zrobić z pocztą { #what-the-agent-can-and-cannot-do-with-mail }

Przeczytaj to przed podłączeniem czegokolwiek, bo od tego zależy, czy ta strona jest warta zgody OAuth.

**Może czytać.** Trigger Gmaila odpytuje podłączoną skrzynkę raz na minutę i przekazuje agentowi temat, nadawcę i treść nowej wiadomości. Wdrożenie prosi Google wyłącznie o zakres `gmail.readonly`. Na ekranie zgody nie ma prośby o nic więcej, więc nie istnieje szersze uprawnienie, na którym można by przypadkiem polegać.

**Nie może wysyłać ani tworzyć prawdziwego szkicu w Gmailu.** Nie ma narzędzia, ani tutaj, ani w katalogu MCP, które wywołuje API wysyłania albo szkiców Gmaila. To, co szablony poniżej nazywają „szkicem”, jest tekstem odpowiedzi agenta zapisanym w runie, który się uruchomił. Trafia do **Activity**, do rozmowy tego runu, jako wiadomość, którą człowiek musi przeczytać i sam wkleić do wychodzącego maila. Nic nigdy nie jest wysyłane w Twoim imieniu i nic nie jest zapisywane z powrotem w skrzynce.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Klient Google OAuth zarejestrowany przez operatora wdrożenia (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, włączone Gmail API). To warunek na poziomie *wdrożenia*, a nie coś, co każda organizacja konfiguruje sama. Bez niego karta podłączenia Gmaila mówi o tym, zamiast pokazywać przycisk, który mógłby tylko zawieść.
- Uprawnienie `mcp:manage`, żeby podłączyć skrzynkę.

## Zbuduj agenta { #build-the-agent }

1. Otwórz **Routines → New event trigger → Gmail → Connect account**. Zgoda daje dostęp do skrzynki tylko do odczytu. Podłączenie niczego nie uruchamia i niczego nie gubi: pozycja w skrzynce jest ustalana w chwili zakończenia zgody.
2. Wybierz, co ma uruchamiać trigger: każda nowa wiadomość, tylko skrzynka odbiorcza albo oznaczone jako ważne. Zawęź dalej przez **Subject contains**, **Sender contains** albo etykietę Gmaila. Wszystkie trzy to opcjonalne filtry podciągu, a pominięty filtr oznacza, że uruchamia każda wiadomość w zakresie.
3. Zacznij od szablonu zamiast od pustego promptu. `GET /trigger-templates` zwraca dwa dla tego źródła:

   | Szablon | Co robi |
   | --- | --- |
   | **Draft a reply to the email** | Streszcza w jednej linii, czego potrzebuje nadawca, a potem przygotowuje szkic odpowiedzi do przejrzenia |
   | **Turn the email into action items** | Wyciąga każde zadanie, jego właściciela i ewentualny termin |

4. Utwórz agenta, którego ma uruchamiać ten trigger, z profilem modelu i opublikuj go. Żaden z szablonów nie wymaga sandboksa, kolekcji wiedzy ani innej capability.
5. Przypisz trigger do opublikowanego agenta i ustaw go jako aktywny.

Prompt szablonu ze szkicem odpowiedzi, dosłownie:

```text
An email just arrived - its subject, sender and body are in this message.
Summarise in one line what the sender needs, then draft a reply I can review and
send. Match the sender's tone, answer every question they asked, and keep it
brief.
```

## Co tu znaczy „Uruchom” { #what-run-it-means-here }

Nie ma podpisanej dostawy do wysłania ręcznie: Gmail jest odpytywany, a nie wypycha zdarzeń, więc nie ma ani adresu URL, ani sekretu. Są dwa sposoby, żeby zobaczyć agenta w działaniu, zanim przyjdzie prawdziwa wiadomość:

- **Run now** na triggerze uruchamia **podstawowy prompt agenta bez kontekstu dostawy**: bez wiadomości, bez nadawcy, bez niczego, na co można by przygotować odpowiedź. Dowodzi, że agent, jego budżet i stan publikacji są w porządku, ale nie sprawdza segregacji, bo w tym runie nie ma maila, na którym mogłyby zadziałać instrukcje szablonu.
- **Prawdziwa wiadomość w podłączonej skrzynce** to jedyny sposób, żeby zobaczyć faktyczny szkic. Heartbeat raz na minutę czyta to, co przyszło od ostatniego sprawdzenia, do 25 wiadomości na raz, więc najgorsze opóźnienie to minuta, a nagły napływ z listy mailingowej nie zamienia się w setki runów.

## Sprawdź wynik { #check-the-result }

Gdy prawdziwa wiadomość uruchomi trigger, sprawdzenia ogólnie są takie:

| Sprawdzenie | Kryterium |
| --- | --- |
| Wiadomość pasująca do filtra | Uruchamia raz, a rozmowa runu zawiera szkic odpowiedzi albo listę zadań, nigdy wysłany mail |
| Wiadomość **niepasująca** do tematu/nadawcy/etykiety | W ogóle nie uruchamia |
| Mail bez wyraźnego pytania ani zadania | Szablon zadań mówi wprost, że nie ma nic do zrobienia, zamiast coś wymyślać |
| Własny status połączenia z Gmailem | Widoczny na triggerze; nieudane odpytanie jest zgłaszane tam, a nie tylko w logu kontenera |
| Poczta sprzed podłączenia skrzynki | Nigdy nie uruchamia, bo kursor zaczyna się w chwili zakończenia zgody |

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Nic się nie uruchamia.** Najpierw sprawdź status połączenia z Gmailem: zepsute odpytywanie jest zgłaszane na triggerze. Potem sprawdź filtr. Puste **Subject contains** albo **Sender contains** pasuje do wszystkiego, więc wąski filtr, który na papierze wygląda dobrze, może i tak wykluczyć wiadomość wysłaną jako test.
- **Spodziewasz się wysłanej odpowiedzi, a dostajesz wiadomość w czacie.** Tak to działa z założenia, to nie błąd; zobacz wyżej *Co agent może, a czego nie może zrobić z pocztą*. Skopiuj szkic do klienta poczty ręcznie.
- **Pominięte zaległości po przestoju.** Google przechowuje około tygodnia historii. Kursor starszy niż to synchronizuje się do teraz, zamiast odtwarzać wszystko, co się nazbierało, więc skrzynka wyłączona dłużej niż tydzień ma lukę, której nic nie uzupełni.
- **`Run now` wygląda na udane, ale nie wróciło nic użytecznego.** Uruchomił agenta bez dołączonej wiadomości. Tak ma być i nie jest to sposób na przetestowanie samej segregacji. Poczekaj na prawdziwą dostawę albo wyślij sobie pasujący testowy mail.

## Zapisz próbę { #record-the-trial }

Gdy uda się to uruchomić na prawdziwej skrzynce: zachowaj ustawiony filtr, użyty szablon albo prompt, kilka uruchomionych runów z ich szkicami i to, kto czyta te szkice, zanim cokolwiek zostanie wysłane. Człowiek wysyła każdą odpowiedź i zapisuje każde zadanie. Ten agent tylko przygotowuje tekst.

## Kolejne kroki { #next-steps }

Segregację sterowaną przez Twoją własną aplikację zamiast skrzynki opisuje strona [Segreguj zgłoszenia wsparcia z własnej aplikacji](support-ticket-triage.md). Używa podpisanego webhooka, który w całości kontrolujesz, i da się ją zweryfikować bez zewnętrznego konta.
