---
source_sha: f5fcd6aff7b4
---

# Pliki kontekstowe { #context-files }

**Plik kontekstowy** to kawałek stałej wiedzy napisany raz i podpięty do wielu
agentów: słownik pojęć, opis tonu marki, macierz eskalacji, lista produktów,
które naprawdę sprzedajesz.

To odpowiedź na problem, który każda firma napotyka przy swoim trzecim agencie —
te same trzy akapity wklejone do trzech zestawów instrukcji, a potem poprawione
w jednym z nich.

## Gdzie leży, między skillami a wiedzą { #where-it-sits-between-skills-and-knowledge }

Trzy rzeczy podają modelowi tekst, a zły wybór między nimi to zwykła przyczyna
agenta, który albo ignoruje to, co mu powiedziano, albo nie czyta niczego.

| | Co trzyma | Kiedy model to widzi |
|---|---|---|
| **Plik kontekstowy** | Stałe fakty, krótkie i niezmienne — słownik, przewodnik po tonie, schemat organizacji | Zawsze albo na żądanie — Ty wybierasz |
| **[Skill](skills.md)** | Procedurę dla jednego rodzaju zadania — jak obsłużyć wniosek o zwrot | Kiedy model uzna, że dzieje się właśnie to zadanie |
| **[Kolekcja wiedzy](file-processing.md)** | Korpus zbyt duży, by go przeczytać — każdy dokument polityki, każde zgłoszenie | Tylko te fragmenty, które zwróci wyszukiwanie |

Zasada praktyczna: **jeśli coś jest krótkie i zawsze istotne, to plik
kontekstowy. Jeśli jest długie, to wiedza. Jeśli to procedura, to skill.**

## Dwa tryby, a różnica między nimi to koszt { #two-modes-and-the-difference-is-cost }

Każdy plik kontekstowy niesie tryb, a tryb decyduje o tym, jak plik dociera do
modelu.

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

Ta capability ma jedno ustawienie warte poznania. Wyłączenie narzędzia do
czytania oznacza, że do modelu trafiają tylko pliki wstrzykiwane i nic nie jest
czytane na żądanie — rozsądny wybór, gdy chcesz, żeby wejścia agenta były
całkowicie przewidywalne.

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
