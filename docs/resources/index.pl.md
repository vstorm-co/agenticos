---
source_sha: 586f51917e7c
---

# Zasoby { #resources }

Wszystko wokół produktu, a nie w nim: jak uzyskać pomoc, jak współtworzyć i jak
rozszerzać platformę.

## Pomóż AgenticOS { #help-agenticos }

Projekt jest młody, a najszybszym sposobem, żeby mu pomóc, jest używać go i
mówić, co się zepsuło.

<div class="grid cards" markdown>

- :material-bug:{ .lg .middle } **[Zgłoś błąd](https://github.com/vstorm-co/agenticos/issues/new)**

    Co się psuje, jaka sekwencja to wywołuje i po czym poznasz, że zostało
    naprawione. Tego trzeciego brakuje w większości zgłoszeń.

- :material-lightbulb-on:{ .lg .middle } **[Zaproponuj coś](https://github.com/vstorm-co/agenticos/issues)**

    Najpierw sprawdź [mapę zgłoszeń](https://github.com/vstorm-co/agenticos/issues/168)
    — mówi, co jest już zaplanowane, a co nie ma jeszcze zakresu.

- :material-star:{ .lg .middle } **[Daj gwiazdkę repozytorium](https://github.com/vstorm-co/agenticos)**

    To najtańszy sygnał, że warto to ciągnąć dalej.

</div>

## Rozwój - współtworzenie { #development-contributing }

Przeczytaj stronę pasującą do tego, czego dotykasz. To są własne notatki
inżynierskie repozytorium, opublikowane, a nie przepisane, więc czytasz to samo,
co czytają kontrybutorzy.

| Pracujesz nad | Przeczytaj |
|---|---|
| Czymkolwiek, na początek | [Architektura](../architecture.md) · [Kod konsoli](../frontend.md) — trasy → serwisy → repozytoria oraz transakcja żądania |
| Kształtem, który już widziałeś | [Wzorce](../patterns.md) |
| Funkcją od początku do końca | [Dodawanie funkcji](../adding_features.md) |
| Testem albo czerwoną bramką pokrycia | [Testowanie](../testing.md) |
| Pull requestem | [Przegląd kodu](../code-review.md) i [Gałęzie](../branching.md) |

!!! warning "Trzy rzeczy, które cię ugryzą"

    Repozytorium zapisuje przez `db.flush()`, nigdy przez `db.commit()`. Praca w
    tle, która czyta wiersz zapisany właśnie przez żądanie, jest przekazywana
    przez `spawn_after_commit`, nigdy przez `spawn`. A warstwa platformowa jest
    trzymana na 100% pokrycia, egzekwowanym w CI. Wszystkie trzy są w
    [Architekturze](../architecture.md) i [Testowaniu](../testing.md) i
    wszystkie trzy zostały tu przynajmniej raz zrobione źle.

## Rozszerzanie platformy { #extending-the-platform }

Dokładanie do tego, co potrafi samo AgenticOS, w Pythonie. To są przepisy dla
kontrybutorów — potrzebujesz sklonowanego repozytorium.

- [Dodaj capability](../howto/add-capability.md) — nowe narzędzie, które model może wywołać
- [Dodaj serwer do katalogu MCP](../howto/add-mcp-server.md)
- [Dodaj endpoint API](../howto/add-api-endpoint.md)
- [Dodaj zadanie w tle](../howto/add-background-task.md)
- [Dodaj konektor synchronizacji](../howto/add-sync-connector.md)

!!! tip "Zanim napiszesz capability"

    Zastanów się, czy to naprawdę nie jest [połączenie MCP](../mcp.md).
    Capability, która byłaby klientem API jednego produktu SaaS, to serwer, który
    ktoś już napisał, a wzięcie go do tego repozytorium oznacza utrzymywanie go
    wobec API tamtego produktu na zawsze.

## Zbudowane na { #built-on }

AgenticOS jest wygenerowany z
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template)
i stoi na:

- [Pydantic AI](https://ai.pydantic.dev) — runtime agenta
- [FastAPI](https://fastapi.tiangolo.com) i [Pydantic](https://docs.pydantic.dev) — backend
- [pgvector](https://github.com/pgvector/pgvector) — wyszukiwanie
- [Prefect](https://www.prefect.io) — praca w tle
- [Next.js](https://nextjs.org) — konsola
- [Model Context Protocol](https://modelcontextprotocol.io) — każda integracja

## Licencja { #licence }

Apache 2.0. Zobacz
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
