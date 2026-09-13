---
source_sha: 7e69c0532818
---

# Polecenia { #commands }

Ten projekt udostępnia polecenia przez dwa interfejsy: cele **Make** dla typowych
przepływów pracy oraz **CLI projektu** dla precyzyjnej kontroli.

## Polecenia Make { #make-commands }

Uruchamiaj je z katalogu głównego projektu.

### Szybki start { #quick-start }

| Polecenie | Opis |
|---------|-------------|
| `make quickstart` | Uruchamia Dockera, wykonuje migracje, tworzy użytkownika admina. **Nie** instaluje zależności — najpierw `make install` |
| `make install` | Cała ścieżka konfiguracji: `backend/.env` z pliku przykładowego, jeśli go nie ma, zależności backendu przez uv, `frontend/node_modules` przez bun oraz hooki pre-commit. Wszystko to, bo `make check` wszystkiego tego potrzebuje — `db-check` czyta plik env, a eslint, prettier, tsc, vitest i next żyją wyłącznie w `node_modules`. Jedno i drugie jest per checkout, więc należy się przy każdym klonie; istniejący `.env` nigdy nie jest nadpisywany |

### Rozwój { #development }

| Polecenie | Opis |
|---------|-------------|
| `make run` | Uruchamia serwer deweloperski z hot reloadem |
| `make run-prod` | Uruchamia serwer produkcyjny (0.0.0.0:8000) |
| `make routes` | Pokazuje wszystkie zarejestrowane trasy API |
| `make test` | Zestaw testów backendu plus bramka 100% na warstwie platformy. Biegnie w wielu procesach roboczych (`-n auto --maxprocesses 4`); `pytest-cov` scala ich dane, więc bramka pozostaje ta sama |
| `make test-cov` | Uruchamia testy z raportem pokrycia (HTML + terminal). Biegnie w wielu procesach roboczych, tak jak `make test` |
| `make format` | Automatycznie formatuje kod — ruff na backendzie, prettier na frontendzie |
| `make lint` | Każde sprawdzenie statyczne: ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, skrypty strażnicze (backtick, i18n, trasy, komentarze-banery), sprawdzenie zależności przez knip oraz codespell nad całym drzewem |
| `make lint-backend` / `make lint-frontend` | Jedna połowa powyższego. CI uruchamia je w dwóch różnych zadaniach, więc każde da się uruchomić osobno |
| `make dead-code` | Nieużywane funkcje i metody — vulture na niższym poziomie pewności niż bramka `lint`, plus pełny raport knipa na frontendzie. Raport do przeczytania, a nie bramka: w kodzie sterowanym rejestrami przychodzi z fałszywymi trafieniami (polecenie CLI, hook capability), więc przeczytaj każde przed usunięciem. Ta sama rola, jaką `dependency-freshness` pełni dla zależności. Jego jedyna jednoznaczna połowa — paczka w `package.json`, której nic nie importuje — bramkuje za to w `lint-frontend` (`bun run lint:deps`), bo to zależność, która przez miesiące przetrwała nieużywana, była powodem powstania tego sprawdzenia |
| `make lint-spelling` | codespell nad każdym śledzonym plikiem. Hook pre-commit czyta tylko pliki, których dotyka commit, więc literówka, która wjechała razem ze swoim plikiem, czeka tam, by odrzucić czyjś niezwiązany commit |
| `make lint-precommit` | yamlfmt, zizmor i podstawy `pre-commit-hooks` nad każdym śledzonym plikiem. Ten sam powód co przy `lint-spelling` — te hooki działają per plik, więc podbicie `rev:`, które przynosi nową regułę, psuje drzewo, a nic tego nie zauważa. `SKIP` pomija hooki, które `lint-backend`/`lint-frontend`/`lint-spelling` już bramkują, więc ani nie podwaja ich czasu, ani nie pozwala fixerowi przepisać pliku w trakcie sprawdzania |
| `make build-frontend` | `next build`. Sprawdza typy w drzewie tras i zawodzi na komponencie serwerowym, który nie potrafi się wyrenderować — czego nie widzi ani tsc, ani vitest |
| `make desktop-dev` / `make desktop-build` | Otwiera albo pakuje powłokę desktopową - okno Tauri wokół konsoli, którą wskazujesz adresem. Wymaga Rusta i webview platformy; resztę ma `docs/desktop.md` |
| `make desktop-check` | `bun test` nad petem, następnie rustfmt, clippy z ostrzeżeniami traktowanymi jak błędy i testy Rusta powłoki. Nie ma tego w `lint` ani w `check`, bo CI nie ma jeszcze toolchaina Rusta |
| `make audit` | Audytuje zablokowany zestaw zależności pod kątem znanych podatności. Wymaga sieci — jedno żądanie na każdą zablokowaną dystrybucję — więc jego ostatnia linia mówi, w którym z czterech stanów się skończyło, zamiast zostawiać czerwony przebieg niejednoznacznym. Patrz niżej |
| `make sandbox-token` | Generuje własny `SANDBOXD_TOKEN` usługi sandboksa do `backend/.env`, raz. `make dev` uruchamia to za ciebie; nigdy nie generuje go ponownie, bo nowy token osierocia każdy workspace, który usługa trzyma. Formularz połączenia proponuje zapisanie tej samej wartości w vaulcie, więc nie trzeba jej nigdzie wklejać |
| `make clean` | Usuwa pliki cache (__pycache__, .pytest_cache itp.) |

### Przed pull requestem { #before-a-pull-request }

!!! success "`make check` to każde zadanie CI poza `e2e`"

    Ta równość jest utrzymywana, a nie deklarowana, i to
    `backend/tests/test_ci_parity.py` trzyma ją prawdziwą. Rozjechała się cztery
    razy.

`.github/workflows/ci.yml` woła te same cele Make, zamiast powtarzać ich
polecenia, więc bramkujące zadanie, któremu przybywa krok nieuruchamiany przez
`check`, wywraca test parzystości — tak samo jak sytuacja odwrotna.

```bash
make check   # lint, test, db-check, test-frontend-cov, build-frontend, docs-build, audit
```

Około pięciu minut, szeregowo, na rozgrzanym cache. Co celowo pomija:

| Czego nie ma w `check` | Dlaczego i co uruchomić zamiast tego |
|---|---|
| `e2e` | Wymaga zmigrowanej bazy danych, zaszczepionej organizacji i działającego backendu: `make dev && make platform-bootstrap && make test-e2e` |
| Budowanie, publikacja i skan Trivy obrazu | `.github/workflows/images.yml` uruchamia je przy pushu do `main` i przy tagu `v*`, i publikuje do GHCR |
| `make test-migrations` | CI przepuszcza cały łańcuch przez jednorazową bazę `test_db`. Na laptopie `alembic downgrade base` wskazuje na to, co mówi `backend/.env`, czyli zwykle na bazę z twoją własną pracą — `uv run pytest tests/test_migrations.py` zadaje to samo pytanie na własnej bazie, a `make test` i tak już to uruchamia |

!!! warning "Jedna luka, której nie zamknie żadne polecenie"

    Zadanie `test` w CI ma obok siebie Postgresa, więc `tests/integration/` tam
    działa; lokalnie pomija się samo, gdy nic nie odpowiada na 5432. `make check`
    mówi o tym na końcu, kiedy tak się dzieje — uruchom najpierw `make docker-db`,
    jeśli zmiana jest gdziekolwiek blisko bazy danych.

### Co oznacza czerwone `make audit` { #what-a-red-make-audit-means }

`make audit` eksportuje to, do czego rozwiązuje się plik blokad — czyli to, co
instaluje wdrożenie — i podaje to `pip-audit`, które po kolei pyta kanał
podatności o każdą z 254 zablokowanych dystrybucji. `pip-audit` sam z siebie nie
potrafi powiedzieć, która z dwóch bardzo różnych rzeczy poszła źle: kończy się
kodem 1 zarówno wtedy, gdy znalazł zgłoszenie, jak i wtedy, gdy zginął na
`ReadTimeout` w drodze po nie, a `Security Scan` jest wymaganym sprawdzeniem —
więc jedna wolna odpowiedź z 254 blokuje merge, czytając się dokładnie jak
prawdziwe znalezisko, dopóki ktoś nie otworzy loga
([#855](https://github.com/vstorm-co/agenticos/issues/855)).

`scripts/audit_dependencies.py` stoi pomiędzy nimi i **kończy każdy przebieg
jedną linią**:

```
AUDIT: CLEAN — no known advisories against 254 locked dependencies
AUDIT: VULNERABLE — 6 known advisories in 1 of 254 locked dependencies
AUDIT: NETWORK — unreachable (ReadTimeout) after 3 attempts; no audit was performed
AUDIT: FAILED — pip-audit reached no verdict in 3 attempts and did not say why; no audit was performed
```

| Stan | Znaczy | Co zrobić |
|---|---|---|
| `CLEAN` | Każda zablokowana zależność została zaudytowana, żadna nie ma znanego zgłoszenia | Nic |
| `VULNERABLE` | Zablokowana zależność ma znane zgłoszenie. Identyfikatory, naprawione wersje i aliasy CVE są wypisane nad werdyktem | Zaktualizuj ją |
| `NETWORK` | Audyt się nie odbył, a przyczyną była rozpoznawalnie sieć | Uruchom ponownie |
| `FAILED` | Audyt się nie odbył, a przyczyny nie rozpoznano. Własne wyjście pip-audit jest na stderr | Przeczytaj to wyjście |

**Linia, a nie kod wyjścia, bo make nie potrafi go przenieść.** GNU Make zamienia
każdą nieudaną receptę we własne wyjście 2, więc `make audit` zwraca 2 zarówno dla
`VULNERABLE`, jak i dla `NETWORK`, i nie ma takiego kształtu celu, który by to
zmienił. Cokolwiek czyta wynik przez ten interfejs — zadanie `Security Scan`
włącznie — czyta tę linię: `make audit | tail -1` albo
`make audit 2>&1 | grep '^AUDIT:'`. Wewnątrz zadania GitHuba ta sama linia jest
dopisywana do `$GITHUB_STEP_SUMMARY`, więc strona podsumowania przebiegu mówi,
w jakim był stanie, bez otwierania loga przez kogokolwiek.

Wywołany wprost, `scripts/audit_dependencies.py` ten kod przenosi: `0` dla
`CLEAN`, `1` dla `VULNERABLE`, `75` (`EX_TEMPFAIL`) tak samo dla `NETWORK`, jak
i dla `FAILED` — audyt, który się nie odbył, nigdy nie jest raportowany na
zielono, bo niezaudytowany zestaw zależności nazwany czystym to ta sama wada
odwrócona drugą stroną.

**Każdy niepełny przebieg jest ponawiany, cokolwiek powiedział.**

`AUDIT_ATTEMPTS` (domyślnie 3) z odczekaniem 5 s/10 s oraz `AUDIT_TIMEOUT`
(domyślnie 30 s) jako limit czasu gniazda na żądanie, podniesiony z własnych 15
pip-audit.

Dopasowanie frazy w wyjściu decyduje tylko o tym, czy werdykt brzmi `NETWORK`, czy
`FAILED` — nigdy o tym, czy próbować ponownie. Te dwa błędy nie są symetryczne:
ponowienie deterministycznej porażki kosztuje sekundy i tę samą odpowiedź,
podczas gdy *nieponowienie* przejściowej to fałszywa czerwień na wymaganym
sprawdzeniu, której to rozwiązanie ma zapobiegać.

Porażka sformułowana słowami, których lista nie zawiera, i tak dostaje więc swoje
ponowienia. Dostaje tylko mniej precyzyjną nazwę.

Na tej liście są dwa słowniki, bo po sieć sięgają dwa programy: `uv`, pobierając
samo `pip-audit` przy zimnym cache narzędzi, a potem `pip-audit`, pobierając
zgłoszenia.

### Baza danych { #database }

| Polecenie | Opis |
|---------|-------------|
| `make db-init` | Uruchamia PostgreSQL + tworzy początkową migrację + stosuje ją |
| `make db-migrate` | Tworzy nową migrację (pyta o wiadomość) |
| `make db-upgrade` | Stosuje oczekujące migracje |
| `make db-check` | `alembic check` — zawodzi, jeśli zmiana modelu nie ma migracji. Nieniszczące (nigdy nie cofa), więc w odróżnieniu od `test-migrations` działa wewnątrz `make check`; wymaga bazy danych na head i pomija się, zamiast zawodzić, gdy nic nie odpowiada na 5432. Tabele `rag_<collection>` magazynu wektorów, po jednej na kolekcję, są wyłączone z porównania, skoro nic ich nie modeluje ani nie migruje — `rag_documents`, która jest tabelą modelu, nie jest |
| `make db-downgrade` | Wycofuje ostatnią migrację |
| `make db-current` | Pokazuje bieżącą rewizję migracji |
| `make db-history` | Pokazuje pełną historię migracji |

### Użytkownicy { #users }

| Polecenie | Opis |
|---------|-------------|
| `make create-admin` | Tworzy użytkownika admina (interaktywnie) |
| `make user-create` | Tworzy nowego użytkownika (interaktywnie) |
| `make user-list` | Wypisuje wszystkich użytkowników |

### Prefect { #prefect }

Prefect działa w stosie deweloperskim jako dwa kontenery — startują automatycznie razem z `make dev`:

- **`prefect-server`** — API orkiestracji + UI webowe pod <http://localhost:4200>
- **`prefect-runner`** — rejestruje zaplanowane deploymenty i odpytuje o pracę

Runnerem jest `python -m app.worker.prefect_app`; flow żyją w `app/worker/tasks/`.
Otwórz UI, żeby oglądać przebiegi flow, przeglądać logi i ręcznie wyzwalać
deploymenty.
Domyślnie self-hosted — ustaw `PREFECT_API_KEY` (oraz chmurowy `PREFECT_API_URL`), żeby korzystać z Prefect Cloud.

### Docker (rozwój) { #docker-development }

| Polecenie | Opis |
|---------|-------------|
| `make docker-up` | Uruchamia wszystkie usługi backendu |
| `make docker-down` | Zatrzymuje wszystkie usługi |
| `make docker-logs` | Śledzi logi backendu |
| `make docker-build` | Buduje obrazy backendu |
| `make docker-shell` | Otwiera powłokę w kontenerze aplikacji |
| `make docker-frontend` | Uruchamia konsolę (w klonie za profilem `console`) |
| `make docker-frontend-down` | Zatrzymuje frontend |
| `make docker-frontend-logs` | Śledzi logi frontendu |
| `make docker-frontend-build` | Buduje obraz frontendu |
| `make docker-db` | Uruchamia tylko PostgreSQL |
| `make docker-db-stop` | Zatrzymuje PostgreSQL |
| `make docker-redis` | Uruchamia tylko Redisa |
| `make docker-redis-stop` | Zatrzymuje Redisa |

### Docker (produkcja z Traefikiem) { #docker-production-with-traefik }

| Polecenie | Opis |
|---------|-------------|
| `make docker-prod` | Uruchamia stos produkcyjny |
| `make docker-prod-down` | Zatrzymuje stos produkcyjny |
| `make docker-prod-logs` | Śledzi logi produkcyjne |

### Vercel (wdrożenie frontendu) { #vercel-frontend-deployment }

| Polecenie | Opis |
|---------|-------------|
| `make vercel-deploy` | Wdraża frontend na Vercel |

---

## CLI projektu { #project-cli }

Wszystkie polecenia CLI projektu wywołuje się przez:

```bash
cd backend
uv run agenticos <group> <command> [options]
```

### Polecenia serwera { #server-commands }

```bash
uv run agenticos server run              # Start dev server
uv run agenticos server run --reload     # With hot reload
uv run agenticos server run --port 9000  # Custom port
uv run agenticos server routes           # Show all registered routes
```

`--reload` uruchamia reloader uvicorna pod naszym własnym nadzorcą
(`backend/cli/reload_supervisor.py`), ponieważ reloader uvicorna jest obserwatorem
plików i niczym więcej: kiedy jądro zabija workera — realistycznie przez zabicie
z braku pamięci — ani go nie sprząta, ani nie zastępuje, więc reloader dalej
obserwuje, podczas gdy żaden port nie nasłuchuje. Pod nadzorcą worker zabity
sygnałem jest zastępowany w około pięć sekund, a ten, który zakończył się sam,
nadal czeka na edycję, która go naprawi — i po to właśnie jest `--reload`.

Zastępuje też workera, który jest **zaklinowany** — żywego, ale z pętlą zdarzeń,
która przestała się kręcić, co nie ma kodu wyjścia i dlatego wygląda zdrowo dla
każdej innej ścieżki odzyskiwania.

Worker raportuje swoją pętlę przez hook `callback_notify` uvicorna raz na sekundę,
a worker milczący przez piętnaście sekund w dwóch kolejnych odpytaniach zostaje
zabity i zastąpiony. Około dwudziestu pięciu sekund od zakleszczenia do ponownego
odpowiadania.

Dwa odpytania, a nie jedno, bo `docker pause` i budzenie laptopa ze snu
zatrzymują nadzorcę tak samo jak workera, a pierwsze odpytanie po tym odczytuje
nieaktualne uderzenie, które nic nie mówi.

To jest **liveness, a nie readiness**, i to celowo: uderzenie jest wywołaniem
z zegara, a nie żądaniem, więc wolna baza danych nie sprawi, że zdrowy serwer
będzie wyglądał na zaklinowany.

| | |
|---|---|
| `EVENT_LOOP_WEDGED_AFTER` | Sekundy ciszy, po których worker zostaje zastąpiony. Domyślnie `15`; `0` lub mniej wyłącza to sprawdzenie |

Wyłącz je na czas debugowania. Breakpoint blokuje pętlę zdarzeń i żadna sonda nie
odróżni tego od zakleszczenia, więc worker stojący na breakpoincie zostanie ci
podmieniony.

Tę samą zmienną czyta sam worker, który obserwuje własną pętlę zdarzeń i zabija
własny proces — i to właśnie pokrywa stos deweloperski i produkcyjny, gdzie nie ma
nadzorcy czytającego uderzenia z zewnątrz. Jedna liczba, więc wyłączenie
sprawdzenia na czas breakpointa wyłącza obu sędziów.
[Konfiguracja](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
ma cały obraz.

`server run` wybiera też implementację `websockets-sansio` w obu trybach. `auto`
uvicorna wybiera tę starą, która przy websockets >=14 zawala handshake błędem HTTP
500 — a czat w dashboardzie jest WebSocketem.


### Polecenia bazy danych { #database-commands }

```bash
uv run agenticos db init                  # Run all migrations
uv run agenticos db migrate -m "message"  # Create new migration
uv run agenticos db upgrade               # Apply pending migrations
uv run agenticos db upgrade --revision e3f  # Upgrade to specific revision
uv run agenticos db downgrade             # Rollback last migration
uv run agenticos db downgrade --revision base  # Rollback to start
uv run agenticos db current               # Show current revision
uv run agenticos db history               # Show migration history
```

### Polecenia użytkowników { #user-commands }

```bash
# Create user (interactive prompts for email/password)
uv run agenticos user create

# Create user non-interactively
uv run agenticos user create --email user@example.com --password secret

# Also grant app-admin, which administers the whole deployment
uv run agenticos user create --email admin@example.com --password secret --superuser

# The same thing, as a shortcut
uv run agenticos user create-admin --email admin@example.com --password secret

# List all users
uv run agenticos user list
```

**Nie ma `--role` ani `set-role`.** Władza użytkownika wewnątrz organizacji to
wiersz członkostwa plus [katalog uprawnień](reference/permissions.md), przyznawany
z Users & Roles w UI — kolumnę `users.role` usunięto, zanim łańcuch migracji
został spłaszczony. Jedyny przywilej, jaki ta grupa może rozdać, to ten globalny,
i `--superuser` nim jest. Żeby przyznać go lub odebrać później:

```bash
uv run agenticos cmd create-app-admin user@example.com
uv run agenticos cmd create-app-admin user@example.com --revoke
```

### Polecenia własne { #custom-commands }

Polecenia własne są odkrywane automatycznie w `app/commands/`. Uruchamiaj je przez:

```bash
uv run agenticos cmd <command-name> [options]
```

`uv run agenticos cmd --help` wypisuje wszystko, co ma działające wdrożenie.

### Konfiguracja i diagnostyka { #setup-and-diagnostics }

```bash
# An organization, an owner, a model profile and a published agent. Idempotent.
uv run agenticos cmd bootstrap \
    --email owner@example.com --password secret \
    --org "Acme" --provider anthropic --api-key sk-ant-...

# Without a key the agent is created but cannot run
uv run agenticos cmd bootstrap --org "Acme"

# Can this deployment actually run an agent? Database, vault, a usable model,
# and every registered sandbox connection - probed one by one, credential
# included, because `/healthz` is unauthenticated and answers for a service
# holding the wrong token.
uv run agenticos cmd doctor

# Find published agents that lend a skill their publisher could not reach. The
# publish-time check on skill_ids only guards new publishes; this is the offline
# half, naming versions frozen before it that still hand a private skill to a run.
# It sweeps every version a run can load, not only the current one: each named
# environment's pinned version, each version a non-terminal run (running, or parked
# awaiting approval) still reloads, and each delegate a spec pins - the last only as
# deep as max_depth lets a run reach, so a grandchild past the ceiling is not flagged.
# Report-only - a spec is exported into a client's own git, so unbinding is a person's
# call. Exits non-zero when it finds one, so a cron can gate on it.
uv run agenticos cmd audit-skill-bindings

# Re-wrap every stored secret under the current master key - the staged rotation
# docs/secrets.md describes. Configure the old and new key side by side in
# VAULT_MASTER_KEYS first; --dry-run fully unseals every stored envelope without
# writing, so failures surface before anything moves. Exits non-zero when any row
# could not move, so a script cannot drop the old key on a partial rotation.
uv run agenticos cmd vault-rotate --dry-run
uv run agenticos cmd vault-rotate

# Install the bundled skills (refund-policy, code-review, incident-report)
uv run agenticos cmd seed-skills
uv run agenticos cmd seed-skills --org <org-id> --dry-run

# Sample data for development
uv run agenticos cmd seed --count 10 --clear
```

### Zapraszanie zespołu i wydobywanie linków { #inviting-a-team-and-getting-the-links-out }

```bash
# Invitations for several addresses at once, printed as `address  link`.
uv run agenticos cmd invite-members <org-id> ada@example.com grace@example.com

# One role for the batch; `member` unless you say otherwise.
uv run agenticos cmd invite-members <org-id> ada@example.com --role admin

# Whose authority they are created under. Defaults to the organization's first
# owner, and a role gate needs a role to weigh the offered one against.
uv run agenticos cmd invite-members <org-id> ada@example.com --as owner@example.com
```

Istnieje to z powodu dwóch połówek zaproszenia. **Na wdrożeniu bez `SMTP_*` nic
nie idzie mailem**, a token przyjęcia jest zwracany raz i nie jest przechowywany
nigdzie, dokąd sięgnąłby drugi odczyt — więc link trzeba wypisać, żeby w ogóle
dało się go przekazać. Polecenie mówi, która z tych dwóch rzeczy się wydarzyła,
a jeden odrzucony adres (już członek, już zaproszony) jest raportowany i pomijany,
zamiast kosztować całą resztę.

Idzie to przez ten sam serwis co UI, więc pułap roli, limit miejsc i sprawdzenia
duplikatów obowiązują dokładnie tak samo jak przy kimś klikającym przycisk —
łącznie z tym, że nikt nie rozdaje roli, której jego własna nie przewyższa
ściśle.

`make platform-bootstrap BOOTSTRAP_API_KEY=sk-...` opakowuje `bootstrap`
migracjami, których ono potrzebuje. Uruchom najpierw `doctor`, kiedy coś działa
lokalnie, a nie działa na świeżym środowisku — to szybsze niż czytanie logów.

### Uruchomienie wdrożenia { #getting-a-deployment-up }

```bash
# Docker, one downloaded compose file, four questions, and a running agent.
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
# Only report what this machine is missing.
./scripts/quickstart.sh --check
# Print every command it would run, run none of them.
./scripts/quickstart.sh --dry-run
# Unattended.
./scripts/quickstart.sh --yes --provider anthropic --api-key sk-ant-... --org Acme
```

To nakładka na `docker compose up` na opublikowanych obrazach (`make dev`
w klonie), `agenticos cmd bootstrap` i `agenticos cmd mcp-registry-sync` — nic
z tego, co robi, nie jest niedostępne ręcznie, a Docker jest jedyną rzeczą, jakiej
potrzebuje.

### Lustro rejestru MCP { #the-mcp-registry-mirror }

```bash
# Fill or refresh `mcp_registry_servers` from the bundled snapshot.
uv run agenticos cmd mcp-registry-sync

# Or from the live registry, which is how the mirror moves between deploys.
uv run agenticos cmd mcp-registry-sync --fetch

# Keep rows the registry no longer lists, rather than pruning them.
uv run agenticos cmd mcp-registry-sync --no-prune
```

**`make platform-bootstrap` już to ładuje**, z dołączonego snapshotu, więc
pierwsza konfiguracja niczego z tego nie potrzebuje. Jest to pomijane, gdy tabela
zawiera już wiersze: ponowne uruchomienie bootstrapu nie może wydawać sekund na
przepisywanie pięciu tysięcy niezmienionych wierszy, a odświeżanie lustra jest
zadaniem tego polecenia, a nie bootstrapu.

Uruchom je ręcznie na wdrożeniu starszym niż ta tabela albo po to, żeby pobrać
nowszy snapshot. Synchronizacja jest idempotentna: drugi przebieg stempluje
`synced_at` i nie zmienia niczego więcej, chyba że zmienił się rejestr.

Przycinanie jest tym, co usuwa serwer wycofany z rejestru. Bez niego lustro tylko
rośnie, a martwy endpoint na zawsze zostaje do zaoferowania, więc jest domyślnie
włączone i kluczowane po `synced_at`, a nie po różnicy pięciu tysięcy id.

### Boty kanałów { #channel-bots }

Zobacz [Kanały](channels.md), żeby sprawdzić, co wspiera każda platforma.

Każde polecenie tutaj działa dla **jednej organizacji**, bo bot kanału należy do
jednej. `--org <id>` ją wskazuje, a wdrożenie z dokładnie jedną organizacją nie
potrzebuje żadnej flagi. Wdrożenie z kilkoma odrzuca, zamiast wybierać, i wypisuje
je wraz z ich id — zgadywanie działałoby na cudzych botach.

```bash
# Register a bot
uv run agenticos cmd channel-add-bot \
    --platform telegram --name "Support" --token <token> --mode jwt_linked

# Mattermost is self-hosted, so its bot carries its own server's address.
# --webhook-secret is the token Mattermost shows when the outgoing webhook is
# created; omit it to use the event stream and expose nothing.
uv run agenticos cmd channel-add-bot \
    --platform mattermost --name "Support" --token <token> \
    --api-base-url https://mattermost.acme.internal \
    --webhook-secret <token-from-mattermost>

uv run agenticos cmd channel-list-bots
uv run agenticos cmd channel-list-bots --platform telegram

# Send a test message through it - the cheapest proof the token and the
# address are right. --chat-id is a Telegram chat id or a Mattermost channel id.
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text "ping"

# Webhook delivery, or delete the webhook to fall back to polling. Telegram is
# the only platform with an API for this; for Slack and Mattermost the command
# prints the URL to paste into their own settings.
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>
```

Rejestracja bota z CLI to jedyna droga na wdrożeniu, na które nie jest skierowana
żadna przeglądarka, a tym zwykle jest serwer Mattermosta za VPN-em.

Tryby dostępu to `open`, `whitelist`, `jwt_linked` i `group_only`; `jwt_linked`
odpowiada wyłącznie kontom czatowym powiązanym z członkiem, na kanale tak samo jak
w wiadomości bezpośredniej. Wzmianka działa jako *nadawca*, nigdy jako bot,
a niepowiązana tożsamość zostaje odrzucona, zamiast działać bez roli — zobacz
[Kanały](channels.md#what-every-channel-shares).

### Polecenia RAG { #rag-commands }

Wszystkie polecenia RAG są poleceniami własnymi, wywoływanymi przez `cmd`:

#### Ingestia dokumentów { #document-ingestion }

Domyślną kolekcją jest `default`. Nazwa, której tabelę wektorów modele już
deklarują — `documents`, która z prefiksem jest tabelą śledzenia ingestii —
zostaje odrzucona z kodem 400, zamiast być na nią aliasowana; zobacz
[Przetwarzanie plików](file-processing.md#vector-storage).

```bash
# Ingest a single file into the default collection
uv run agenticos cmd rag-ingest ./docs/guide.pdf

# Ingest a directory
uv run agenticos cmd rag-ingest ./docs/

# Ingest recursively into a specific collection
uv run agenticos cmd rag-ingest ./docs/ --collection knowledge --recursive

# Ingest with sync mode
uv run agenticos cmd rag-ingest ./docs/ --sync-mode new_only
uv run agenticos cmd rag-ingest ./docs/ --sync-mode update_only

# Skip replacing existing documents
uv run agenticos cmd rag-ingest ./docs/ --no-replace
```

#### Wyszukiwanie { #search }

```bash
# Search the default collection
uv run agenticos cmd rag-search "what is fastapi"

# Search a specific collection
uv run agenticos cmd rag-search "deployment guide" --collection docs

# Get more results
uv run agenticos cmd rag-search "deployment" --top-k 10
```

#### Zarządzanie kolekcjami { #collection-management }

```bash
# List all collections with stats
uv run agenticos cmd rag-collections

# Show overall RAG system statistics
uv run agenticos cmd rag-stats

# Drop a collection (with confirmation)
uv run agenticos cmd rag-drop my_collection

# Drop without confirmation
uv run agenticos cmd rag-drop my_collection --yes
```

#### Synchronizacja z Google Drive { #google-drive-sync }

```bash
# Sync from Google Drive root
uv run agenticos cmd rag-sync-gdrive --collection docs

# Sync from a specific folder
uv run agenticos cmd rag-sync-gdrive --collection docs --folder-id abc123
```

#### Synchronizacja z S3/MinIO { #s3minio-sync }

```bash
# Sync from S3 bucket root
uv run agenticos cmd rag-sync-s3 --collection docs

# Sync from a specific prefix (folder)
uv run agenticos cmd rag-sync-s3 --collection docs --prefix documents/

# Sync from a specific bucket
uv run agenticos cmd rag-sync-s3 --collection docs --bucket my-bucket
```


#### Zarządzanie źródłami synchronizacji { #sync-source-management }

```bash
# List configured sync sources
uv run agenticos cmd rag-sources

# Add a new sync source. `--org` is required and the collection has to be one
# that organization already holds: a sync *writes into* the collection it names,
# so a source pointing at a name nobody owns fails later in a worker, and one
# pointing at another tenant's is an injection rather than a read.
uv run agenticos cmd rag-source-add \
    --name "My Drive" \
    --type gdrive \
    --org 0c8f2b1e-... \
    --collection docs \
    --config '{"folder_id": "abc123"}' \
    --sync-mode new_only \
    --schedule 60

# Remove a sync source
uv run agenticos cmd rag-source-remove <source-id>
uv run agenticos cmd rag-source-remove <source-id> --yes  # Skip confirmation

# Trigger sync for a specific source
uv run agenticos cmd rag-source-sync <source-id>

# Trigger sync for all active sources
uv run agenticos cmd rag-source-sync --all
```

`rag-source-sync` **czeka na synchronizacje, które uruchomił**, do godziny,
i mówi o tym w trakcie. Sama synchronizacja działa w zadaniu w tle, a proces
polecenia kończy się, gdy wraca jego korutyna — więc polecenie, które tylko
wyzwoliło je i wyszło, anulowało pracę, o której właśnie zaraportowało, że
wystartowała. Przez API to zadanie należy do długo żyjącego workera i nic nie musi
na nie czekać.

## Dodawanie własnych poleceń { #adding-custom-commands }

Polecenia są odkrywane automatycznie w `app/commands/`. Utwórz nowy plik:

```python
# app/commands/my_command.py
import click
from app.commands import command, success, error

@command("my-command", help="Description of what this does")
@click.option("--name", "-n", required=True, help="Name parameter")
def my_command(name: str):
    """Your command logic here."""
    success(f"Done: {name}")
```

Uruchom je:

```bash
uv run agenticos cmd my-command --name test
```

Więcej szczegółów znajdziesz w `docs/adding_features.md`.
