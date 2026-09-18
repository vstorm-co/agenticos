---
source_sha: "6794d026b64e"
---

# Ochrona danych { #data-protection }

Gdzie we wdrożeniu mieszkają dane osobowe, co je opuszcza i przy jakiej
konfiguracji, które kontrole istnieją w kodzie i mają za sobą test, a które są
wciąż otwartymi zgłoszeniami. Napisane dla osoby, która odpowiada na przegląd
ochrony danych jednego wdrożenia — inspektora ochrony danych, oficera
bezpieczeństwa, operatora — i uczciwe co do różnicy między tym, co
oprogramowanie potrafi, a tym, co wdrożenie faktycznie postanowiło.

!!! warning "Strona to nie zgodność"

    Nic tutaj nie jest dowodem, że wdrożenie jest zgodne z RODO. Kod da się
    wdrożyć wewnątrz zgodnego środowiska; czy dane wdrożenie *jest* zgodne,
    zależy od skonfigurowanych providerów, ustalonej retencji, podpisanych umów
    i operatora, który je prowadzi. Każdy taki warunek jest poniżej nazwany jako
    coś do zdobycia i zweryfikowania, nigdy jako coś założonego.

## Domyślnie nic nie wychodzi { #nothing-leaves-by-default }

Świeże wdrożenie trzyma wszystko we własnym PostgreSQL-u i na własnym dysku,
i nigdzie nic nie wysyła. Każdy skok na zewnątrz to wiersz albo ustawienie,
które ktoś dodał później: profil modelu wskazujący providera, kolekcja
wybierająca parser, metoda wyszukiwania w specu, token Logfire, host mem0,
serwer MCP, bot kanału. Usuń wiersz i skok znika.

Wdrożenie, które nie chce **żadnej trzeciej strony w łańcuchu**, konfiguruje się
tak i oprogramowanie współpracuje:

| Zagadnienie | Lokalna odpowiedź |
|---|---|
| Model czatowy | Profil `ollama` albo `litellm` — bezkluczowy, wskazujący endpoint, który hostujesz. Każdy z 27 providerów z `base_url` przyjmie też Twój gateway |
| Parsowanie dokumentów | `pymupdf`, wartość domyślna, działa w workerze. OCR LiteParse też działa w workerze albo na serwerze OCR zarejestrowanym jako usługa lokalna. LlamaParse to wybór per kolekcja, wymagający klucza w vault; bez niego nic nie jest parsowane poza wdrożeniem |
| Embeddingi | Ollama, którą hostujesz, zarejestrowana jako usługa lokalna w Knowledge → Integrations i wybrana per kolekcja jako provider `ollama`. Bezkluczowa i jedyny provider, którego może użyć kolekcja app-scoped |
| Trace'y | Zostaw `LOGFIRE_TOKEN` nieustawiony i nie wiąż żadnego tokenu `observability` ze specem ani ze środowiskiem. Runy dalej zapisują id trace'u lokalnie |
| Wyszukiwanie, przeglądanie, pamięć, narzędzia | Nie wiąż sekretu `search`, żadnej capability `web_fetch`, `browser_use` ani `memory_mem0`, żadnego połączenia MCP |
| Poczta | Twój własny relay SMTP |
| Mowa i obrazy | Profile u providera, którego hostujesz, albo brak takich profili |

Embeddingi w to wliczone: katalog wymienia OpenRouter i OpenAI, do których
kolekcja sięga kluczem z vaultu, oraz `ollama`, do której kolekcja sięga przez
usługę lokalną — wiersz wskazujący serwer prowadzony przez organizację albo
wdrożenie. Kolekcja na `ollama` wysyła swoje chunki i zapytania wyłącznie na ten
host i nikomu nie płaci. Wdrożenie, które musi trzymać dokumenty na własnym
sprzęcie, tam tworzy każdą kolekcję.

## Kto za co odpowiada { #who-is-responsible-for-what }

| Strona | Rola | Co to tutaj znaczy |
|---|---|---|
| Organizacja, która to wdraża (miasto, firma) | **Administrator danych** | Decyduje o celach, retencji, o tym, do których providerów agent może sięgać, i podpisuje z nimi umowy |
| Vstorm jako autor oprogramowania | **Żadna z tych ról**, dla wdrożenia self-hosted | Kod działa na Twojej infrastrukturze i nic nie dzwoni do domu. Vstorm nigdy nie widzi Twoich danych |
| Vstorm, jeśli prowadzi wdrożenie za Ciebie | **Podmiot przetwarzający** | Umowa powierzenia przetwarzania to kontrakt między nami, a nie ustawienie. Musi istnieć przed opublikowaniem pierwszego agenta |
| Provider modelu, embeddingów, parsowania, wyszukiwania albo obserwowalności | **Podprzetwarzający**, wybrany konfiguracją | Platforma zapisuje, *którego* providera i *który* endpoint używa każdy agent. Ich lokalizacja, retencja i warunki treningu są ich, i weryfikuje się je per wdrożenie |

Platforma niczego nie trenuje ani nie dostraja. Wysyła prompty, dokumenty
i wyniki narzędzi do providerów, których wdrożenie skonfigurowało, i zapisuje
to, co wraca. To, czy provider używa ruchu API do treningu, jest własnością
konta i warunków providera, a lista kontrolna na końcu prosi o oświadczenie,
zamiast je zakładać.

## Gdzie mieszkają dane osobowe { #where-personal-data-lives }

Wszystko poniżej jest we własnym PostgreSQL-u wdrożenia, na jego własnym dysku
albo w usłudze, którą wdrożenie wybrało. Każda tabela należąca do organizacji
niesie `organization_id`; wiersz podrzędny — wiadomość, załącznik, ocena — jest
ograniczany przez konwersację albo użytkownika, przy którym wisi, a odczyt idzie
przez sprawdzenie rodzica.

### Baza danych { #the-database }

| Magazyn | Trzyma | Dane osobowe w nim | Cel |
|---|---|---|---|
| `users`, `sessions`, `organization_members` | Konta i logowania | E-mail, imię, awatar, zahaszowane hasło albo id konta Google, hash refresh tokenu, adres IP i user agent na sesję | Uwierzytelnianie i autoryzacja |
| `conversations`, `messages`, `tool_calls` | Każdy czat na każdej powierzchni | Tekst, który ludzie napisali, odpowiedzi i rozumowanie modelu, argumenty i wyniki narzędzi, kroczące podsumowanie długich wątków | Podstawowa funkcja produktu; historia, do której człowiek wraca |
| `chat_files` | Załączniki do wiadomości | Nazwa pliku, typ, rozmiar, wyciągnięty tekst (`parsed_content`) i ścieżka bajtów na dysku | Odpowiadanie o pliku |
| `context_files` | Stała wiedza, którą builder napisał dla agentów | Cokolwiek autor tam umieścił — i trafia to do promptu dosłownie. Zobacz [Pliki kontekstu](context.md) | Instrukcje i fakty, które agent zawsze ma znać |
| `agent_memory_files` | Notatki, które agent napisał o osobie albo o czacie grupowym | Cokolwiek agent uznał za warte zapamiętania, kluczowane przez `person:<user_id>` albo pokój czatu | Ciągłość między rozmowami |
| `rag_documents`, `knowledge_bases` i jedna tabela wektorowa na kolekcję | Wgrane i zsynchronizowane dokumenty, ich chunki i embeddingi | Tekst dokumentu i jego wektory, oryginalna ścieżka pliku w źródle | Wyszukiwanie |
| `agent_runs`, `tool_approvals`, `run_manifests` | Ile każdy run kosztował i co zrobił | Prompt systemowy i ostatnie żądanie podane modelowi, argumenty narzędzi czekające na zatwierdzenie, osoba decydująca i jej notatka | Budżety, zatwierdzenia, historia runów |
| `agent_triggers` | Runy zaplanowane i wyzwalane zdarzeniem | Prompt oraz konfiguracja i filtr źródła zdarzeń | Uruchamianie agenta bez człowieka |
| `app_admin_audit_logs` | Kto zmienił dostęp albo wydał pieniądze — ślad organizacji i ślad administratora wdrożenia dzielą jedną tabelę | Aktor, podszywający się, adres IP, akcja i mapa `details`. Mapa przeważnie nazywa pola, ale niektóre wpisy trzymają wartości: e-mail konta, pod które się podszyto, e-mail konta usuniętego przez administratora, notatka publikacji | Rozliczalność. Zobacz [Nadzór](governance.md#audit) |
| `embed_visitors`, `channel_identities`, `channel_sessions` | Obcy na hostowanej stronie oraz ludzie na Slacku, Telegramie albo Mattermoście | Losowy klucz odwiedzającego; id użytkownika platformy, nazwa użytkownika i nazwa wyświetlana; id czatu | Wznowienie właściwego wątku |
| `message_ratings` | Kciuki i komentarze pod odpowiedziami | Oceniający i jego komentarz | Przegląd jakości |
| `ml_service_calls` | Każde wywołanie [usług ML](ml-services.md) | Organizacja, kto poprosił, która usługa, liczby bajtów i jednostek, czas trwania i sposób zakończenia - **nic z tego, co wysłano, i nic z tego, co wróciło** | Raportowanie zużycia i wgląd operatora w integrację, która się psuje |
| `agent_workspaces`, `sandbox_operations` | Pliki, na których pracował agent, i log tego, co uruchomił | Dla backendu `state` same pliki, jako JSON; dla kontenera id sesji oraz każda komenda, cel i podsumowanie wyniku | Sandbox. Zobacz [Sandbox](sandbox.md#what-was-done-in-one-and-where-that-record-lives) |
| `organization_secrets`, `model_profiles`, `mcp_connections`, `channel_bots` | Poświadczenia i to, gdzie wskazują | Wyłącznie zapieczętowany szyfrogram, z podpowiedzią; provider, model i `base_url` jawnie | Sięganie do providerów. Zobacz [Sekrety](secrets.md) |

`messages.search_vector` to indeks pełnotekstowy nad tą samą treścią,
a `conversations.summary_messages` to jej kompresja napisana przez model. Oba są
kopiami czatu i idą razem z nim.

### Poza bazą danych { #outside-the-database }

| Magazyn | Trzyma | Usuwane, gdy |
|---|---|---|
| `MEDIA_DIR` na hoście API (wolumen `media_data`) | Załączniki czatu pod `<user_id>/`, awatary, logotypy embedów, wygenerowane obrazy pod `generated_<org>/` oraz tymczasową kopię każdego dokumentu pod `_rag_tmp` na czas parsowania | Dokument zostaje usunięty przez produkt. **Nic w produkcie nie usuwa bajtów załącznika czatu** — ani usunięcie jego konwersacji, ani usunięcie jego właściciela. Zobacz [Co obejmuje usunięcie](#what-deletion-reaches) |
| `SANDBOXD_WORKSPACE_ROOT` na hoście sandboksa | Pliki każdego workspace'u opartego o kontener | Konwersacja zostaje usunięta albo zamiata je `SANDBOXD_WORKSPACE_TTL`; nieustawiony — trzymane bezterminowo. Zobacz [Jak długo cokolwiek przeżywa](sandbox.md#how-long-anything-survives) |
| Redis | Kubełki rate limitu kluczowane wywołującym — dla powierzchni publicznej to **jawny adres IP**, w kluczu, na czas TTL okna; klucze deduplikacji triggerów i kanałów; stan wymiany OAuth; zaparkowane zaproszenia | Po wygaśnięciu; nic tutaj nie przeżywa swoich minut |
| Prefect | Historia i logi flow-runów | Parametry to id i ścieżki, z jednym wyjątkiem: **`event_context` runu wyzwolonego zdarzeniem** — nadawca, temat i treść wiadomości Gmail, zgłoszenia GitHub, ładunku webhooka — podróżuje jako parametr flow i zostaje w historii runów. Logi workera przechodzą przez ten sam filtr redakcji co logi API |
| Logfire, jeśli skonfigurowany | Trace'y każdego runu | Retencja providera. Dziś trace niesie pełny prompt, wyjście i argumenty narzędzi — zobacz [Trace'y](#traces) |
| Twój relay SMTP | Zaproszenia, magic linki, prośby o zatwierdzenie, alerty budżetowe, raporty użycia | Cokolwiek relay zachowa. Mail o zatwierdzeniu nazywa agenta, narzędzie i link, a nie argumenty narzędzia |
| Kopie zapasowe | `pg_dump` to cała baza; wolumen mediów to pliki | Twoje wygaśnięcie kopii. Usunięcie nigdy nie sięga kopii już zrobionej — zobacz [Kopie zapasowe](deploy.md#backups) |

## Co opuszcza wdrożenie { #what-leaves-the-deployment }

Nic nie wychodzi, dopóki wiersz albo ustawienie nie wskaże celu. To jest pełna
lista celów, wraz z konfiguracją, która o każdym decyduje.

| Cel | Co jest wysyłane | Decyduje o tym | Lokalizacja i warunki |
|---|---|---|---|
| Model czatowy | Rozmowa jak dotąd, załączniki wklejone albo opisane, pobrane chunki, wyniki narzędzi | [Profil modelu](models.md#a-model-profile): `provider`, `model`, `base_url` i zapieczętowany klucz. Dwudziestu siedmiu providerów; `ollama` i `litellm` są bezkluczowe i sięgane pod endpointem, który hostujesz, a `openai`, `anthropic`, `google`, `huggingface` i inne przyjmują `base_url`, więc endpoint w UE albo gateway to pole, a nie rozwidlenie | Providera. Weryfikuj per profil |
| Model embeddingowy | Każdy chunk każdego dokumentu w kolekcji i każde zapytanie wyszukujące | Per kolekcja i tylko tam: `embedding_provider` (`openrouter`, `openai` albo `ollama`, z katalogu), a dla dwóch pierwszych klucz z vaultu `embedding_secret_id`, który płaci. Nie ma klucza embeddingowego na poziomie wdrożenia; kolekcja z kluczem, ale bez wskazanego, odmawia indeksowania i wyszukiwania. `ollama` jest bezkluczowa i sięgana pod usługą lokalną, którą kolekcja wskazuje (`embedding_endpoint_id`), na hoście, który prowadzisz | Providera albo Twój własny host. [Wybór na stałe](choosing-models.md#embeddings-are-a-separate-permanent-choice) |
| LlamaCloud | Cały dokument | Kolekcja, której `pdf_parser` to `llamaparse`; musi wskazać klucz z vaultu (`llamaparse_secret_id`), nie ma klucza wdrożenia. Domyślny `pymupdf` parsuje w workerze | LlamaCloud, jeśli użyty |
| Serwer OCR | Wyrenderowane strony dokumentu | Kolekcja, której `pdf_parser` to `liteparse` **i** której `ocr_endpoint_id` wskazuje usługę lokalną; bez tego OCR działa w workerze | Twój własny host — usługa lokalna jest z definicji w sieci wdrożenia |
| Model opisujący obrazy | Obrazy wewnątrz dokumentów | `image_description_model` kolekcji | Providera tego modelu |
| Web research | Zapytanie wyszukiwania, które ułożył agent | `web_research.method` w specu: `duckduckgo` (bez klucza), `tavily`, `brave` albo `exa` (każde z sekretem `search`), albo `native`, gdzie szuka provider modelu czatowego | Dostawcy wyszukiwania albo providera modelu |
| Web fetch i browser use | URL; dla browser use całe zadanie | Capability w specu; browser use potrzebuje też endpointu CDP, który wskażesz | Pobieranej strony; hosta przeglądarki |
| Sandbox, ruch wychodzący | **Cokolwiek z workspace'u, do dowolnego hosta** — runtime `workbench` ma sieć, powłokę i `curl` | Capability `sandbox` i runtime z `needs_network`; zatwierdzanie komend bramkuje to, co się uruchamia, a nie to, dokąd się łączy | Dokądkolwiek poszła komenda. Kontrola ruchu wychodzącego to firewall hosta sandboksa, a nie ustawienie tutaj |
| Serwer MCP | Argumenty i wyniki narzędzi | `mcp_connections.url`, per organizacja albo per osoba | Operatora serwera |
| mem0 | Wspomnienia zapisane dla osoby albo czatu | `base_url` capability `memory_mem0`, który musi być w `MEM0_ALLOWED_HOSTS` | Hosta mem0, na który pozwalasz |
| Logfire | Spany każdego żądania i runu | `LOGFIRE_TOKEN` na poziomie wdrożenia; token `observability` w specu albo `logfire_token_secret_id` na środowisku przekierowuje te runy do innego projektu. `LOGFIRE_BASE_URL` wybiera wdrożenie w USA albo w UE. Nieustawione wszędzie — nic nie jest wysyłane | Pydantic, USA albo UE |
| Mowa na tekst, generowanie obrazów | Notatka głosowa; prompt | Profil dla `groq`, `mistral` albo `openai`; profil dla `google` albo `openai` | Providera |
| Slack, Telegram, Mattermost | Odpowiedzi agenta | Wiersz `channel_bots` z tokenem w vaulcie | Dostawca komunikatora i tak ma już ten czat |
| Logowanie Google | Nic wychodzącego; Google zwraca e-mail, imię, zdjęcie i id konta | `GOOGLE_CLIENT_ID` | Google |
| Twój relay SMTP | Poczta wymieniona wyżej | `SMTP_HOST`, `SMTP_TLS` | Twoja |

Konektory synchronizacji działają w drugą stronę: źródło Google Drive albo S3
zaciąga dokumenty **do środka**, uwierzytelnione sekretem `connector`, a od tej
chwili dokumenty są kopią wdrożenia i podlegają regułom powyżej. To, kto może
przeczytać, co zaciągnęło źródło, jest
[decyzją, którą podejmuje wiersz źródła](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

## Kontrole i gdzie każda jest dowiedziona { #controls-and-where-each-is-proved }

Każdy wiersz nazywa mechanizm w kodzie oraz test albo stronę, która go przypina,
albo zgłoszenie, które to zrobi. Wiersz, którego ostatnia kolumna to zgłoszenie,
jest luką — i tak jest nazwany.

| Kontrola | Mechanizm | Dowiedziona przez |
|---|---|---|
| Izolacja tenantów | `organization_id` w każdej tabeli należącej do organizacji, rozwiązywany z `X-Organization-Id` do członkostwa przy każdym żądaniu; wiersze podrzędne osiągalne tylko przez sprawdzenie rodzica | `tests/integration/test_conversation_tenant_isolation.py` i jego rodzeństwo; [Uprawnienia](permissions.md) |
| Dostęp do wiersza | Trzy warstwy: administrator wdrożenia, rola w organizacji, grant per zasób przez `resolve_access`. Kontrolka, której wywołujący nie może użyć, nie jest renderowana | Testy odmów w `tests/api/`; [Uprawnienia](permissions.md#how-the-layers-combine) |
| Czytanie cudzego czatu | Właściciel, jawne udostępnienie albo administrator aplikacji wdrożenia — nigdy rola w organizacji. Konwersacje mają własne sprawdzenie, `ConversationService._may_read`, a nie formułę grantów | `admin_conversations.py` wymaga `is_app_admin`; `tests/integration/test_conversation_tenant_isolation.py` |
| Poświadczenia w spoczynku | Szyfrowanie kopertowe per organizacja, wersjonowane klucze główne, rotacja z suchym przebiegiem | [Sekrety](secrets.md#what-never-happens), cztery gwarancje przypięte testami |
| Treść w spoczynku | **Nieszyfrowana przez aplikację.** Dane Postgresa, `media_data` i katalog główny workspace'ów sandboksa polegają na szyfrowaniu dysku albo wolumenu, które zapewniasz | Kontrola operatora. Backend S3 z szyfrowaniem po stronie serwera dla plików to [#1423](https://github.com/vstorm-co/agenticos/issues/1423) |
| W tranzycie, przychodzące | HTTPS na Twoim proxy; `Strict-Transport-Security`, gdy `ENVIRONMENT=production`; ciasteczka sesji `httpOnly`, a `secure` ze schematu żądania przy logowaniu i odświeżeniu. Trasa zmiany hasła ustawia `secure` tylko w buildzie produkcyjnym | [Wdrożenie](deploy.md#choose-a-reverse-proxy); `frontend/src/app/api/auth/login/route.ts` |
| W tranzycie, do magazynów | `POSTGRES_SSLMODE` i `REDIS_SSL`; `agenticos cmd doctor` raportuje, czy połączenie, które nawiązał, było szyfrowane | [Połączenia szyfrowane](configuration.md#encrypted-connections-tls); `tests/integration/test_store_tls.py` |
| W tranzycie, do providerów | HTTPS do każdego skatalogowanego endpointu. Własny `base_url` jest odrzucany bez hosta albo z poświadczeniami w środku, ale **`http://` jest przyjmowany**, dla Ollamy albo gatewaya w sieci samego wdrożenia; profil na zwykłym HTTP wskazujący poza tę sieć wysyła prompty i klucz jawnie. Punkt 4 listy kontrolnej wypisuje każdy taki profil | `refused_field("base_url", ...)` w serwisie profili modeli; schemat to kontrola operatora |
| Sekrety w odpowiedziach, logach, audycie, eksportach | Żaden endpoint nie zwraca jawnego tekstu; `SecretStr` wszędzie; spece odwołują się do sekretów po id | [Sekrety](secrets.md#what-never-happens) |
| Dane osobowe w logach | `app/core/logging.py` redaguje adresy e-mail, JWT, klucze API, tokeny bearer i pary `password=` z każdego rekordu logu, tak w API, jak i w workerze | `tests/test_logging.py`; worker instaluje to w `prefect_app.py` (#440) |
| Dane osobowe docierające do modelu | Capability `guardrails` redaguje numery IBAN, numery kart, amerykańskie numery ubezpieczenia społecznego i adresy e-mail z promptów, odpowiedzi i wyników narzędzi, jeśli jest skonfigurowana | [Capabilities](reference/capabilities.md); jej testy pod `tests/` |
| Dane osobowe w kolumnie błędu | `rag_documents.error_message` i pokrewne zapisują etap i klasę, nigdy tekst klienta | `app/services/rag/failures.py` (#423) |
| Rozliczalność | Wpisy audytu dzielą transakcję działającą i zawodzą zamknięte; podszycie nazywa obie osoby; eksporty masowe są zapisywane | [Nadzór](governance.md#audit) |
| Eksport audytu | `GET /audit/export`, CSV albo JSONL w oknie czasu, bramkowany na `audit:read` i zapisywany w samym śladzie | [Governance](governance.md#audit) (#1422) |
| Dowód nienaruszalności śladu | Każdy wpis wchodzi w łańcuch haszy danej organizacji, a każdy łańcuch ma checkpoint na swoim najwyższym stanie, więc przepisany wpis, urwany koniec i skasowany łańcuch są wykrywalne. `agenticos cmd audit-verify` przechodzi je i kończy się kodem niezerowym przy naruszeniu | [Nadzór](governance.md#audit) (#1622, #1648). Wykrywanie, nie zapobieganie: kto ma poświadczenia samej bazy, ten przekuje łańcuch od nowa albo zdejmie trigger pilnujący checkpointu |
| Trace'y | `observability.content` per agent: `full` zapisuje wszystko, `none` tylko czas, tokeny, koszt i nazwy narzędzi, a tryb ten dziedziczy specjalista tego agenta | [Środowiska](environments.md) (#1413); stan pośredni `redacted` został odrzucony, [#1616](https://github.com/vstorm-co/agenticos/issues/1616) |
| Retencja według harmonogramu | Na organizację i na klasę — rozmowy i ich pliki, runy i manifesty, workspace'y, pamięć agentów, wgrane dokumenty i audyt — w ramach domyślnej wartości, sufitu i podłogi audytu na poziomie wdrożenia. Codzienny sweep usuwa twardo i zapisuje liczniki, nigdy treść. Backupy i cokolwiek już wysłane do zewnętrznego kolektora są poza tym | [Retencja](governance.md#retention); `test_retention.py`, `tests/integration/test_retention_sweep.py` |
| Usunięcie jednej osoby | Usunięcie konta uzgadnia to, co by je zablokowało; usunięcie pamięci to osobne wywołanie i sięga do mem0 | [Co obejmuje usunięcie](#what-deletion-reaches); [#1421](https://github.com/vstorm-co/agenticos/issues/1421) co do tego, co zostawia |
| Dostęp do własnych danych | Osoba czyta w Ustawienia → Pamięć wszystko, co każdy agent tutaj o niej zapisał, i może notatkę wyłączyć, przywrócić albo usunąć. Czytanie *cudzego* magazynu należy wyłącznie do administratora wdrożenia — nie do roli w organizacji — i jest audytowane z aktorem, tenantem, podmiotem i powodem, nigdy z treścią. Magazyny zewnętrzne (mem0) są nazwane, a nie listowane | [Jak to czytać i jak wymazać](reference/capabilities.md#reading-it-and-erasing-it); `test_memory_self_service.py`. Wszystko inne, co jest o niej trzymane, wraca z `GET /me/data/export`, ograniczone rozmiarem i audytowane (#1421) |
| Tożsamość korporacyjna | Logowanie Google i hasła; jeszcze bez OIDC | [#1419](https://github.com/vstorm-co/agenticos/issues/1419) |
| Macierz kontroli, którą czyta przegląd bezpieczeństwa | [Bezpieczeństwo](security.md#controls-matrix) mapuje każdą kontrolę na jej mechanizm i test, który go trzyma, w ramach HIPAA §164.312 i SOC 2 CC6–CC8; ta strona i [Wdrażanie](rollout.md#what-your-security-review-will-ask) to reszta | [Bezpieczeństwo](security.md) (#1412) |
| Powierzchnie publiczne | Klucz odwiedzającego hostowanej strony jest losowy, nigdy wyprowadzony z osoby; wpuszczanie i wgrywanie są rate-limitowane per adres, a adres leży w kluczu Redisa na czas okna i nigdzie indziej | [Kanały](channels.md#a-hosted-page) |
| Noty prawne | Własne adresy Regulaminu i Polityki prywatności wdrożenia zastępują strony wbudowane | [Wdrożenie](deployment.md#identity) |

### Trace'y { #traces }

`instrument_pydantic_ai()` działa z domyślnym ustawieniem biblioteki, więc span
trzyma wiadomość użytkownika, odpowiedź modelu oraz każdy argument i wynik
narzędzia. Z nieustawionym `LOGFIRE_TOKEN`, bez tokenu `observability` w żadnym
specu i bez `logfire_token_secret_id` na żadnym środowisku nic nie jest
wysyłane, a id trace'u i tak jest zapisywane lokalnie. Wdrożenie, które
potrzebuje trace'ów bez treści, ustawia agentowi `observability.content` na
`none`: zapisywane są czas, tokeny, koszt i nazwy narzędzi, a żaden tekst
wiadomości nie wychodzi — i tryb ten dziedziczy specjalista tego agenta, czy to
napisany inline przez autora, czy wymyślony przez model w trakcie runu.

Trzeciego trybu pomiędzy nie ma. Eksport wyczyszczony filtrem PII to gwarancja,
której nikt nie zaudytuje — jeden identyfikator, który filtr przepuści, już
wyszedł, a operator sądzi, że nie — więc wybór jest świadomie między całą treścią
a żadną ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)).

### Co obejmuje usunięcie { #what-deletion-reaches }

Usuwanie to to, co produkt robi dziś, gdy ktoś o to poprosi; retencja według
harmonogramu to [#1420](https://github.com/vstorm-co/agenticos/issues/1420).

| Akcja | Usuwa | Zostawia |
|---|---|---|
| `DELETE /conversations/{id}` (właściciel) | Konwersację, jej wiadomości, wywołania narzędzi, oceny, udostępnienia i wiersze `chat_files`, kaskadą; workspace kontenerowy jest czyszczony przez `purge_for_conversation` | **Bajty załączników pod `MEDIA_DIR`.** Żadna trasa nie usuwa pliku czatu; jedyna ścieżka kodu, która odlinkowuje taki plik, porzuca osierocone wgranie bota kanału. Wiersze runów i manifesty, które nazywały konwersację, zachowują swoją kopię promptu. Śledzone w [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| `DELETE /memory/person/{user_id}` (osoba albo `members:manage`) | Każdy wiersz `agent_memory_files` kluczowany na osobę we wszystkich agentach organizacji, i to samo w każdym związanym magazynie mem0 | Notatki kluczowane na czat grupowy, w którym osoba się odzywała |
| `DELETE /users/{id}` | Konto, jego sesje, jego osobistą organizację i osobiste kolekcje wraz z ich tabelami wektorowymi i plikami, przez jawne rozmontowanie; konwersacje i pliki czatu kaskadą | **Pamięć osoby** — `owner_key` to string, a nie klucz obcy, więc wpisy `agent_memory_files` i mem0 przeżywają, chyba że wcześniej wykonano `DELETE /memory/person`. Wpisy audytu nazywające id aktora oraz, dla niektórych akcji, e-mail; wiadomości w konwersacjach udostępnionych; bajty załączników wymienione wyżej. Inwentarz każdego z nich to produkt [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| Usunięcie dokumentu albo kolekcji | Wiersze, tabelę wektorową i zapisany plik, przez trwały flow po commicie | Nic, gdy flow już przebiegł; liczniki `sync_logs` zostają |
| Usunięcie organizacji | Wszystko do niej ograniczone, tym samym odroczonym rozmontowaniem | Kolekcje osobiste, które jedynie niosły to id |

Żadne z tych nie sięga kopii zapasowej. Odtworzenie przywraca to, co usunięto,
więc wygaśnięcie kopii jest częścią polityki retencji i jest spisane razem z nią.

## Co wdrożenie musi rozstrzygnąć i zdobyć { #what-a-deployment-has-to-decide-and-obtain }

Oprogramowanie nie może dostarczyć żadnej z tych rzeczy. Każda jest dowodem,
o który poprosi przegląd, i jest czymś innym niż techniczna możliwość, która ją
umożliwia.

- **Umowa powierzenia z każdym skonfigurowanym podprzetwarzającym** — każdym
  providerem nazwanym przez wiersz `model_profiles` albo `organization_secrets`,
  providerem embeddingów, LlamaCloud, jeśli kolekcja go używa, dostawcą
  wyszukiwania nazwanym przez `method` agenta, hostem mem0, Logfire, relayem
  SMTP i Google, jeśli logowanie jest włączone.
- **Oświadczenie o lokalizacji danych dla każdego providera**, dopasowane do
  `base_url`, którego faktycznie używa każdy profil. Provider z endpointem w UE
  jest w UE tylko wtedy, gdy profil tak mówi.
- **Wyłączenie z treningu dla każdego providera**: ustawienie konta albo zapis
  umowny, na mocy którego dane z API nie są używane do treningu. Własne
  stanowisko platformy to jedno zdanie — niczego nie trenuje — a reszta jest ich.
- **Umowa powierzenia z Vstorm**, tylko jeśli Vstorm prowadzi wdrożenie.
- **Harmonogram retencji** dla konwersacji, plików, pamięci, dokumentów, runów
  i audytu, a obok niego wygaśnięcie kopii zapasowych. Dopóki
  [#1420](https://github.com/vstorm-co/agenticos/issues/1420) nie wymusi
  harmonogramu, retencja jest ręcznym usuwaniem.
- **Szyfrowanie dysku albo wolumenu** na hoście bazy, wolumenie mediów i hoście
  sandboksa, skoro aplikacja sama nie szyfruje treści — oraz reguła ruchu
  wychodzącego na hoście sandboksa, jeśli agenci mogą uruchamiać komendy.
- **Strony prawne**, do których wdrożenie linkuje, i to, kto odpowiada na żądanie
  dostępu albo usunięcia, dopóki
  [#1421](https://github.com/vstorm-co/agenticos/issues/1421) jest otwarte.

## Weryfikacja jednego wdrożenia { #verifying-one-deployment }

Powtarzalne sprawdzenia, z hosta, na działającym wdrożeniu. Każde wypisuje
fakty, które przegląd może załączyć; żadne nie wypisuje poświadczenia ani
danych osoby. Uruchamiaj je z `backend/` albo przez `docker compose exec api`.

```bash
# 1. Czy to w ogóle ruszy i czy połączenia do magazynów są szyfrowane?
#    `postgres` raportuje stan TLS połączenia, które sam doctor nawiązał.
uv run agenticos cmd doctor

# 2. Każde zapieczętowane poświadczenie wciąż otwiera się pod skonfigurowanymi
#    kluczami głównymi.
uv run agenticos cmd vault-rotate --dry-run

# 3. Łańcuchy haszy śladu audytowego i ich checkpointy, przeliczone od nowa.
#    Kod wyjścia niezerowy, jeśli którykolwiek łańcuch został naruszony.
uv run agenticos cmd audit-verify

# 4. Wszystko, co to wdrożenie faktycznie skonfigurowało: ustawienia decydujące
#    o tym, co wychodzi na zewnątrz, każdy provider i endpoint, do którego może
#    sięgnąć agent, trzymane poświadczenia według przeznaczenia, kolekcje i to,
#    kto liczy dla nich embeddingi, serwery we własnej sieci, serwery MCP,
#    portale triggerów, źródła synchronizacji i boty kanałów, zdolności, które
#    sięgają pod własny adres, gdzie trafiają trace'y runów i ile treści niesie
#    span, ile w każdym magazynie objąłby okres retencji oraz pliki pod
#    `MEDIA_DIR`, na które nie wskazuje już żaden wiersz.
uv run agenticos cmd data-protection-report --older-than 365
```

Punkt 4 to ten do załączenia. Wypisuje konfigurację i liczby, nigdy treść:
żadnego tekstu wiadomości, żadnego dokumentu, żadnej wartości sekretu ani jej
podpowiedzi, a ustawienie trzymające poświadczenie jest raportowane jako
ustawione albo nieustawione, nie wypisywane. `--older-than` to rozważany okres
retencji, w dniach, a ostatnia kolumna jego tabeli retencji pokazuje, co ten
okres już by usunął.

Jego ostatnia sekcja to licznik, który przewiduje
[Co obejmuje usunięcie](#what-deletion-reaches) na tej stronie: wiersz
`chat_files` znika kaskadowo razem ze swoją wiadomością, a bajty zostają, więc
liczba rośnie z każdą usuniętą konwersacją, dopóki
[#1421](https://github.com/vstorm-co/agenticos/issues/1421) nie zacznie usuwać
obu naraz. Wygenerowane obrazy i katalog roboczy parsowania są wyłączone, bo z
założenia nie mają wiersza; wszystko inne, co się tam liczy, to bajty, których
produkt już nie znajdzie i nie umie usunąć. Raportuje katalog i liczbę, a nie
nazwę pliku, bo zapisana ścieżka zachowuje nazwę, pod którą plik został wgrany.

Dwie sekcje czyta się z tego, co się wykonuje, a nie z tabeli. **Cele zdolności**
wymieniają zdolności podpięte do agenta, które sięgają pod własny adres —
`web_research` szuka przez DuckDuckGo bez żadnego poświadczenia, a więc bez
wiersza gdziekolwiek indziej w raporcie — a **Tracing** czyta się z każdej wersji
zdolnej do uruchomienia: domyślnej oraz tej, którą przypina każde nazwane
[środowisko](environments.md), bo run przez to środowisko używa obserwowalności
tamtej wersji, a nie domyślnej.

Czego żadna komenda nie wytworzy, to druga połowa tej strony: umowy, lokalizacje
i wyłączenia z treningu z poprzedniej sekcji. Załącz je obok wyniku.

## Otwarte warunki pierwszego wdrożenia { #open-conditions-for-a-first-rollout }

Spisane dla wdrożenia, pod które powstała ta strona, i prawdziwe dla każdego
wdrożenia, dopóki każdy z nich się nie zamknie.

**W kodzie, śledzone:**

- Brak retencji według harmonogramu — [#1420](https://github.com/vstorm-co/agenticos/issues/1420).
- Bajty załączników i pamięć osoby przeżywają usunięcie swojego właściciela; brak
  eksportu danych osobowych; inwentarz usunięcia —
  [#1421](https://github.com/vstorm-co/agenticos/issues/1421).
- Pliki wyłącznie na dysku lokalnym, szyfrowane przez wolumen albo wcale — [#1423](https://github.com/vstorm-co/agenticos/issues/1423).
- Brak logowania OIDC — [#1419](https://github.com/vstorm-co/agenticos/issues/1419).

**Zamknięte i opisane wyżej, a nie tutaj:** dowód nienaruszalności śladu
audytowego (#1622, #1648), tryb treści trace'u per agent i jego dziedziczenie przez specjalistów (#1413, #1699), trace'owanie w procesie wykonującym
uruchomionego agenta (#1700) oraz macierz
kontroli HIPAA i SOC 2 w [Bezpieczeństwie](security.md#controls-matrix) (#1412).
Trace'y nie mają stanu pośredniego z filtrem i go nie dostaną
([#1616](https://github.com/vstorm-co/agenticos/issues/1616)); dla wdrożenia,
które nie może eksportować treści, odpowiedzią jest `none`.

**We wdrożeniu, rozstrzygane przez jego operatora:** umowy, lokalizacje,
wyłączenia z treningu, harmonogram retencji, wygaśnięcie kopii zapasowych,
szyfrowanie dysku, ruch wychodzący sandboksa i strony prawne z poprzedniej
sekcji. Każdy z nich to dowód, którego `data-protection-report` celowo nie
wytwarza.

Przegląd, który zastanie każdy wiersz powyżej albo zamknięty, albo zaakceptowany
na piśmie, ma to, co ta strona może mu dać. Reszta należy do wdrożenia.
