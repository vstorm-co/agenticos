---
source_sha: "d2ccce975127"
---

# Zarządzaj AgenticOS przez klienta AI { #operate-agenticos-with-an-ai-client }

[Plugin AgenticOS](https://github.com/vstorm-co/agenticos/tree/main/plugins/agenticos)
dodaje procedury do narzędzi MCP: wybór sposobu wdrożenia, konfigurację zależności,
budowę rozwiązań i wydawanie przetestowanych agentów. Działa z uprawnieniami
podłączonego członka w jednej organizacji. Instalacja wymaga terminala lub CI.

## Zainstaluj i połącz { #install-and-connect }

```bash
claude plugin marketplace add vstorm-co/agenticos
claude plugin install agenticos@agenticos
claude mcp add --transport http agenticos https://<api-host>/mcp
```

Dokończ OAuth w przeglądarce i wybierz organizację oraz scopes. Ustawienia →
Klienci MCP pokazują polecenia dla poszczególnych klientów. Plugin nie ma stałego
adresu serwera. Zasady dostępu i zatwierdzania opisuje [MCP](../mcp.md).

Wersję bazową sprawdzono na 1.82.2. Nowe narzędzia zależności, jakości i pakietów
korzystają z kontraktu MCP 1, ogłaszanego przez `get_platform_context`. Starszy
serwer nadal udostępnia swoje dotychczasowe narzędzia. Klient musi odkryć funkcje
i scopes; numer wersji nie przyznaje uprawnień. Trasy tylko dla asystenta wymagają
OAuth. Zwykłe klucze organizacji zachowują granicę publicznego API.

## Zbuduj i wydaj rozwiązanie { #build-and-release-a-solution }

Opisz własnymi słowami rezultat, użytkowników, źródła i dozwolone działania.
Klient odkrywa capabilities, node'y workflow, połączenia i istniejące zasoby,
zanim zaprojektuje rozwiązanie. Pakiety obsługi zgłoszeń, repozytorium i onboardingu
są przykładami, a nie zamkniętym katalogiem zastosowań.

Profile modeli mogą wskazywać istniejące identyfikatory vaultu.
`list_secret_references` zwraca tylko dostępne nazwy, ID, rodzaje i przeznaczenia,
bez wartości ani końcówek kluczy. Odkrywanie endpointów embeddingów identyfikuje
lokalne usługi. `get_setup_link` przekazuje wprowadzanie sekretów i zgodę OAuth
do własnej sesji użytkownika w konsoli. Nie wklejaj sekretów ani adresu callback
OAuth do rozmowy lub pakietu.

`plan_solution` waliduje manifest i zwraca jego hash oraz wymagane uprawnienia.
`install_solution` potrzebuje tego hasha, dokładnego manifestu i klucza instalacji.
Tworzy prywatne zasoby i zapis instalacji w jednej transakcji bazy, bez publikacji,
wykonywania, indeksowania ani harmonogramów. Takie samo ponowienie zwraca zapis
instalacji. Inny manifest dla tego samego użytkownika, organizacji i klucza zostaje
odrzucony. Kolejna kopia potrzebuje innego klucza i niekolidujących nazw zasobów.

Logiczne referencje pakietu wiążą agentów z nowymi Context, skillami i wiedzą.
Przygotowanie workflow może zawierać tabelę i jej identyfikator zastępczy. Modele,
embeddingi i połączenia zewnętrzne nadal mają jawne ID konkretnego wdrożenia.
Po instalacji odczytaj zasoby ponownie: zapis instalacji dokumentuje historię,
nie dowodzi braku późniejszych zmian lub usunięcia. Edytuj zasoby ich zwykłymi
operacjami; instalacja nie nadpisuje ich jako aktualizacja pakietu.

Przy wydaniu utwórz dataset z ocenianymi przypadkami, wyceń i uruchom evale,
sprawdź wynik, następnie opublikuj wersję i promuj środowisko. Jeżeli produkcja
śledzi najnowszą wersję, przypnij ją przed publikacją wymagającą etapu staging.
Obowiązują istniejące połączenia testowe, bramki i ograniczenia wyjątków. Rollback
przestawia środowisko na istniejącą wersję, zachowując historię. Zobacz
[Środowiska](../environments.md).

## Sprawdź wdrożenie lub fork { #verify-a-deployment-or-fork }

Skill wdrożeniowy korzysta z istniejącej [procedury dla jednego hosta](../deploy.md),
bootstrapu i polecenia doctor. Skill developerski obsługuje własny prefiks obrazów
forka i PR-y aktualizacji z upstream. MCP platformy nie przyznaje dostępu SSH ani
dostępu do chmury.

Sprawdzenie lokalne w odizolowanym środowisku, z checkoutu:

```bash
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0
# Wykonaj pokazany plan i zapisz raport poza środowiskiem tymczasowym:
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0 --run --report /tmp/agenticos-smoke.json
```

Test używa opublikowanych obrazów, osobnego projektu Compose, wygenerowanych
lokalnych danych logowania i deterministycznego modelu lokalnego. Inicjalizuje
organizację, sprawdza konsolę i API oraz kończy uruchomienie agenta przez prawdziwego
klienta MCP. Następnie usuwa swoje kontenery i wolumeny. Sprawdza działanie platformy,
nie jakość modelu, płatnego dostawcę, zewnętrzny DNS ani produkcyjny TLS.
