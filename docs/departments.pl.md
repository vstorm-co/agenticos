---
source_sha: "186f40ff9e1d"
---

# Działy i grupy { #departments-and-groups }

Firmy dzielą się na działy: sprzedaż, finanse, HR, wsparcie. W AgenticOS dział
to [grupa](directory.md#groups), a grupa decyduje, kto może z czego korzystać.
Finanse mogą mieć własnych agentów, skille, pliki kontekstu i bazy wiedzy, których
sprzedaż nigdy nie zobaczy, a to, czego potrzebują wszyscy, zostaje otwarte dla
całej organizacji.

## Dodawanie działów { #adding-your-departments }

**Grupy** w głównej nawigacji pokazują grupy organizacji. Członek z
`members:manage` dodaje je pojedynczo przyciskiem **Nowa grupa** albo kilka naraz
przyciskiem **Dodaj działy**, który proponuje Sprzedaż, Finanse, HR, Wsparcie,
Inżynierię, Marketing, Dział prawny i Operacje, każdy z ikoną i krótkim opisem.
Potem można zmienić im nazwę, ikonę albo je usunąć jak każdą inną grupę.

Ludzi dodaje się do grupy na jej stronie, ręcznie, albo przez
[mapowanie grupy katalogowej](directory.md#directory-group-mappings), jeśli firma
prowadzi już swoje zespoły w katalogu.

## Kto może korzystać z nowej rzeczy { #who-can-use-a-new-thing }

Tworzenie agenta, skilla, bazy wiedzy albo pliku kontekstu zadaje jedno pytanie:
**kto może z tego korzystać**.

| Wybór | Kto do tego sięga | Zapisane jako |
|---|---|---|
| **Wszyscy** - domyślnie | Każdy członek organizacji | Widoczność `org` |
| **Tylko ja** | Ty i osoby, którym udostępnisz to później | Widoczność `private` (baza wiedzy staje się osobista) |
| **Wybrane grupy** | Członkowie wybranych grup | Widoczność `private`, udostępnione każdej grupie na poziomie `use` |

Członkowie grupy znajdują to, co jej udostępniono, korzystają z tego i podpinają
do własnych agentów. Osoby spoza grupy nie widzą tego na listach, w wyszukiwaniu,
w wyborach Buildera, przez API ani przez AI Architekta, który działa z
uprawnieniami pytającej osoby. Członkowie, których rola sięga do każdego zasobu -
domyślnie właściciel, administrator i builder - nadal widzą wszystko; zobacz
[Uprawnienia](permissions.md).

Aplikacje publikują agenci i na początku są prywatne dla osoby, dla której był
run; grupie udostępnia się je w panelu **Share**. Panel **Sharing** każdego
zasobu dodaje i usuwa grupy także po utworzeniu.

## Strona grupy { #a-groups-page }

Otwarcie grupy pokazuje jej ludzi i wszystko, co jej udostępniono, pogrupowane
według rodzaju - agenci, bazy wiedzy, skille, kontekst i aplikacje - z poziomem
udostępnienia każdego. Czytający widzi tylko to, co i tak mógłby otworzyć, więc
członek Sprzedaży czytający stronę Finansów nie dowie się, co Finanse trzymają.

## Skąd pochodzi wiedza agenta { #where-an-agents-knowledge-comes-from }

Agenta można podpiąć do bazy wiedzy, skilla albo pliku kontekstu udostępnionego
węższemu gronu niż on sam i nic tego nie zablokuje. Każdy, do kogo agent dociera,
dostaje wtedy odpowiedzi z tego źródła, także osoby, które same nie mogłyby go
otworzyć.

Zakładka **Toolbox** w Builderze pokazuje, skąd pochodzi wiedza agenta: do kogo
agent dociera, a przy każdym źródle, czy jest całej organizacji, czy których grup.
Źródło udostępnione mniejszej liczbie osób niż agent jest oznaczone, a nad listą
pojawia się ostrzeżenie. Jeśli to nie to, co planowano, zawęź agenta do tych
samych grup albo poszerz źródło.

## Grupy osoby w instrukcjach { #the-persons-groups-in-instructions }

Instrukcje mogą nazwać grupy osoby, z którą rozmawia agent, przez `{{groups}}` -
na przykład *„Pomagasz komuś z działu {{groups}}.”* Zmienna staje się nazwami jej
grup rozdzielonymi przecinkami albo pustym tekstem dla odwiedzającego. Zobacz
[Zmienne](reference/spec.md#variables).

## Czego jeszcze nie obejmuje { #what-is-not-covered-yet }

Połączenia MCP są udostępniane na poziomie organizacji albo osobiste, nie per
grupa. Budżety i analityka w podziale na grupy nie są jeszcze częścią tej funkcji.
