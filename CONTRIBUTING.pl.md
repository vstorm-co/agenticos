---
source_sha: "7cb876b5ef26"
---

<!-- source_sha: 7cb876b5ef26 -->

# Współtworzenie AgenticOS

[English](CONTRIBUTING.md) · **Polski** · [Deutsch](CONTRIBUTING.de.md) · [Español](CONTRIBUTING.es.md)

Dzięki, że zaglądasz. Ten dokument jest oszczędny w ceremoniale i konkretny w
tym, co faktycznie sprawia, że pull requesty są odrzucane.

## Poprzeczka

Kod wchodzi wtedy, gdy maintainer scaliłby go bez zmian. Konkretnie:

- **W pełni otypowany.** Żadnego `Any`, żadnego `# type: ignore`, żadnego
  `except:`, przez które błąd znika. Modeluj precyzyjnymi typami, nie luźnymi
  słownikami.
- **Błędy są głośne.** Przerwij z czytelnym komunikatem; nigdy nie połykaj
  wyjątku i nie zaklejaj buga fallbackiem. Cicha błędna odpowiedź jest gorsza
  niż awaria.
- **Żadnego balastu.** Żadnych spekulatywnych abstrakcji, nieużywanych
  parametrów, zakomentowanego kodu ani gałęzi „na wszelki wypadek”.
- **Komentarze wyjaśniają *dlaczego*.** To, co kod robi, widać; dlaczego robi to
  właśnie tak — już nie, a tego właśnie potrzebuje czytelnik za pół roku.
- **Dopasuj się do otaczającego kodu.** Jego idiomy wygrywają z osobistymi
  preferencjami.

## Przygotowanie środowiska

```bash
make dev            # postgres, redis, api, worker, frontend
make seed           # an organization, an owner, a default model profile
```

Backend potrzebuje `VAULT_MASTER_KEY`. Bez niego schodzi do `SECRET_KEY`, co
lokalnie jest w porządku, a na produkcji zostaje odrzucone.

## Uruchamianie testów

Pełny obraz jest w [`CLAUDE.md`](CLAUDE.md#testing). Krótka wersja:

```bash
make test               # backend, with the coverage gate
make test-frontend      # vitest unit + integration, no coverage
make test-frontend-cov  # the same, plus the gate CI applies
make test-e2e           # playwright
make check              # every CI job except e2e — run this before a pull request
```

**`make test-frontend` nie mierzy pokrycia, a jedyną bramką frontendu jest próg
pokrycia.** To jest pętla; odpowiedzią jest `make check`.

**Warstwa platformy jest trzymana na 100% pokrycia** i CI tego pilnuje. Chodzi o
`app/agents/`, katalog uprawnień, vault i zbudowane na nich serwisy. Podsystemy
odziedziczone z szablonu (pipeline RAG, konektory, adaptery kanałów) są
raportowane, ale nie są bramką dla buildu — trzymanie kodu, którego nie
projektowaliśmy, przy tej samej poprzeczce oznaczałoby testy naszpikowane
mockami, które kupują liczbę, a nie pewność.

Jeśli dodajesz plik do warstwy platformy, potrzebuje on testów, które nie
przeszłyby, gdyby zachowanie się zmieniło. Test, który przechodzi wyłącznie
szczęśliwą ścieżkę, się nie liczy.

## Architektura w jednym akapicie

Agent to **dane**, a nie kod. `AgentSpec` jest kontraktem: Builder go edytuje,
baza danych wersjonuje, `app/agents/factory.py` tworzy z niego instancję, a
klient może go zacommitować jako YAML do własnego repozytorium git. Wszystko, z
czego agent jest złożony, to **capability** — wyszukiwanie w wiedzy, research w
sieci, strażnik budżetu, zestaw skilli — zadeklarowane w kodzie z metadanymi i
składane przez konfigurację. Konfiguracja może sięgnąć wyłącznie po to, co
zarejestrował kod.

Wynikają z tego dwie zasady i większość komentarzy z review sprowadza się do
nich:

**Id są na zawsze.** Id capability pojawia się w zapisanych specach i w
repozytoriach klientów. Nazwę klasy w Pythonie zmieniaj do woli; zmiana id to
breaking change.

**Waliduj przy publikacji, nie w czasie działania.** Zepsuty agent ma zostać
odrzucony wtedy, gdy ktoś patrzy na formularz, a nie o trzeciej w nocy w
rozmowie z klientem.

## Dodanie capability

Jeden katalog w `app/agents/capabilities/`, o kształcie takim jak pozostałe:

```
app/agents/capabilities/your_thing/
    __init__.py        # registration + public exports
    _capability.py     # the AbstractCapability subclass
    _toolset.py        # its tools, if it has any
    README.md          # the decisions behind it, not a description of the code
```

Zarejestruj ją w `load_builtins()` w `_registry.py`, bo inaczej — z punktu
widzenia Buildera — nie istnieje; to sprzężenie jest celowe.

Jeśli capability może działać na świat zewnętrzny, oznacz ją
`side_effecting=True`. To ustawia zatwierdzenie przez człowieka jako domyślne, a
zapomniana flaga jest tym, przez co agent kończy, wysyłając maile bez nadzoru.

## Pull requesty

- Jedna sprawa na PR. Refaktor i funkcja w jednym diffie nie zostaną
  zreviewowane ani jako jedno, ani jako drugie.
- Bugi jadą z testem regresji, który bez poprawki nie przechodzi.
- W opisie napisz, co zdecydowałeś i dlaczego. Co — pokazuje kod.

## Bezpieczeństwo

Nie zakładaj publicznego issue na podatność. Zobacz [`SECURITY.md`](SECURITY.md).

## Licencja

Wnosząc wkład, zgadzasz się, że Twoja praca jest licencjonowana na Apache
License 2.0, na tych samych warunkach co reszta tego repozytorium. Nie ma CLA.
