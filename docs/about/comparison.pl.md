---
source_sha: 0683b5318348
---

# Kiedy sięgnąć po coś innego { #when-to-use-something-else }

Ta strona jest napisana tak, żeby przydała się wtedy, gdy odpowiedzią nie jest
AgenticOS. Porównanie, które zawsze kończy się tak samo, nie jest porównaniem, a
kategorie poniżej pokrywają się na tyle, że zły wybór kosztuje miesiące.

Krótka wersja: **biblioteka** jest właściwa dla jednego agenta wewnątrz
produktu, **hostowana platforma** jest właściwa, gdy nie chcesz zajmować się
maszyną, **agentowy workspace** jest właściwy, gdy użytkownikiem jest Twój
własny pracownik, a AgenticOS jest właściwy, gdy agenci mają być edytowalni
przez osobę niebędącą inżynierem, nadzorowani przez kogoś, kto za nich
odpowiada, i uruchamiani na sprzęcie, który kontrolujesz — wszystko trzy naraz.

## Kategorie { #the-categories }

| | Co to jest | Kiedy użyć tego zamiast |
|---|---|---|
| [Pydantic AI](https://ai.pydantic.dev) | Biblioteka agentowa, na której działa AgenticOS | Budujesz jednego agenta, w Pythonie, jako część produktu |
| LangGraph, LangChain, LlamaIndex, elizaOS | Biblioteki i frameworki do komponowania wywołań modelu | To samo — chcesz kodu, nie platformy, i nie przeszkadza Ci, że deployment jest Twój |
| [Cloudflare OS](https://github.com/cloudflare/cloudflare-os) | Otwartoźródłowy agentowy workspace na Cloudflare Workers | Twoimi użytkownikami są Twoi własni pracownicy, jesteś już na Cloudflare i bardziej zależy Ci na aplikacjach per osoba niż na nadzorowanym katalogu agentów |
| [Glean](https://www.glean.com) | Hostowana wyszukiwarka korporacyjna z agentami na wierzchu | Chcesz 275+ konektorów świadomych ACL zaindeksowanych za Ciebie, a dane mogą leżeć w chmurze dostawcy |
| Dify, Flowise | Wizualne kreatory agentów, możliwe do samodzielnego hostowania | Chcesz kreatora i płótna do workflow, a model nadzoru liczy się dla Ciebie mniej niż to, jak szybko ktoś złoży przepływ |
| Hostowane korporacyjne platformy agentowe | Zamknięte platformy sprzedawane razem z zespołem wdrożeniowym | Chcesz, żeby za wynik odpowiadał ktoś inny, a koszt licencji nie jest ograniczeniem |
| OpenAI Assistants, Bedrock Agents | Hostowane środowiska uruchomieniowe agentów | Nie przeszkadza Ci jeden dostawca i nie potrzebujesz danych na własnym sprzęcie |

## Open source to nie to samo co możliwość samodzielnego hostowania { #open-source-is-not-the-same-as-self-hostable }

To dwie różne obietnice, a różnica między nimi decyduje o wdrożeniach.

**Open source** znaczy, że możesz przeczytać kod i zrobić forka.
**Self-hostable** znaczy, że możesz uruchomić całość na infrastrukturze, którą
już masz, bez zależności od platformy dostawcy.

AgenticOS potrzebuje PostgreSQL z pgvector, Redisa i Dockera. Niczego więcej,
żadnego konta nigdzie, a jedyne żądania wychodzące to te, które robią Twoi
agenci. To cała powierzchnia wdrożenia i dlatego może on działać wewnątrz sieci
szpitalnej albo w środowisku odciętym od internetu.

Cloudflare OS jest na licencji Apache-2.0 i jest naprawdę otwarty, a zbudowano
go na Durable Objects, Dynamic Workers i Cap'n Web. Uruchomienie go poza
Cloudflare oznacza samodzielne uruchomienie `workerd`, a README samego projektu
wymienia dokumentację tego jako jeszcze nienapisaną. Jeśli ograniczeniem
wdrożeniowym jest „to nie może zależeć od konkretnej chmury”, to właśnie tę
rzecz trzeba sprawdzić najpierw.

!!! info "Żadne z tych stanowisk nie jest błędne"

    Budowanie na prymitywach jednej platformy to sposób, w jaki Cloudflare OS
    dostaje sandboxowanie per dokument i dostęp ograniczony capability, które są
    naprawdę trudne do odtworzenia na zwykłej infrastrukturze. To wymiana i to,
    którą jej stronę chcesz, zależy od tego, gdzie oprogramowanie musi działać.

## Cloudflare OS { #cloudflare-os }

Najbliższa temu projektowi rzecz z nazwy, a co do kształtu — inny produkt.

**Cloudflare OS jest workspace'em.** Każda osoba dostaje agenta, środowisko do
pisania i uruchamiania kodu oraz osobiste aplikacje, które może zbudować i
udostępnić. Model bezpieczeństwa jest znakomity: agenci startują bez dostępu do
czegokolwiek, poświadczenia nigdy nie docierają do agenta, a każdy zasób, który
agent czyta, jest zapisywany i sprawdzany wobec tego, kto później otworzy wynik.

**AgenticOS jest katalogiem.** Publikujesz agentów, a oni odpowiadają ludziom,
którzy często nie są pracownikami — klientowi w widgecie, użytkownikowi na
Slacku, systemowi za kluczem API. Jednostką jest opublikowany, wersjonowany
agent z budżetem i odbiorcami, a nie workspace jednej osoby.

Wybierz Cloudflare OS, jeśli użytkownikiem agenta jest Twój własny personel i
jesteś na Cloudflare. Wybierz AgenticOS, jeśli agent ma być zwrócony na zewnątrz,
nadzorowany per agent i działać tam, gdzie każesz.

## Glean { #glean }

Glean to przede wszystkim wyszukiwarka korporacyjna, z agentami zbudowanymi na
indeksie. Jego siłą jest to, czego AgenticOS nie próbuje: konektory do 275+
systemów, które wnoszą do indeksu własne reguły dostępu każdego dokumentu, więc
odpowiedź nigdy nie może zacytować czegoś, czego pytający nie mógłby otworzyć.

Wynikają z tego dwie rzeczy. Jeśli Twoim problemem jest *„nasza wiedza jest w
czterdziestu systemach, a wyszukiwanie nie działa”*, to jest to, do czego służy
Glean, i AgenticOS mu nie dorówna — nasze wyszukiwanie działa per kolekcja i nie
dziedziczy jeszcze ACL ze źródła.

Jeśli Twoim problemem jest *„potrzebujemy nadzorowanych agentów, a dane nie mogą
wyjść”*, porównanie wychodzi w drugą stronę: Glean jest hostowany, wyceniany za
stanowisko z minimum korporacyjnym i nie jest czymś, co uruchamiasz sam.

## Biblioteka i dobudowanie reszty samemu { #a-library-and-building-the-rest-yourself }

LangGraph, LangChain, LlamaIndex, Pydantic AI. Najczęstsza prawidłowa odpowiedź
i ta, z którą ten projekt konkuruje najmniej: AgenticOS **działa na** Pydantic
AI, więc biblioteka jest warstwą pod spodem, a nie alternatywą dla niego.

Biblioteka plus kolejka plus baza danych szybko dają działającego agenta, a przy
jednym czy dwóch agentach to mniej pracy niż nauka platformy.

Sięgnij po bibliotekę bezpośrednio, gdy:

- **Agent jest produktem.** Jego zachowanie to funkcja, którą wydajesz,
  wersjonowana razem z Twoim kodem, przeglądana w Twoich pull requestach. UI,
  które pozwala komuś innemu je zmienić, nie jest tu zaletą — jest sposobem, w
  jaki Twój produkt zmienia się bez wydania.
- **Potrzebujesz pętli.** Własnego przepływu sterowania, grafu z cyklami,
  polityki ponowień, której nie wyraża niczyja abstrakcja. Platforma daje Ci
  dobrze zdefiniowany runner; a to jest dokładnie to, czego starasz się nie mieć.
- **W tej historii nie ma nikogo spoza inżynierii.** Jeśli każdą zmianę i tak od
  początku miał pisać inżynier, ta warstwa pośrednia nie kupuje Ci niczego.
- **Jest jeden agent.** Albo dwóch. Ekonomia poniżej odwraca się dopiero przy
  kilku.

To, co bierzesz na siebie w zamian, to
[siedem zadań](index.md#what-makes-something-an-operating-system-for-agents), po
jednym naraz i zwykle w tej kolejności, każde dopiero po tym, jak raz już
zabolało:

| Skończysz, pisząc | Ponieważ |
|---|---|
| Budżet, który zatrzymuje run | Liczenie wydatku po fakcie nie jest budżetem, a pierwsza zaskakująca faktura tego uczy |
| Approval rozstrzygany raz | Druga decyzja na rozstrzygniętym approvalu to wyścig i nie jest to teoretyczne |
| Izolację tenantów | Gdy pierwszy raz zapomni się o `WHERE organization_id`, jest to incydent danych, a nie błąd |
| Magazyn sekretów per tenant | Jeden klucz na całe wdrożenie znaczy, że jeden wyciek jest wyciekiem każdego klienta |
| Jedną ścieżkę wykonania dla wszystkich powierzchni | Inaczej Slack i Twoje API nie zgadzają się co do tego, ile kosztował agent |
| Ślad audytowy, który zapisuje porażki | Rejestr logujący tylko sukcesy odpowiada podczas incydentu na złe pytanie |

Nic z tego nie jest trudne. Wszystko to jest pracą, której nie wykonujesz nad
swoim produktem, i jest całością tego, czym jest ta platforma.

!!! info "Granica leży gdzieś koło piątego agenta"

    Albo wcześniej, przy pierwszej osobie, która potrzebuje zmienić to, co agent
    mówi, i nie ma dostępu do commitowania. Przed tym momentem biblioteka i
    kolejka to mniej pracy i to ich powinieneś użyć.

A jeśli i tak zamierzasz zbudować te sześć wierszy, to
[siedem zadań](index.md#what-makes-something-an-operating-system-for-agents) jest
rozsądną specyfikacją, względem której można budować — niezależnie od tego, czy
użyjesz akurat tej.

## Podsumowanie { #recap }

- Użyj **biblioteki** do jednego agenta wewnątrz produktu; użyj tego do katalogu
  agentów — granica leży koło piątego agenta albo przy pierwszym budującym spoza
  inżynierii.
- **Open source i możliwość samodzielnego hostowania to różne obietnice** —
  sprawdź, której naprawdę potrzebujesz.
- **Cloudflare OS** to workspace dla pracowników; to jest katalog agentów
  zwróconych na zewnątrz.
- **Glean** wygrywa konektorami i wyszukiwaniem świadomym ACL; to wygrywa wtedy,
  gdy dane nie mogą opuścić Twojej infrastruktury.
- **Zbudowanie tego samemu** jest słuszne mniej więcej do piątego agenta, a
  siedem zadań jest specyfikacją tak czy inaczej.
