---
source_sha: ff4961c85112
---

# O AgenticOS { #about-agenticos }

AgenticOS to system operacyjny dla agentów AI firmy: hostowany u siebie, otwarty
źródłowo, wielotenantowy.

Istnieje z powodu jednej obserwacji. Większość frameworków agentowych daje Ci
bibliotekę — piszesz Pythona, wdrażasz go, a każda zmiana zachowania agenta to
pull request, przegląd i wydanie. To jest dokładnie właściwe dla funkcji
produktu i dokładnie niewłaściwe dla czterdziestu małych agentów, których firma
naprawdę chce, bo osoba, która wie, co agent ma mówić, to nie jest osoba z
dostępem do commitowania.

Dlatego tutaj **kod definiuje, a konfiguracja komponuje**. Zespół biznesowy
składa agentów w przeglądarce — instrukcje, model, zestaw capabilities, budżet —
a inżynierowie rozszerzają to, z czego można składać, w typowanym Pythonie.
Konfiguracja nigdy nie sięgnie dalej niż to, co zarejestrował kod, i to właśnie
sprawia, że Builder bez kodu można bezpiecznie oddać komuś, kto nie jest
inżynierem.

Spec jest dokumentem, więc wersjonuje się przy publikacji i eksportuje jako YAML
do Twojego własnego repozytorium git. Sufitem nie jest ten dokument: sufitem
jest to, co Twoi inżynierowie włożą do rejestru.

## Co czyni coś systemem operacyjnym dla agentów { #what-makes-something-an-operating-system-for-agents }

W tej kategorii to słowo bywa używane luźno i jest to uczciwy zarzut. Warto
powiedzieć, co musi ono znaczyć, bo system operacyjny nie jest nastrojem: to
siedem zadań, a produkt albo je wykonuje, albo nie.

Użyj tego jako testu. Przepuść przez niego AgenticOS i przepuść wszystko, z czym
go porównujesz.

| System operacyjny… | …a dla agentów jest to |
|---|---|
| **Uruchamia i izoluje procesy** | Procesem jest run. Startuje, można go zatrzymać, jest odizolowany od innych tenantów i zostawia zapis tego, co zrobił |
| **Egzekwuje limity zasobów** — quota, cgroups | Budżet sprawdzany *zanim* praca zostanie dopuszczona, a nie sumowany po fakcie, na jednostce, za którą ktoś odpowiada |
| **Kontroluje dostęp** — użytkownicy, uprawnienia, `sudo` | Uprawnienia sprawdzane w miejscu wywołania, a nie nazwy ról; oraz ścieżka eskalacji dla wszystkiego, co działa na świat zewnętrzny |
| **Sięga sprzętu przez sterowniki** | Jeden interfejs do wielu providerów modeli i wielu serwerów narzędzi, więc wymiana jednego czy drugiego nie przepisuje tego, co z nich korzysta |
| **Prowadzi system plików** | Trwałe miejsce na własną wiedzę organizacji, z dołączonymi do niej regułami dostępu |
| **Daje wielu interfejsom jedną powłokę** | Ten sam agent odpowiadający na każdej powierzchni jedną ścieżką wykonania, zamiast składania jej osobno przez każdą powierzchnię |
| **Pisze log audytowy** | Kto co uruchomił, kiedy, ile to kosztowało, kto to zatwierdził — zapisane niezależnie od tego, czy run się powiódł |

### Jak AgenticOS odpowiada na każde z nich { #how-agenticos-answers-each-one }

| | |
|---|---|
| Procesy | Runy są pierwszej kategorii: historia, koszt, status oraz izolacja tenantów egzekwowana przez ograniczenia bazy danych, a nie przez kod serwisu |
| Limity zasobów | [Miesięczne budżety](../governance.md) per agent, sprawdzane przed każdym żądaniem do modelu. Run, który się nie powiódł, i tak zapisuje, ile wydał, bo budżet ignorujący porażki nie jest budżetem |
| Kontrola dostępu | [Katalog uprawnień](../permissions.md) w kodzie, role złożone z niego, granty per zasób, które poszerzają i nigdy nie zawężają. `approval: required` jest tutaj `sudo` — run parkuje i czeka na człowieka |
| Sterowniki | [27 providerów modeli](../models.md) za profilem modelu i [dowolny serwer MCP po URL](../mcp.md). Zmień profil, a przesuną się wszyscy agenci, którzy go używają, bez publikowania żadnego z nich na nowo |
| System plików | [Kolekcje, skille i kontekst](../file-processing.md) w Twoim własnym Postgresie, z embeddingami kluczowanymi per organizacja |
| Powłoka | Jeden runner za [czatem webowym, API, Slackiem, Telegramem, widgetem, hostowaną stroną i harmonogramem](../channels.md) |
| Log audytowy | Każdy run, każda decyzja o approvalu, każda rotacja sekretu — z wartościami, nigdy z wierszami i nigdy z kluczem otwartym tekstem |

!!! info "Dlaczego ten test jest napisany tak, by stosować go również do nas"

    Lista kontrolna, która zawsze daje jedną odpowiedź, jest marketingiem. Tej
    da się naprawdę użyć wobec dowolnego produktu w tej kategorii i to tak
    chcielibyśmy być oceniani — łącznie z wierszem poniżej, w którym odpowiedź
    nie jest jeszcze wystarczająco dobra.

### Gdzie ten nie jest skończony { #where-this-one-is-not-finished }

Monitoring jest najsłabszym z tej siódemki. Każdy run zapisuje
`logfire_trace_id` i nic jeszcze tego nie odczytuje, więc dziś dostajesz
historię runów, koszt i status, a nie trend, na którym można działać. Jest to na
[roadmapie](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md) jako R11.

Dwie kolejne luki warte poznania, zanim zaczniesz porównywać: nie ma jeszcze
SAML ani SCIM — logowanie to JWT, klucze API, Google OAuth i magic linki — i nie
ma zestawu do ewaluacji, więc testowanie agenta przed opublikowaniem to coś, co
robisz ręcznie.

## Dla kogo to jest { #who-it-is-for }

Dla firmy, która chce więcej niż trzech agentów i chce mieć nad nimi nadzór.

- **Osoba, która buduje agenta**, nie pisze Pythona. Pisze instrukcje, włącza
  capabilities, wskazuje kolekcję wiedzy i ustawia budżet.
- **Osoba odpowiadająca za rachunek** dostaje budżety, które zatrzymują run,
  approvale dla wszystkiego, co ma skutki uboczne, i ślad audytowy.
- **Inżynier** dostaje spec eksportowany jako YAML do własnego repozytorium git,
  HTTP API i platformę, której źródła może przeczytać.

## Czym to celowo nie jest { #what-it-deliberately-is-not }

**To nie jest framework do napisania jednego agenta.**
[Pydantic AI](https://ai.pydantic.dev) jest środowiskiem uruchomieniowym pod
spodem i jeśli chcesz pojedynczego agenta w Pythonie jako części produktu, użyj
go bezpośrednio.

To nie to samo co powiedzenie, że rzecz jest zamknięta na kod. Rozszerzanie jej
*jest* Pythonem — [capability](../howto/add-capability.md) to typowany,
przetestowany kod w tym repozytorium, a konektor, kanał czy strategia ingestii to
ten sam wzorzec. Różnica polega na tym, że narzędzie piszesz raz, a potem
komponuje z nim każdy.

**To nie jest usługa hostowana.** Nic nie dzwoni do domu. Ceny modeli pochodzą
ze snapshotu dołączonego do wydania, a jedyne żądania wychodzące to te, które
robią Twoi agenci. System operacyjny instaluje się na własnej maszynie; nikt nie
wynajmuje jądra za stanowisko.

**To nie jest miejsce na pisanie integracji.** Integracja z produktem SaaS to
[połączenie MCP](../mcp.md), a nie moduł Pythona, który ktoś w tym repozytorium
utrzymuje wobec API tamtego produktu. Dlatego katalog capabilities jest krótki i
krótki pozostaje.

## Część, która naprawdę jest produktem { #the-part-that-is-actually-the-product }

Większość wartości leży tutaj w tym, czego platforma **odmawia**: odczytu spoza
tenanta, nieprzyznanego scope'u, przekroczenia budżetu, drugiej decyzji na
rozstrzygniętym approvalu, speca, który nie przechodzi walidacji przy publikacji.

Ścieżka szczęśliwa — wywołanie modelu z podpiętymi narzędziami — to łatwiejsza
połowa i tuzin bibliotek robi ją dobrze. Odmowy są tą połową, która decyduje o
tym, czy możesz oddać agenta komuś, kto nie jest Tobą.

## Kiedy sięgnąć po coś innego { #when-to-use-something-else }

Cztery z siedmiu zadań to rzeczy, których biblioteka nigdy za Ciebie nie zrobi, a
trzy z nich to rzeczy, które hostowana platforma zrobi, nie dając Ci maszyny.
Żadne z tego nie jest zarzutem; to po prostu inne produkty.

[Który wybrać i kiedy →](comparison.md)

## Skąd to się wzięło { #where-it-came-from }

Wygenerowane z
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
dlatego „warstwa platformy” i „odziedziczone z szablonu” to rozróżnienia
pojawiające się w dokumentacji dla kontrybutorów. Warstwa platformy — wszystko,
co AgenticOS dokłada na wierzchu — jest w CI trzymana na 100% pokrycia testami.
Odziedziczone podsystemy są raportowane, ale nie bramkują buildu, bo trzymanie
kodu, którego nie zaprojektowaliśmy, na tej samej poprzeczce kupuje liczbę
pokrycia, a nie pewność.

Sześć decyzji stojących za kształtem tej rzeczy — dlaczego agent jest plikiem,
dlaczego format speca porusza się tylko naprzód, dlaczego walidacja dzieje się
przy publikacji — jest opisanych dla kontrybutorów w
[`docs/about/design.md`](https://github.com/vstorm-co/agenticos/blob/main/docs/about/design.md).

## Kto to buduje { #who-builds-it }

[Vstorm](https://vstorm.co) i każdy, kto przyśle pull requesta.

## Podsumowanie { #recap }

- **Kod definiuje, konfiguracja komponuje** — zespół biznesowy składa agentów,
  inżynierowie rozszerzają to, z czego można składać, i żadna strona nie czeka na
  drugą.
- „System operacyjny” jest tutaj **specyfikacją, a nie etykietą** — siedem zadań,
  każde z mechanizmem za sobą.
- Ten test jest pomyślany tak, by **stosować go również do innych produktów** i
  do tego: monitoring jest wierszem, w którym uczciwą odpowiedzią jest „jeszcze
  nie”.
- Produktem są głównie **odmowy**, a nie ścieżka szczęśliwa.
- Działa na **Twojej maszynie**, bo właśnie to robi system operacyjny.

[Kiedy sięgnąć po coś innego →](comparison.md) · [Zainstaluj →](../install.md)
