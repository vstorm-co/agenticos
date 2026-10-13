---
source_sha: "62fe6a8232a7"
title: "Kieruj prośby do zespołu wyspecjalizowanych agentów"
description: "Zbuduj agenta recepcji, który deleguje pytanie o rozliczenia albo pytanie techniczne do opublikowanego specjalisty, a dopytuje, gdy pytanie jest niejednoznaczne."
---

# Kieruj prośby do zespołu wyspecjalizowanych agentów { #route-requests-to-a-team-of-specialist-agents }

Zbuduj trzech agentów: specjalistę od rozliczeń, specjalistę technicznego i recepcję, która kieruje pytanie do właściwego z nich albo dopytuje, gdy nie jest to jasne. Każdy specjalista jest publikowany osobno, więc jest przeglądany, wersjonowany i może go użyć inna recepcja. To instrukcja wykonania z trzema zapisanymi pytaniami jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu dla wszystkich trzech agentów.
- `agents:run` na obu specjalistach, żeby przypiąć ich z poziomu recepcji. To to samo uprawnienie, które sprawdza wzmianka na kanale albo sprawdzenie delegacji w każdym innym miejscu produktu. Zobacz [uprawnienia](../permissions.md#delegation-is-not-a-privilege-boundary).
- Bez kolekcji wiedzy, sandboksa i połączenia MCP w tym przykładzie.

## Przygotuj dane wejściowe { #prepare-the-input }

Mały syntetyczny produkt, żeby fakty specjalistów dało się sprawdzić:

**Fakty o rozliczeniach**: plan Basic 9 USD miesięcznie, Pro 29 USD miesięcznie, oba rozliczane co miesiąc. Pełny zwrot w ciągu 14 dni od obciążenia, bez podawania powodu; po tym czasie brak zwrotów. Faktury są wysyłane mailem w dniu obciążenia i zawsze dostępne na stronie Billing konta.

**Fakty techniczne**: klucz API jest w Settings → API keys; wygenerowanie nowego od razu unieważnia stary. Limit żądań to 60 na minutę na klucz; odpowiedź `429` podaje, ile sekund czekać. Status i historia incydentów są publikowane na stronie statusu.

## Zbuduj dwóch specjalistów { #build-the-two-specialists }

Opublikuj każdego jako osobnego agenta, bez capabilities. Każdy odpowiada wyłącznie na podstawie faktów, które mu dałeś.

1. **uc-billing-specialist**: w instrukcjach podaj powyższe fakty o rozliczeniach i dopisz, że pytanie spoza nich nie jest tematem tego agenta.
2. **uc-tech-specialist**: w instrukcjach podaj powyższe fakty techniczne z tą samą odmową dla wszystkiego innego.

Opublikuj obu przed zbudowaniem recepcji. Delegat musi być opublikowanym agentem, którego możesz uruchamiać, wskazanym przez slug.

## Zbuduj recepcję { #build-the-front-desk }

1. Utwórz trzeciego agenta, **uc-front-desk**, i wybierz swój profil modelu.
2. W **Toolbox** włącz **Delegation**. Zostaw `allow_dynamic` wyłączone: ten agent zawsze wywołuje tylko dwóch wskazanych specjalistów, nigdy wymyślonego przez siebie.
3. W **Delegates** dodaj obu opublikowanych specjalistów, przypiętych do bieżącej wersji.
4. Ustaw budżet i limit kroków na czas próby.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You are the front desk for this product's support. You never answer a billing
or technical question yourself.
Route a billing question (pricing, refunds, invoices, charges) to the billing
specialist with task(description=..., subagent_type="uc-billing-specialist").
Route a technical question (the API, keys, rate limits, uptime) to the
technical specialist with task(description=..., subagent_type="uc-tech-specialist").
If a question could be either, or names neither, ask the user one short
question to tell which team it belongs to before delegating anything.
Relay the specialist's answer; do not add facts of your own.
```

`task` nie ma efektów ubocznych, więc żadna z delegacji domyślnie nie prosi o zatwierdzenie. Zatwierdzałoby się narzędzia samego specjalisty, w specu specjalisty.

## Kto płaci i co widzi użytkownik { #who-pays-and-what-the-user-sees }

Run recepcji płaci za całą wymianę: jedna wspólna księga wydatków obejmuje rodzica i każdego specjalistę, którego wywołuje, a w trakcie rozmowy egzekwowany jest budżet recepcji. Każdy specjalista i tak dostaje własny wiersz w Activity z `parent_run_id` wskazującym run recepcji, więc na pytanie „ile w tym miesiącu kosztował specjalista od rozliczeń” jest odpowiedź, która nie podwaja rachunku organizacji. Zobacz [jak zapisywany jest delegowany run](../governance.md#what-a-delegated-run-is-recorded-as).

Pytający widzi jedną ciągłą odpowiedź. Recepcja przekazuje to, co powiedział specjalista. W transkrypcji nic nie wygląda na przekazanie, dopóki nie otworzysz runu w Activity i nie zobaczysz pod nim delegacji.

## Zatwierdzenie wewnątrz delegacji { #an-approval-inside-a-delegation }

Żaden ze specjalistów nie ma tu narzędzia za bramką, więc nic nie parkuje. Gdyby miał, na przykład capability `send_email` u specjalisty od rozliczeń, zatwierdzenie trafiłoby do tej samej kolejki, którą obserwuje osoba rozmawiająca z recepcją, z informacją, **który delegat** zaproponował wywołanie, a nie tylko jakie narzędzie. Zatwierdzenie wznawia tego specjalistę tam, gdzie się zatrzymał, zamiast delegować od nowa. Zobacz [zatwierdzenie wewnątrz delegacji](../governance.md#an-approval-inside-a-delegation).

## Uruchom { #run-it }

Zadaj recepcji trzy pytania, każde w osobnej rozmowie:

```text
I was charged twice this month, can I get a refund on the extra charge?
```

```text
My integration keeps getting 429s, what's the limit and where do I check status?
```

```text
Something changed and now it doesn't work like before.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pytanie o rozliczenia | Deleguje do `uc-billing-specialist`; odpowiedź podaje zasadę 14-dniowego zwrotu |
| Pytanie techniczne | Deleguje do `uc-tech-specialist`; odpowiedź podaje limit 60 na minutę i stronę statusu |
| Pytanie niejednoznaczne | Brak delegacji; recepcja pyta, do którego zespołu to należy |
| Activity, run rozliczeń | Run podrzędny pod runem recepcji, z ustawionym `parent_run_id` i własnym kosztem |
| Activity, run techniczny | Ten sam kształt, pod `uc-tech-specialist` |
| Pytanie, które nie wskazuje żadnego zespołu, a pytający odmawia doprecyzowania | Recepcja nadal dopytuje, zamiast zgadywać, którego specjalistę wywołać |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, dla wszystkich trzech agentów. Pytanie o zwrot dało jedno wywołanie `task` do `uc-billing-specialist` (koszt 0,0236 USD za run recepcji razem z delegatem), którego odpowiedź wskazywała 14-dniowe okno i stronę Billing. Pytanie o limit żądań dało jedno wywołanie `task` do `uc-tech-specialist` (0,0227 USD), którego odpowiedź podawała 60 żądań na minutę i stronę statusu. Niejednoznaczna wiadomość nie dała żadnej delegacji: „Could you tell me a bit more about what changed - is this related to billing... or something technical...?” (0,0066 USD). Własny wiersz runu specjalisty od rozliczeń zapisał 0,0057 USD jako run podrzędny runu recepcji, co potwierdza opisany wyżej układ ze wspólną księgą i osobnym wierszem.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Recepcja odpowiada sama, bez delegacji.** Instrukcje nie zostały wykonane albo `subagents` nie jest przypisane. Sprawdź Toolbox, zanim ponownie przeczytasz prompt.
- **Publikacja recepcji jest odrzucana ze wskazaniem delegata.** Któryś specjalista nie jest opublikowany albo nie możesz go uruchamiać. Przypięcie sprawdza `agents:run` na wierszu tego specjalisty.
- **Recepcja zawsze dopytuje, nawet przy jasnym pytaniu o rozliczenia.** Zasada kierowania w instrukcjach jest zbyt surowa albo model zbyt szeroko rozumie „could be either”. Zawęź przykłady w prompcie.
- **Specjalista odpowiada na pytanie spoza swoich faktów, zamiast odmówić.** Jego instrukcje nie każą odmawiać. Dopisz jawną linię z odmową, jak powyżej.
- **Wersja delegata zmieniła się bez Twojej prośby.** Tak się nie stało. Przypięcie zmienia się tylko wtedy, gdy spec recepcji zostanie ponownie opublikowany z nową wersją. Zobacz [przypięty delegat sam się nie zmienia](../governance.md#a-pinned-delegate-does-not-move-on-its-own).

## Zapisz próbę { #record-the-trial }

Zachowaj każde pytanie, informację, który specjalista odpowiedział, odpowiedź, run podrzędny w Activity z własnym kosztem i sumę recepcji. Człowiek nadal decyduje, co jest na tyle niejednoznaczne, żeby dopytać, przegląda fakty każdego specjalisty przed publikacją i ocenia, czy przekazana odpowiedź naprawdę oddaje to, co powiedział specjalista.

## Kolejne kroki { #next-steps }

Dodaj trzeciego specjalistę i zobacz, jak trudno utrzymać jednoznaczne instrukcje kierowania w recepcji. To dobry znak, że zespół wyrasta z ręcznie pisanych reguł kierowania. `allow_questions` pozwala specjaliście w trakcie odpowiedzi zapytać tę samą osobę, z którą rozmawia recepcja, zamiast zgadywać; zobacz [delegowanie](../reference/capabilities.md#delegation).
