---
source_sha: "c51412640202"
title: "Odpowiadaj na pytania z bazy danych"
description: "Podłącz samodzielnie hostowany serwer MCP dla Postgresa za rolą tylko do odczytu i schematem zawierającym wyłącznie widoki, a potem pozwól agentowi go odpytywać."
---

# Odpowiadaj na pytania z bazy danych { #answer-questions-from-your-database }

Podłącz serwer MCP dla Postgresa, żeby agent mógł odpowiadać na pytania z Twojej własnej bazy danych, a wcześniej postaw między agentem a tabelami rolę tylko do odczytu i schemat zawierający wyłącznie widoki. To instrukcja wykonania, a nie raport z pomiaru wdrożenia. Serwera MCP, którego wymaga ten przepis, nie da się osiągnąć z tej instalacji, z powodu opisanego niżej, więc nic tu nie zostało uruchomione od początku do końca z działającym agentem.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Serwer MCP dla Postgresa, który uruchamiasz sam, dostępny pod adresem URL, z którym to wdrożenie może się połączyć. Wpis `postgres` w katalogu jest dokładnie tym: bez hostowanego adresu, z tokenem bearer, który sprawdza *Twój własny serwer*, i z ostrzeżeniem, żeby kierować go na widoki tylko do odczytu, a nie na bazę główną z prawem zapisu. Zobacz [katalog](../mcp.md#data-and-analytics).
- `connections:manage`, żeby zarejestrować połączenie organizacji.

## Dlaczego rola tylko do odczytu i schemat z samymi widokami { #why-a-read-only-role-and-a-views-only-schema }

**Narzędzia MCP są poza bramką zatwierdzeń.** Narzędzia capability mogą czekać na zatwierdzenie przez człowieka, narzędzia serwera MCP nie. Nie ma przeglądu SQL-a, który uruchamia narzędzie zapytań agenta, przy każdym wywołaniu. Cokolwiek może podłączony serwer, agent może bez pytania. Zobacz [narzędzia MCP są poza bramką zatwierdzeń](../governance.md#an-approval-inside-a-delegation). Granicą musi być samo poświadczenie do bazy, a nie ustawienie agenta.

Robią to dwie decyzje:

- **Rola bez uprawnień do zapisu**, żeby najgorsze, co może zrobić błędne albo zmanipulowane zapytanie, to odczytać coś, czego nie powinno, a nigdy nie zmienić ani nie usunąć wiersza.
- **Schemat z widokami, a nie tabelami bazowymi**, nadany tej roli zamiast samych tabel. Widok może pominąć kolumny, których model nie powinien widzieć, i z góry agregować to, co zwraca. To jednocześnie granica prywatności i tańsze zapytanie do napisania dla agenta.

## Przygotuj dane wejściowe { #prepare-the-input }

Mała syntetyczna tabela `orders` w osobnej bazie danych:

```sql
CREATE TABLE orders (
    id           serial PRIMARY KEY,
    customer     text NOT NULL,
    status       text NOT NULL CHECK (status IN ('paid', 'refunded', 'pending')),
    amount_cents integer NOT NULL,
    created_at   date NOT NULL
);

INSERT INTO orders (customer, status, amount_cents, created_at) VALUES
    ('Ada',     'paid',     4200, '2026-09-01'),
    ('Grace',   'paid',     1800, '2026-09-02'),
    ('Ada',     'refunded', 4200, '2026-09-03'),
    ('Rex',     'paid',     9900, '2026-09-05'),
    ('Grace',   'pending',  2500, '2026-09-06'),
    ('Linus',   'paid',     3300, '2026-09-06'),
    ('Rex',     'paid',     1500, '2026-09-08'),
    ('Ada',     'paid',     6000, '2026-09-09');
```

Schemat zawierający wyłącznie widoki i rola, jako którą uwierzytelnia się connection string serwera MCP:

```sql
CREATE SCHEMA reporting;

CREATE VIEW reporting.daily_paid_totals AS
SELECT created_at, count(*) AS paid_orders, sum(amount_cents) AS paid_amount_cents
FROM orders
WHERE status = 'paid'
GROUP BY created_at
ORDER BY created_at;

CREATE VIEW reporting.status_counts AS
SELECT status, count(*) AS orders, sum(amount_cents) AS amount_cents
FROM orders
GROUP BY status
ORDER BY status;

CREATE ROLE shop_readonly LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE shop_demo TO shop_readonly;
GRANT USAGE ON SCHEMA reporting TO shop_readonly;
GRANT SELECT ON reporting.daily_paid_totals, reporting.status_counts TO shop_readonly;
REVOKE ALL ON SCHEMA public FROM shop_readonly;
```

Odpowiedź referencyjna, żeby sprawdzić odpowiedź ze źródłowymi wierszami: `status_counts` daje paid 6 zamówień / 26700 centów, pending 1 / 2500, refunded 1 / 4200. Bezpośrednie zapytanie `shop_readonly` do `orders` jest odrzucane komunikatem `permission denied for table orders`, więc widoki są jedynymi drzwiami.

## Podłącz serwer { #connect-the-server }

1. W **Toolbox → MCP servers** agenta wybierz **Connect a server** i z katalogu **PostgreSQL** albo podłącz go raz w **MCP servers** w ustawieniach organizacji, żeby mogło go przypisać więcej niż jednego agenta.
2. Skieruj połączenie na własny działający serwer MCP dla Postgresa (na przykład [`crystaldba/postgres-mcp`](https://github.com/crystaldba/postgres-mcp)) skonfigurowany z connection stringiem `shop_readonly` i w ograniczonym trybie tylko do odczytu. Jako token połączenia wklej token bearer, który sprawdza ten serwer, a nie hasło do bazy.
3. W przypisaniu agenta zawęź `allowed_tools` do narzędzi tylko do odczytu, które udostępnia serwer, dodatkowo względem tego, na co pozwala już samo połączenie.
4. Przypisz tylko to połączenie, ustaw budżet i instrukcje, które nazywają dwa widoki i każą agentowi powiedzieć, gdy pytanie wymaga kolumny albo tabeli, której widoki nie mają, zamiast zgadywać.

## Dlaczego nie dało się tego tu uruchomić { #why-this-could-not-be-run-here }

Próba podłączenia serwera do tej instalacji została odrzucona:

```text
This MCP server URL cannot be used: Blocked: 'localhost' resolves to
private/internal address '::1'. SSRF protection does not allow requests to
internal networks.
```

Adres URL połączenia MCP jest zawsze odrzucany dla każdego adresu loopback, prywatnego, link-local albo ze współdzielonej puli CGNAT. Nie ma wyjątku dla środowiska lokalnego, bo ta sama kontrola chroni też `cdp_url` i każdy krok wykrywania OAuth. Zobacz [adres URL, do którego to wdrożenie nie może sięgać, jest odrzucany](../mcp.md#a-connection). Serwera MCP dla Postgresa dostępnego tylko pod `localhost` albo adresem w sieci prywatnej, czyli tam, gdzie zwykle uruchamia się go po raz pierwszy, nie da się podłączyć z maszyny tego samego wdrożenia. Potrzebny jest routowalny adres przed serwerem: mały host z publicznym albo dostępnym przez VPN IP albo tunel.

Powyższy SQL został uruchomiony i sprawdzony bezpośrednio w Postgresie. Odmowa dla roli i podane sumy z widoków są prawdziwe. Nie zweryfikowano tego, że agent faktycznie odpytuje bazę przez podłączony serwer, bo serwera nigdy nie dało się podłączyć.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pytanie o sumę opłaconych zamówień | 26700 (sześć opłaconych zamówień) |
| Pytanie o zamówienia oczekujące | 2500 (jedno zamówienie) |
| Pytanie o kolumnę, której nie udostępnia żaden widok (np. nazwę klienta) | Agent mówi, że nie odpowie na to na podstawie tego, co ma przypisane |
| Zapytanie, którego rola nie może wykonać (update, delete) | Odrzucone przez bazę, `permission denied` |
| `allowed_tools` zawężone do narzędzi tylko do odczytu | Narzędzia do zapisu, które oferuje serwer, w ogóle nie ma w zestawie narzędzi modelu |

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Połączenie jest odrzucane z komunikatem o SSRF.** Adres serwera to loopback, adres prywatny albo inny wewnętrzny dla sieci tego wdrożenia; zobacz wyżej. Postaw przed nim routowalny adres.
- **Agent czyta tabelę bazową zamiast widoków.** `shop_readonly` dostała uprawnienia do `public` oprócz `reporting` albo nigdy nie odebrano jej schematu tabeli bazowej. Uruchom ponownie `REVOKE` z góry.
- **Zapytanie agenta wygląda, jakby coś zmieniło.** Nie mogło, jeśli rola naprawdę nie ma uprawnień do zapisu. Sprawdź uprawnienia roli, zanim uznasz, że agent zachował się źle.
- **Test połączenia przechodzi, ale Builder nie pokazuje żadnych narzędzi.** Nic go jeszcze nie odpytało albo ostatnie sprawdzenie się nie powiodło. `POST /mcp-connections/{id}/test` je odświeża.
- **Dwa agenty potrzebują różnego dostępu do tej samej bazy.** Podłącz serwer dwa razy, pod dwiema nazwami, każdy z własną rolą i własnymi widokami. Jeden serwer, dwa poświadczenia, nigdy jedna rola poszerzona pod bardziej wymagającego agenta.

## Zapisz próbę { #record-the-trial }

Zachowaj SQL, który utworzył dane testowe, uprawnienia roli, definicje widoków, `allowed_tools` połączenia i `allowed_tools` na poziomie przypisania agenta. Człowiek nadal decyduje, które kolumny należą do widoku, zanim agent w ogóle do niego sięgnie. Zawężanie dostępu, gdy agent już zadaje pytania, to znacznie trudniejsza rozmowa niż decyzja podjęta na początku.
