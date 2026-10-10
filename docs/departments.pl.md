---
source_sha: "28cffc94fecf"
---

# Działy i grupy { #departments-and-groups }

Firmy dzielą się na działy: sprzedaż, finanse, HR, wsparcie. W AgenticOS dział
to [grupa](directory.md#groups), a grupa decyduje, kto może z czego korzystać.
Finanse mogą mieć własnych agentów, skille, pliki kontekstu, bazy wiedzy i
serwery MCP, których sprzedaż nigdy nie zobaczy, a to, czego potrzebują wszyscy,
zostaje otwarte dla całej organizacji.

## Dodawanie działów { #adding-your-departments }

**Grupy** w głównej nawigacji pokazują grupy organizacji. Członek z
`members:manage` dodaje je pojedynczo przyciskiem **Nowa grupa** albo kilka naraz
przyciskiem **Dodaj działy**, który proponuje Sprzedaż, Finanse, HR, Wsparcie,
Inżynierię, Marketing, Dział prawny i Operacje, każdy z ikoną i krótkim opisem.
Potem można zmienić im nazwę, ikonę albo je usunąć jak każdą inną grupę.

Ludzi dodaje się do grupy na jej stronie, ręcznie, albo przez
[mapowanie grupy katalogowej](directory.md#directory-group-mappings), jeśli firma
prowadzi już swoje zespoły w katalogu.

### Lider grupy { #a-groups-lead }

Administrator może ustawić członka jako **lidera** grupy - korona przy nim na
liście członków. Lider dodaje osoby do swojej grupy i je z niej usuwa bez
administrowania organizacją, więc kierownik działu może dodać nowego pracownika
bez proszenia IT. Lidera wyznacza i odwołuje tylko ktoś z `members:manage`, bo
lider rozdaje dostęp do wszystkiego, co udostępniono grupie.

## Kto może korzystać z nowej rzeczy { #who-can-use-a-new-thing }

Tworzenie agenta, skilla, bazy wiedzy, pliku kontekstu albo wspólnego serwera MCP
zadaje jedno pytanie: **kto może z tego korzystać**.

| Wybór | Kto do tego sięga | Zapisane jako |
|---|---|---|
| **Wszyscy** - domyślnie | Każdy członek organizacji | Widoczność `org` |
| **Tylko ja** | Ty i osoby, którym udostępnisz to później | Widoczność `private` (baza wiedzy staje się osobista) |
| **Wybrane grupy lub osoby** | Członkowie wybranych grup i osoby, które wskażesz | Widoczność `private`, udostępnione każdej z nich na poziomie `use` |

Grupy pojawiają się od razu po wybraniu trzeciej opcji; osoby znajduje się,
wpisując imię albo adres e-mail. Każda wybrana zostaje jako chip, dopóki jej nie
usuniesz.

Członkowie grupy znajdują to, co jej udostępniono, korzystają z tego i podpinają
do własnych agentów. Osoby spoza grupy nie widzą tego na listach, w wyszukiwaniu,
w wyborach Buildera, przez API ani przez AI Architekta, który działa z
uprawnieniami pytającej osoby. Członkowie, których rola sięga do każdego zasobu -
domyślnie właściciel, administrator i builder - nadal widzą wszystko; zobacz
[Uprawnienia](permissions.md).

Aplikacje publikują agenci i na początku są prywatne dla osoby, dla której był
run; grupie udostępnia się je w panelu **Share**. Panel **Sharing** każdego
zasobu dodaje i usuwa grupy także po utworzeniu.

## Serwery MCP działu { #a-departments-mcp-servers }

Serwer MCP organizacji - jedno wspólne konto, podłączone raz - można zawęzić w ten
sam sposób, żeby serwer księgowy Finansów był Finansów. Członkowie zarządzający
serwerami MCP widzą serwery całej organizacji, te, które sami podłączyli, i te
udostępnione ich grupom albo im; właściciele i administratorzy widzą wszystkie.
Builder spoza Finansów nie znajdzie ich serwera na liście, nie otworzy go po
identyfikatorze i nie opublikuje agenta, który go używa. Zobacz
[MCP](mcp.md#personal-or-organization-wide).

Agent, który już go używa, działa dalej dla każdego, kto może go uruchomić. Ten
wybór decyduje o tym, kto może serwer wybrać, a nie o tym, kto dostaje przez
niego odpowiedzi, dlatego Builder pokazuje go tam, skąd pochodzi wiedza agenta.

## Strona grupy { #a-groups-page }

Otwarcie grupy pokazuje jej ludzi i wszystko, co jej udostępniono, pogrupowane
według rodzaju - agenci, bazy wiedzy, skille, kontekst, aplikacje i serwery MCP -
z poziomem udostępnienia każdego. Czytający widzi tylko to, co i tak mógłby
otworzyć, więc członek Sprzedaży czytający stronę Finansów nie dowie się, co
Finanse trzymają.

**Dodaj do tej grupy** udostępnia kilka rzeczy naraz: pokazuje wszystko, co
czytający może edytować, a czego grupa jeszcze nie ma, z wyszukiwarką, polem do
zaznaczenia przy każdej rzeczy i poziomem udostępnienia. Każde to ten sam grant,
który zapisuje panel Share, więc wymaga tego samego prawa do edycji.

Członkowie dostają powiadomienie, gdy coś udostępniono ich grupie - w skrzynce i,
jeśli chcą, e-mailem; *Shared with your group* w ustawieniach powiadomień to
wyłącza. Karty w całej konsoli mówią, dla kogo jest każda rzecz: *Wszyscy*, jej
działy z nazwy albo *Prywatne*.

## Budżet działu { #a-departments-budget }

Administrator może nadać działowi **miesięczny budżet** przy jego tworzeniu lub
edycji. Liczy to, co uruchamiają członkowie działu - każdy agent, bieżący
miesiąc kalendarzowy - i zatrzymuje run członka, gdy dział go wyczerpie, z
odmową, która nazywa dział. Osoba w dwóch działach podlega obu limitom. Zobacz
[poziomy budżetu](governance.md#budgets).

Gdy dział przekroczy 80% swojego miesiąca, jego lider i administratorzy dostają
jedno powiadomienie - w skrzynce i e-mailem, chyba że wyłączą *Department budget
at 80%*. Gdy limit zatrzyma run, dowiadują się ci sami ludzie.

Strona grupy pokazuje miesiąc na tle limitu i eksportuje go do CSV, wiersz na
członka i agenta. Karta **Wydatki działów** na dashboardzie pokazuje miesiąc
każdego działu. Obie wymagają `runs:view`; lider działu może też pobrać jego CSV
z `GET /orgs/{org_id}/groups/{group_id}/spend.csv`.

## Skąd pochodzi wiedza agenta { #where-an-agents-knowledge-comes-from }

Agenta można podpiąć do bazy wiedzy, skilla, pliku kontekstu albo serwera MCP
udostępnionego węższemu gronu niż on sam i nic tego nie zablokuje. Każdy, do kogo
agent dociera, dostaje wtedy odpowiedzi z tego źródła, także osoby, które same nie
mogłyby go otworzyć.

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

Run, którego nie uruchomił nikt z organizacji - harmonogram, gość na kanale -
nie liczy się do budżetu żadnego działu, bo miesiąc działu to to, co uruchomili
jego członkowie.
