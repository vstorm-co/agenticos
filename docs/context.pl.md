---
source_sha: "6ed5be54f7ae"
---

# Pliki kontekstowe { #context-files }

**Plik kontekstowy** to kawałek stałej wiedzy napisany raz i podpięty do wielu
agentów: słownik pojęć, opis tonu marki, macierz eskalacji, lista produktów,
które naprawdę sprzedajesz.

Jeśli pisałeś kiedyś `AGENTS.md` dla agenta kodującego, to jest ta sama idea w
tym samym kształcie — plik w Markdownie mówiący, jak się tu robi rzeczy, trzymany
obok pracy, a nie w środku jednego promptu. Różnica jest w tym, kto go czyta:
`AGENTS.md` w repozytorium czyta cokolwiek akurat je otworzy, a plik kontekstowy
tutaj jest podpięty do agentów, których wybierzesz, wersjonowany razem z nimi i
edytowalny przez osobę, która naprawdę zna odpowiedź.

To odpowiedź na problem, który każda firma napotyka przy swoim trzecim agencie —
te same trzy akapity wklejone do trzech zestawów instrukcji, a potem poprawione
w jednym z nich.

W kreatorze agenta **Context → New context file** tworzy plik bezpośrednio w panelu zdolności, dołącza go do bieżącego szkicu i włącza Context. Następnie możesz wybrać sposób użycia pliku przez tego agenta. Publikacja pozostaje osobnym krokiem. Tworzenie wymaga uprawnień do edycji agenta i plików contextu.

## Gdzie leży, między skillami a wiedzą { #where-it-sits-between-skills-and-knowledge }

Trzy rzeczy podają modelowi tekst, a zły wybór między nimi to zwykła przyczyna
agenta, który albo ignoruje to, co mu powiedziano, albo nie czyta niczego.

|                                           | Co trzyma                                                                             | Kiedy model to widzi                               |
| ----------------------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Plik kontekstowy**                      | Stałe fakty, krótkie i niezmienne — słownik, przewodnik po tonie, schemat organizacji | Zawsze albo na żądanie — Ty wybierasz              |
| **[Skill](skills.md)**                    | Procedurę dla jednego rodzaju zadania — jak obsłużyć wniosek o zwrot                  | Kiedy model uzna, że dzieje się właśnie to zadanie |
| **[Kolekcja wiedzy](file-processing.md)** | Korpus zbyt duży, by go przeczytać — każdy dokument polityki, każde zgłoszenie        | Tylko te fragmenty, które zwróci wyszukiwanie      |

Zasada praktyczna: **jeśli coś jest krótkie i zawsze istotne, to plik
kontekstowy. Jeśli jest długie, to wiedza. Jeśli to procedura, to skill.**

Strona **Context** pokazuje na karcie początek każdego pliku. `GET
/api/v1/context` zwraca go jako `excerpt`: kilka ograniczonych linii, nigdy całą
treść.

## Dwa tryby, a różnica między nimi to koszt { #two-modes-and-the-difference-is-cost }

Każde przypięcie pliku ma tryb w ustawieniach capability **Context** agenta. Ten sam wspólny plik można wstrzykiwać u jednego agenta, udostępniać na żądanie u drugiego lub wyłączyć u trzeciego.

=== "`inject` — zawsze obecny"

    Treść jest wklejana do instrukcji agenta dosłownie. Model zna ją zawsze,
    bez decydowania, czy zajrzeć, i bez wywołania narzędzia.

    Używaj go do rzeczy, których agent nigdy nie może pomylić: jak nazywają się
    Twoje produkty, do kogo eskalować, jak mówić o firmie.

    **Jest czytany w każdej turze**, więc jest częścią kosztu każdej wiadomości.
    Wstrzykiwane pliki trzymaj krótkie.

=== "`link` — czytany na żądanie"

    Treść zostaje poza promptem i jest wystawiona przez narzędzie. Model czyta
    ją tylko wtedy, gdy uzna plik za istotny, wybierając po nazwie i po
    jednozdaniowym opisie, który piszesz.

    Używaj go do materiałów, które liczą się czasami: rzadko potrzebnej
    polityki, regionalnego wariantu, długiej listy.

    Nie kosztuje nic w turach, które go nie potrzebują, i nie kosztuje nic w
    ogóle, jeśli model nigdy nie zajrzy — co jest jednocześnie ryzykiem.

!!! tip "Opis pisz dla modelu, nie dla człowieka"

    Linkowany plik jest wybierany wyłącznie po nazwie i opisie. „Polityka
    zwrotów” mówi modelowi mniej niż „kiedy klient może zwrócić towar, jakie są
    terminy i trzy wyjątki” — a ta różnica decyduje o tym, czy plik zostanie
    kiedykolwiek otwarty.

## Podpinanie ich do agenta { #attaching-them-to-an-agent }

Pliki kontekstowe należą do organizacji, nie do agenta. Piszesz jeden, a wiąże
się z nim dowolna liczba agentów.

Włącz na agencie capability **Context**, a potem podepnij pliki, które ma mieć.
Edycja pliku później zmienia to, co wie każdy związany z nim agent **przy jego
następnym runie** — bez ponownej publikacji, żadnego z nich.

O to właśnie chodzi i na to właśnie trzeba uważać: zmiana w pliku wstrzykiwanym
jest zmianą w każdym agencie, który go niesie. Traktuj go jak wspólny, nośny
tekst, którym jest.

W Builderze każdy wybrany plik ma przełącznik **Używaj w tym agencie** i wybór trybu. Te ustawienia należą do szkicu agenta i zaczynają działać po publikacji. Edytor biblioteki zmienia tylko wspólną treść i opis; format wynika z nazwy pliku. Istniejące wersje agentów bez indywidualnych ustawień zachowują poprzedni tryb i dostępność.

Capability pozwala też wyłączyć narzędzie do odczytu. Wyłączenie narzędzia do
czytania oznacza, że do modelu trafiają tylko pliki wstrzykiwane i nic nie jest
czytane na żądanie — rozsądny wybór, gdy chcesz, żeby wejścia agenta były
całkowicie przewidywalne.

Można też zacząć od pliku: **Dodaj do agenta** na jego karcie dodaje go do
szkicu agenta razem z włączoną capability Kontekst, a karta mówi, którzy agenci
już go mają. Baza wiedzy ma tę samą akcję na swojej stronie.

## Zmiany proponowane przez asystenta { #changes-the-assistant-proposes }

**Ulepsz z asystentem**, w edytorze pliku, prosi
[asystenta tworzenia](authoring.md#context-files) o lepszą treść, napisaną na
podstawie runów agentów, którzy czytają plik. To, co proponuje, nie jest
stosowane: czeka nad listą na stronie Context, z uzasadnieniem, runami, na
których się opiera, i agentami, do których plik jest podpięty.

Zastosowanie jej to to samo co ręczna edycja pliku - działa od razu dla każdego
agenta, którego opublikowana wersja czyta plik - więc najpierw jest
**Sprawdź evalami**, na jednym z tych agentów. Obok **Zastosuj** zmiana mówi, co
robi jej zastosowanie: dla jakich agentów i środowisk zacznie działać, które
suity evali ustawi w kolejce i którzy strażnicy sprawdzą ją dopiero przy
następnej promocji agenta. Plik, który ktoś edytował po zaproponowaniu zmiany,
odrzuca ją; ta edycja nigdy nie zostaje nadpisana.

Ponowna prośba do asystenta przepisuje czekającą zmianę, zamiast dodawać drugą.
Decyzja wskazuje wersję zmiany, którą przeczytałeś, więc z dwóch podjętych
naraz liczy się tylko jedna, a strona otwarta przed przepisaniem jest odrzucana
z komunikatem „The proposal changed since you opened it”, dopóki nie przejrzysz
nowej wersji. Zmiana, która mówi to, co plik już mówi, w ogóle nie jest
proponowana.

Każda edycja pliku - zastosowana albo zrobiona ręcznie - i jego usunięcie
ustawiają w kolejce suity evali uruchamiane po zmianie zależności, dla każdego
agenta, który go czyta, a zastosowanie zmiany powiadamia właścicieli tych
agentów.

## Dostęp { #access }

Plik kontekstowy ma właściciela i widoczność, jak każdy inny zasób tutaj, a
`context:view` bramkuje odczyt katalogu. Plik, do którego ktoś nie dostał grantu,
to plik, którego nie może podpiąć, i decydują o tym [te same trzy
warstwy](permissions.md) co wszędzie indziej.

Nic naprawdę tajnego nie trafia do takiego pliku — plik kontekstowy to tekst,
który agent czyta na głos, gdy zadać mu właściwe pytanie. Poświadczenia należą do
[vaultu](secrets.md).

## Podsumowanie { #recap }

- Plik kontekstowy to **stała wiedza napisana raz i związana z wieloma agentami**.
- **`inject`** jest zawsze w prompcie i kosztuje w każdej turze; **`link`** jest
  czytany na żądanie i nie kosztuje nic, dopóki nie zostanie przeczytany.
- Linkowany plik jest wybierany po **opisie**, więc pisz go dla modelu.
- Edycja pliku aktualizuje **każdego związanego agenta przy jego następnym
  runie**, bez publikowania czegokolwiek.
- Krótkie i zawsze istotne → kontekst. Długie → [wiedza](file-processing.md).
  Procedura → [skill](skills.md).
