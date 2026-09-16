---
source_sha: "863643d3d515"
---

# Bezpieczeństwo { #security }

Ta strona jest tym, co przegląd bezpieczeństwa w kształcie HIPAA albo SOC 2
dostaje do ręki: granice zaufania, jakie dane opuszczają wdrożenie i do kogo, co
jest gdzie szyfrowane, oraz macierz kontroli, która dla każdej kontroli nazywa
mechanizm w tym kodzie, który ją realizuje, i test, który trzyma ją w mocy.

Opisuje to, co **jest**, a nie to, co byłoby miłe. Wiersz bez mechanizmu mówi to
wprost i linkuje issue, które by go zbudowało. Jak zgłosić podatność i jaka jest
produkcyjna lista kontrolna hardeningu — zobacz [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md)
w korzeniu repozytorium; ta strona to cała reszta, w jednej kopii.

Dwie sąsiednie strony odpowiadają na pytania, które przegląd zadaje zaraz potem,
i nie są tu powtarzane: [Ochrona danych](data-protection.md) — gdzie leżą dane
osobowe, co faktycznie obejmuje usunięcie i które luki są wciąż otwarte, oraz
[Licencje](licenses.md) — każdy komponent trzeciej strony, który wiozą obrazy.

## Model zagrożeń { #threat-model }

Platforma jest self-hostowana i wielotenantowa. Założeniem projektowym jest, że
infrastruktura operatora jest zaufana, a każde żądanie do niej nie jest — więc
granicami, które mają znaczenie, są te, które żądanie przekracza w drodze do
danych.

| Granica | Co ją przekracza | Zaufana po drugiej stronie? |
|---|---|---|
| Przeglądarka → BFF (route handlery Next.js) | Ciasteczko sesji, nagłówek organizacji, dane z formularza | Nie — ale BFF nie weryfikuje ciasteczka: czyta `httpOnly` `access_token` i przekazuje go jako nagłówek bearer (`frontend/src/lib/platform-proxy.ts`). To granica przekazywania poświadczenia; weryfikacja jest zadaniem API |
| BFF → API (FastAPI) | JWT związany z sesją w bazie, nagłówek `X-Organization-Id` | Nie — token jest weryfikowany przy każdym żądaniu, sesja sprawdzana pod kątem unieważnienia, a organizacja rozstrzygana z tokena |
| API → PostgreSQL / Redis | Zapytania i odczyty z cache, po TLS, gdy jest skonfigurowany | Tak — magazyn należy do operatora; co chroni w spoczynku, jest pod „Co jest gdzie szyfrowane” |
| API / worker → providerzy modeli, kanały, serwery MCP, dostawcy wyszukiwania, Logfire | Prompty, wywołania narzędzi, zapytania, odpowiedzi, trace'y | Nie — to strony trzecie; co do nich trafia, jest decyzją per agent, z wyjątkiem tracingu na poziomie całego wdrożenia (poniżej) |
| Worker → konektory (Google Drive, S3, …) | Poświadczenia odpieczętowane z vaultu, pobrane dokumenty | Nie — poświadczenie konektora to sekret w vault wskazywany po id |

Władza wewnątrz tenanta nigdy nie jest nazwą roli na route'cie: to wiersz
członkostwa plus katalog uprawnień (`app/core/permissions.py`), rozstrzygany per
zasób. Dwóch wywołujących z tą samą rolą może sięgnąć do różnych wierszy, bo
grant na jednym zasobie poszerza to, na co rola pozwala, nie awansując członka.

## Co opuszcza wdrożenie { #what-leaves-the-deployment }

Nic nie dzwoni do domu. Każde wywołanie na zewnątrz jest tym, które wdrożenie
skonfigurowało, i każde jest granicą, o którą przegląd u klienta zapyta.

| Do | Co | Kiedy |
|---|---|---|
| Skonfigurowany provider modelu | Prompt, wyjście modelu, argumenty i wyniki narzędzi | Każdy run — chyba że model działa na własnej infrastrukturze operatora, wtedy nic nie wychodzi |
| Skonfigurowany kanał (Slack, Telegram, Mattermost) | Wygenerowane odpowiedzi agenta — tekst, obrazy i załączniki | Zawsze, gdy agent jest wystawiony przez ten kanał; każde `send_message` publikuje u providera (`app/services/channels/`) |
| Logfire | Trace'y, które niosą prompty i wyjścia, chyba że agent mówi inaczej | Dwie niezależne ścieżki. Token observability per agent trace'uje tego agenta, a jego tryb `content` decyduje, ile niesie span - `none` sprowadza go do czasu, tokenów, kosztu i nazw narzędzi (#1413). `LOGFIRE_TOKEN` na poziomie wdrożenia instrumentuje **każdy** run, tak samo w API jak w workerze Prefect (`app/core/logfire_setup.py`), więc przy nim ustawionym wychodzi treść każdego agenta, który nie poprosił o `none`; agent, który poprosił, jest przypięty do instrumentacji bez treści również na tym tracerze (`suppress_content`), więc tryb trzyma na obu ścieżkach, a specjalista tego agenta go dziedziczy - napisany inline albo wymyślony w trakcie runu. Jedna luka, której nie obejmuje: nieudane podpięcie, które jest logowane i zostawione. Żadna ze ścieżek nie jest domyślnie włączona. Stanu pośredniego z filtrem świadomie nie ma - częściowo wyczyszczony eksport to gwarancja, której nikt nie zaudytuje ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)) |
| Serwery MCP | Wywołania narzędzi i ich argumenty | Tylko dla narzędzi, do których agent jest podpięty |
| Dostawca web search (Tavily, DuckDuckGo) | Zapytanie wyszukiwania | Tylko gdy przyznana jest capability wyszukiwania |
| Provider embeddingów | Tekst dokumentu, przy ingest | Tylko dla bazy wiedzy, której provider jest zdalny |

## Co jest gdzie szyfrowane { #what-is-encrypted-where }

Jest jeden mechanizm szyfrowania na poziomie aplikacji i celowo jest jedyny:
vault (`app/core/vault.py`). Każde **poświadczenie konektora i API** w spoczynku
jest zapieczętowane w kopercie per właściciel, której klucz opakowujący jest
wyprowadzany przez HKDF z organizacji (albo użytkownika), do której należy — więc
szyfrogram skopiowany do wiersza innej organizacji nie da się odpieczętować.
Klucz główny jest rotowalny bez ponownego szyfrowania ładunków.

Nie wszystko, co platforma przechowuje, jest poświadczeniem w vault, i mówimy to
wprost, bo przegląd i tak to znajdzie:

- **Krótkożyjące tokeny bearer** — zaproszenia do organizacji
  (`OrganizationInvitation.token`), żądania połączenia kanału
  (`ChannelLinkRequest.token`) i linki do udostępnionych konwersacji
  (`ConversationShare.share_token`) — to losowe kolumny `String(64)`
  wyszukiwane po równości, nie pieczętowane w vault. Kto ma wartość, ten może jej
  użyć, więc chroni je wygaśnięcie i jednorazowość, a nie szyfrowanie. Wyjątkiem
  są refresh tokeny sesji, haszowane w spoczynku (`sessions.refresh_token_hash`).
- **Wgrane pliki i pliki z czatu** leżą na systemie plików kontenera API otwartym
  tekstem (`app/services/file_storage.py`) — chroni je wyłącznie szyfrowanie
  wolumenu.
- **Treści wiadomości, `rag_documents` i ich wektory oraz workspace'y sandboksa**
  są przechowywane jako kolumny z tekstem jawnym, wiersze pgvector i pliki
  workspace'u. Vault pieczętuje poświadczenia, nie treść; ochrona tych rzeczy w
  spoczynku jest na poziomie dysku.

Backend plików zgodny z S3, z szyfrowaniem po stronie serwera, jest odpowiedzią
na poziomie aplikacji dla object storage i jest śledzony w
[#1423](https://github.com/vstorm-co/agenticos/issues/1423).

## Macierz kontroli { #controls-matrix }

Jeden wiersz na kontrolę, mechanizm, który ją realizuje, i test, który trzyma ją
w mocy. Ujęte względem zabezpieczeń technicznych HIPAA §164.312 i SOC 2 CC6–CC8.

### Kontrola dostępu · HIPAA §164.312(a) · SOC 2 CC6 { #access-control-hipaa-164312a-soc-2-cc6 }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| Izolacja tenantów, nawet gdy wywołujący jest właścicielem wiersza | `resolve_access` odmawia zasobowi, którego `organization_id` się różni, zanim sprawdzi własność (`app/services/access.py`) | `test_resource_access.py::TestTenantBoundary`, `test_conversation_tenant_isolation.py`, `test_platform_flows.py` |
| Uprawnienie na każdym route'cie kolekcji | Zależność route'u `require(*perms)` na listowaniu, tworzeniu i route'ach katalogu (`app/api/deps.py`), katalog w `app/core/permissions.py` | `test_platform_routes.py::TestEachRouteDemandsItsOwnPermission` |
| Route'y per zasób autoryzują w serwisie, nie na route'cie | Route działający na jednym agencie, skillu albo kolekcji nie niesie bramki `require()` — bramka roli odmówiłaby posiadaczowi grantu, zanim grant by zadziałał — i zamiast tego woła `resolve_access` (`app/services/access.py`) | `test_platform_routes.py::TestEveryPlatformRouteIsGuarded` (każdy route jest bramkowany albo rozstrzygany w serwisie) |
| Grant poszerza dostęp, nie awansując członka | `resolve_access` per zasób bierze `max(zakres roli, grant)` (`app/services/access.py`) | `test_resource_access.py::TestGrantsWidenAccess`, `::TestPermissionsGrantsCannotWiden` |
| Wzmianka w kanale uruchamia run jako nadawca, nie jako bot | Używany jest własny `AuthContext` powiązanego, aktywnego nadawcy (`app/services/channels/mentions.py`) | `test_channel_mentions.py::TestAnswer::test_the_run_carries_the_senders_own_role` |

### Uwierzytelnianie · HIPAA §164.312(d) · SOC 2 CC6 { #authentication-hipaa-164312d-soc-2-cc6 }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| JWT (HS256), hasła przez bcrypt | `app/core/security.py` — `verify_token`, `get_password_hash` | `test_security.py`, `test_auth.py` |
| Klucze API porównywane w stałym czasie | `secrets.compare_digest` (`app/api/deps.py`) | `test_auth.py`, sprawdzenia HMAC webhooków w adapterach kanałów |
| Sesje w bazie danych z unieważnianiem | Tabela `sessions` + `SessionService`; token związany z claimem `sid` (`app/services/session.py`, `app/api/routes/v1/sessions.py`) | `test_session_verify.py`, `test_session_revocation.py` |
| Logowanie jednokrotne przez własnego dostawcę tożsamości wdrożenia | Generyczne OIDC przez discovery — authorization code z PKCE, wymagane `email_verified`, konto kluczowane po `sub` (`app/core/oauth.py`, `app/api/routes/v1/oauth.py`). Entra ID, Okta, Keycloak; konfiguracja w [Logowaniu jednokrotnym](configuration.md#single-sign-on-generic-oidc) | `test_oidc_sign_in.py` |
| Polityka rejestracji bramkuje SSO tak samo jak formularz | `check_may_register` wewnątrz `get_or_create_oauth_user` — `invite_only` i lista dozwolonych domen odmawiają też logowaniu przez dostawcę (`app/services/user.py`) | `test_oidc_sign_in.py::TestTheRoundTrip`, `test_signup_policy.py` |
| Mapowanie grup na role, SAML, SCIM | **Jeszcze nie** — ludzie logują się przez dostawcę, a administrator ich umieszcza | — |

### Kontrole audytowe · HIPAA §164.312(b) · SOC 2 CC7 { #audit-controls-hipaa-164312b-soc-2-cc7 }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| Mutacje istotne dla governance zapisywane w transakcji żądania | `record_audit` (`app/core/audit.py`) w mutującym serwisie — rotacja sekretu, podpięcie skilla / synchronizacji / MCP, członkostwo, udostępnianie, zatwierdzenia, eksporty i więcej; zapisywane do `app_admin_audit_logs`. To nie jest pokrycie każdego zapisu (CRUD bazy wiedzy, choćby, nie jest audytowany) | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| Ślad jest czytelny dla audytora | `GET /audit`, bramkowane na `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Eksport śladu (CSV/JSONL) | `GET /audit/export` w oknie czasu, bramkowany na `audit:read`, zapisujący własny odczyt w śladzie; eksporty runów, zatwierdzeń i wydatków robią to samo (#1422) | `test_exporting.py` (eksport i jego własny wpis audytowy) |
| Okres audytu, który organizacja może wydłużyć i nigdy skrócić | Podłoga na poziomie wdrożenia (domyślnie sześć lat, HIPAA §164.316(b)(2)); krótszy okres jest odrzucany, a nie podnoszony. Sweep **nie** usuwa wpisów audytowych — łańcuch haszy i jego checkpoint stoją na tym, że wpisy zostają, więc weryfikowalne wycofanie to [#1622](https://github.com/vstorm-co/agenticos/issues/1622) (`app/core/retention.py`). Zobacz [Retencję](governance.md#retention) | `test_retention.py::TestWhichNumberWins`, `::test_audit_resolves_to_a_period_and_is_still_not_swept` |
| Dowód nienaruszalności (łańcuch haszy) | **Jeszcze nie** — [#1622](https://github.com/vstorm-co/agenticos/issues/1622) | — |

### Integralność · HIPAA §164.312(c) · SOC 2 CC8 (zarządzanie zmianą) { #integrity-hipaa-164312c-soc-2-cc8-change-management }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| Spec jest odrzucany przy publikacji, nigdy w czasie runu | `validate_spec` (`app/services/agent_registry.py`) — nieznana capability, nieprzyznany scope, `secret_id` złego rodzaju albo z innej organizacji, osobiste połączenie MCP | `test_agent_registry.py`, `test_capability_secrets.py::TestPublishValidation` |
| Budżet jest sprawdzany przed żądaniem do modelu, a koszt zapisywany nawet przy błędzie | `BudgetGuard.wrap_model_request` bramkuje przed wywołaniem (`app/agents/capabilities/budget/`); koszt runu jest zapisywany w terminalnym `finally` (`app/services/agent_runner.py`) | `test_spend.py::TestBudgetGuard`, `test_agent_runner.py::…::test_a_failed_run_still_records_its_cost` |
| Zatwierdzenie jest rozstrzygane dokładnie raz | `ApprovalService.decide` odmawia wierszowi innemu niż oczekujący, odczytanemu `for_update` (`app/services/approvals.py`) | `test_approvals_queue.py::TestDecidingTwiceIsRefused` |

### Poufność poświadczeń · HIPAA §164.312(a)(2)(iv) { #confidentiality-of-credentials-hipaa-164312a2iv }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| Żaden sekret otwartym tekstem w odpowiedzi API ani we wpisie audytowym | `SealedStr`/`CredentialStr` maskują każdy repr; podpowiedzi to wyłącznie ostatnie 4 znaki (`app/core/secret_kinds.py`, `app/core/vault.py`) | `test_no_secret_escapes.py` (przemiata całą powierzchnię OpenAPI), `test_capability_secrets.py::TestInjection` |
| Logi nie są częścią tej gwarancji | Zniekształcona odpowiedź tokena MCP OAuth trafia do logów przez `ValidationError` Pydantica, który powtarza swoje wejście — znana luka, [#1626](https://github.com/vstorm-co/agenticos/issues/1626) | `test_mcp_connections.py::test_an_unreadable_token_response_does_not_echo_its_input` (dokumentuje, że token ląduje w `caplog`) |
| Poświadczenie jest w spoczynku związane ze swoją organizacją | Koperta HKDF per właściciel (`app/core/vault.py`); zakres to poświadczenia konektorów i API — o tokenach bearer, których nie obejmuje, mówi „Co jest gdzie szyfrowane” | `test_secret_tenant_isolation.py`, `test_vault.py` |

### Bezpieczeństwo transmisji · HIPAA §164.312(e) · SOC 2 CC6 { #transmission-security-hipaa-164312e-soc-2-cc6 }

| Kontrola | Mechanizm | Trzymane przez |
|---|---|---|
| TLS do PostgreSQL i Redisa | `POSTGRES_SSLMODE`, `REDIS_SSL` (`app/core/config.py`); `doctor` raportuje żywy stan Postgresa z `pg_stat_ssl` | Postgres, na żywym połączeniu: `test_store_tls.py`; Redis, przy budowie URL-a i w `doctor`: `test_config.py`, `test_doctor_sandbox.py` |
| Nagłówki ramkowania i MIME na każdej odpowiedzi; CSP na wszystkich poza endpointami referencji API | `SecurityHeadersMiddleware` (`app/core/middleware.py`), którego `exclude_paths` zdejmują CSP — nie ramkowanie ani MIME — dla OpenAPI, Swaggera i ReDoc; plus CSP frontendu per wdrożenie (`frontend/src/middleware.ts`), którego `script-src` niesie nonce per żądanie i `'strict-dynamic'` zamiast `'unsafe-inline'` | `test_security_headers.py`, w tym `test_an_excluded_path_keeps_its_framing_but_drops_the_csp`; `csp.test.ts`, `middleware.test.ts` |
| HTTPS i HSTS | Terminowane na reverse proxy — dołączony `nginx/nginx.conf` ustawia HSTS; aplikacja z założenia nie | Sprawa wdrożenia; zobacz listę kontrolną hardeningu |
| Limity zapytań na publicznych powierzchniach | Limity oparte o Redis na API runów, widgecie embed i stronach hostowanych (`app/services/rate_limit.py`); limity per nadawca na botach kanałów (`app/services/channels/router.py`) | `test_rate_limited_surfaces.py`; limit bota kanału jest zaimplementowany, ale cienko przetestowany |

### Odmowy jako zbiór { #the-refusals-as-a-set }

Testy odmów powyżej niosą marker `security`. `make test-security` uruchamia cały
zbiór, a CI publikuje zebraną listę jako artefakt `security-tests.txt` przy każdym
przebiegu backendu (#1417) — więc odmowy da się policzyć i przeczytać, a nie tylko
przyjąć na wiarę. Test, którego nazwa albo moduł wspomina tenanta, uprawnienie,
budżet, zatwierdzenie, sekret albo tekst jawny, a nie ma markera, wywala
`tests/test_security_marker.py`, co trzyma listę kompletną w miarę rozrostu suite.

## Profil HIPAA i czego nie twierdzi { #the-hipaa-profile-and-what-it-does-not-claim }

Przegląd bezpieczeństwa nie pyta „czy to oprogramowanie jest zgodne”. HHS nie
certyfikuje żadnego oprogramowania, a OCR nie uznaje prywatnych certyfikacji.
Pyta **czy możemy to uruchomić wewnątrz naszego zgodnego środowiska i czy da się
to udowodnić** — a odpowiedzią jest konfiguracja dostarczona z produktem plus
komenda sprawdzająca działające wdrożenie względem niej (#1448).

```bash
uv run agenticos cmd doctor --profile hipaa
```

Jeden wiersz na kontrolę, każdy nazywający ustawienie, które ją spełnia, albo to,
które jej nie spełnia, i niezerowy exit przy jakiejkolwiek porażce, żeby dało się
to odpalić w CI klienta. Konfiguracja to `deploy/profiles/hipaa/`: overlay compose
odmawiający startu bez ustawień, których nie może domyślnie przyjąć, i opisany
plik env.

**Ten akapit czytaj jednym tchem z profilem.** Odpowiada on na **techniczne**
zabezpieczenia, §164.312, i tylko na nie. Zabezpieczenia administracyjne
(§164.308 — analiza ryzyka, szkolenia, polityka sankcji, plan ciągłości, umowy z
business associate) i fizyczne (§164.310) należą do operatora i zawsze będą.
Profil sugerujący inaczej byłby twierdzeniem, którego nikt nie obroni.

### Arkusz { #the-sheet }

| Kontrola | Zabezpieczenie | Spełnia ją |
|---|---|---|
| `postgres-tls` | §164.312(e)(1) | `POSTGRES_SSLMODE=verify-full`. `require` szyfruje i nie weryfikuje żadnego certyfikatu, więc profil go nie przyjmuje |
| `redis-tls` | §164.312(e)(1) | `REDIS_SSL=true`. Oba magazyny muszą być twoje: dołączone w repozytorium `db` i `redis` nie mają listenera TLS, więc overlay odmawia startu bez `POSTGRES_HOST` i `REDIS_HOST` |
| `browser-tls` | §164.312(e)(1) | `FRONTEND_URL` i `PUBLIC_BASE_URL` po https, z twoim reverse proxy je terminującym. Poświadczane, a adres http jest tu **odrzucany**: każda inna kontrola może przejść, podczas gdy logowanie przechodzi granicę klienta otwartym tekstem |
| `vault-key` | §164.312(a)(2)(iv) | Klucz główny vaulta o długości co najmniej 64 znaków. HKDF wyprowadza z czegokolwiek klucz opakowujący właściwej długości i nie doda entropii do zgadywalnego sekretu |
| `content-at-rest` | §164.312(a)(2)(iv) | **Operatora.** Dane Postgresa, wolumen mediów i katalog workspace'ów sandboxa szyfruje wolumen albo dysk, nie ta aplikacja |
| `local-model` | §164.312(e)(1) | Każdy profil modelu serwowany z twojej sieci. Parsowana jest **nazwa hosta** — adres prywatny, `localhost`, gołe `ollama`/`litellm`/`vllm` albo nazwa `.internal`/`.local`/`.svc` — więc `https://ollama.vendor.example` nie jest lokalny, a ten bez `base_url` to z definicji publiczne API dostawcy |
| `traces-local` | §164.312(e)(1) | Nieustawiony `LOGFIRE_TOKEN` **i** żaden opublikowany agent ani nazwane środowisko nie niesie własnego tokenu tracingu — każdy podpina własny eksporter, a `observability.content` domyślnie to `full` |
| `sso` | §164.312(d) | `OIDC_ISSUER`. **Jeszcze niedostępne** — generyczne logowanie OIDC to [#1419](https://github.com/vstorm-co/agenticos/issues/1419), więc ta kontrola jest dziś niespełniona na każdym wdrożeniu, co jest prawdą o takim, gdzie ludzie logują się hasłami. MFA należy do dostawcy tożsamości, i arkusz to mówi, zamiast tego twierdzić |
| `signup` | §164.312(a)(1) | `invite_only` albo `closed` |
| `audit-retention` | §164.312(b) | Podłoga audytu co najmniej 2190 dni — sześć lat z §164.316(b)(2) |
| `audit-chain` | §164.312(c)(1) | Łańcuch haszy i jego checkpoint. Wykrywanie, nie zapobieganie — zobacz [Kontrole audytu](#audit-controls-hipaa-164312b-soc-2-cc7) |

Trzy wyniki i to środkowy waży. `ok` i `!!` to odpowiedzi tego kodu. `--` to
kontrola, która naprawdę należy do operatora, **nazwana**, a nie po cichu
zaliczona — arkusz pomijający to, czego nie widzi, czytałby się jako kompletny i
nie byłby — i nie wywala komendy, bo kontrola, której stąd nikt nie udowodni, to
kontrola, której nikt nigdy by nie przeszedł.

### Kto jest business associate { #who-is-the-business-associate }

Klient uruchamiający to na własnej infrastrukturze dostaje oprogramowanie. Nikt
tutaj nie dotyka jego PHI i żadna umowa nie jest potrzebna. Wdrożenie prowadzone
dla niego przez kogoś innego czyni tego kogoś business associate, a to umowa, nie
flaga w konfiguracji.

### Dlaczego profil domyślnie bierze model lokalny { #why-the-profile-defaults-to-a-local-model }

Hostowany model zabiera ze sobą treść każdego uruchomienia, więc jego użycie
oznacza umowę z tym dostawcą — a te umowy są węższe, niż ludzie zakładają.
Organizacja z włączonym HIPAA u dużego dostawcy zwykle wyklucza wykonywanie kodu
i pobieranie z sieci, czyli dokładnie kształt capability `sandbox`,
`code_execution` i `web_fetch`. Klient, który taką umowę podpisze, a potem
zbuduje agenta na tych capability, dowiaduje się o tym w trakcie incydentu.

Lokalna inferencja usuwa to pytanie i dlatego jest domyślną wartością profilu, a
nie sugestią.

## Podsumowanie { #recap }

- Ufaj infrastrukturze operatora; nie ufaj żadnemu żądaniu do niej. Granicami,
  które mają znaczenie, są przeglądarka → BFF → API → magazyn oraz API/worker →
  strony trzecie. BFF przekazuje ciasteczko sesji; API jest tym miejscem, gdzie
  żądanie jest weryfikowane.
- Jedyne dane, które wychodzą, to te, o których wyjściu zdecydowało wdrożenie —
  providerzy modeli, kanały, serwery MCP, dostawcy wyszukiwania i embeddingów
  oraz Logfire — który jest opcjonalny, a gdy token na poziomie wdrożenia jest
  ustawiony, trace'uje każdy run obsłużony przez proces API, z treścią każdego
  agenta, który nie poprosił o `none`.
- Poświadczenia konektorów i API są zapieczętowane per organizacja w jednym
  vaulcie; krótkożyjące tokeny bearer i treść w spoczynku (pliki, wiadomości,
  RAG, sandboksy) nie są, a [#1423](https://github.com/vstorm-co/agenticos/issues/1423)
  jest odpowiedzią na poziomie aplikacji dla object storage.
- Każda kontrola w macierzy nazywa mechanizm i test, i tym samym tchem nazywa
  swoje luki — dowód nienaruszalności i szyfrowanie plików na poziomie aplikacji
  linkują issue, które by je zbudowały.
- Podatności zgłaszaj i listę kontrolną hardeningu uruchamiaj z
  [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md);
  obok tej strony czytaj [Ochronę danych](data-protection.md) i
  [Licencje](licenses.md).
