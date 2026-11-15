---
source_sha: "37f61b35dd4e"
---

# Wdrożenie na Kubernetes { #deploy-on-kubernetes }

`charts/agenticos` instaluje API, worker i konsolę z opublikowanych obrazów.
Wymaga zewnętrznego PostgreSQL z pgvector, Redis/Valkey oraz istniejącego bucketa
S3. Nie instaluje baz ani nie zapewnia ich backupów. `appVersion` charta określa
domyślną wersję obrazów. Inną wersję przypniesz przez `image.tag`, a konkretne
obrazy przez `image.backendDigest` i `image.frontendDigest`.

Obrazy backendu starsze niż 1.63.0 oczekują współdzielonych plików tymczasowych
ingestu i nie są obsługiwane przez ten chart.


## Zgodność i ograniczenia { #compatibility-and-limits }

Odtwarzalny test używa kind 0.33.0, Kubernetes 1.37.0 i Helm 4.3.1. Sprawdza
restrykcyjną politykę Pod Security, system plików tylko do odczytu, dowolne numeryczne
UID, migracje, logowanie, odpowiedź opublikowanego agenta, upload S3, ingest i
trwały run w tle. Model jest deterministyczną atrapą protokołu; test nie sprawdza
dostępności ani jakości odpowiedzi płatnego dostawcy.

**OpenShift pozostaje niezweryfikowany.** `values-openshift.yaml` usuwa stałe UID i
`fsGroup`, aby `restricted-v2` mógł przypisać zakresy przestrzeni nazw. Sprawdź tę
konfigurację na swojej wersji OpenShift. Dowolny UID w Kubernetes nie weryfikuje
SCC, SELinux, Routes ani sterowników storage. Nie nadawaj `anyuid`, uprzywilejowanych
SCC ani dostępu do socketu węzła, żeby uruchomić aplikację.

Bazowy chart nie uruchamia daemona sandboxa, usługi przeglądarki ani renderera
artefaktów i nie montuje socketu Dockera. Wykonywanie kodu w kontenerze, obsługa
komputera/przeglądarki i rendering wymagające tych usług pozostają niedostępne,
dopóki nie podłączysz odpowiedniej usługi zewnętrznej. Skorzystaj z
[konfiguracji sandboxa](sandbox.md) i vaulta; nie montuj `/var/run/docker.sock`
z węzła do podów aplikacji.

## Przygotowanie usług zewnętrznych { #prepare-external-services }

Utwórz bazę i użytkownika `agenticos` na PostgreSQL z pgvector. Konto migracji
musi móc utworzyć rozszerzenie vector albo administrator bazy musi je wcześniej
zainstalować. Zapewnij aplikacji dostęp do jej bazy, bazy Redis i bucketa.
Zobacz [usługi zewnętrzne i liczbę połączeń](scaling.md).

Bucket musi istnieć przed bootstrapem: trafiają do niego również awatary agentów
startowych. Domyślne szyfrowanie to `sse-s3`. `storage.encryption: sse-kms` wymaga
też `storage.kmsKeyId`. Testowe MinIO bez KMS używa `none`; nie oznacza to zalecenia
wyłączania szyfrowania na produkcji.

Przez swojego menedżera sekretów utwórz Secret w przestrzeni nazw aplikacji
**przed uruchomieniem Helm**. Wymagane klucze to niezależne `SECRET_KEY`, `API_KEY`
i `VAULT_MASTER_KEY`, wygenerowane przez `openssl rand -hex 32`, oraz
`POSTGRES_PASSWORD`. Zachowuj je podczas aktualizacji. Zmiana klucza vaulta to
[rotacja klucza](secrets.md), a nie ponowna instalacja: odszyfrowuje on zapisane
dane uwierzytelniające organizacji. Dodaj `REDIS_PASSWORD`, jeśli jest wymagane,
oraz parę `FILE_STORAGE_S3_ACCESS_KEY` / `FILE_STORAGE_S3_SECRET_KEY` dla stałych
poświadczeń S3. Pomiń oba klucze S3 przy użyciu tożsamości workloadu.

Chart używa istniejącego konta usługi z wyłączonym automatycznym montowaniem
tokenu API. Dla tożsamości workloadu ustaw `serviceAccountName` i skonfiguruj na
tym koncie adnotacje/projekcję tokenu wymagane przez dostawcę. Hooki migracji też
używają tego konta. Klucze modeli pozostają sekretami organizacji w vaulcie produktu.

Dla `postgres.sslMode: verify-full` (wartość domyślna) lub `verify-ca` utwórz
Secret wskazany przez `trust.existingSecret`, z kluczem `postgres-ca.crt`
zawierającym certyfikat CA bazy. Chart montuje go tylko do odczytu w migracji,
API i workerze oraz ustawia `PGSSLROOTCERT`. Inną nazwę pliku wybiera
`trust.postgresCaKey`. Dla prywatnego CA Redis dodaj pakiet publicznych i prywatnych
CA i wskaż jego klucz przez `trust.sslCaKey`; ustawi to `SSL_CERT_FILE`. Zachowaj
publiczne CA potrzebne dostawcom modeli. Inne ustawienia SDK, np. `AWS_CA_BUNDLE`,
mogą wskazywać ten sam mount przez `extraEnv`.

## Instalacja { #install }

Użyj charta z taga repozytorium odpowiadającego wdrażanej wersji. Przygotuj plik
`cluster-values.yaml` z konfiguracją, bez danych uwierzytelniających:

```yaml
existingSecret: agenticos-runtime
public:
  siteUrl: https://app.example.com
  apiUrl: https://api.example.com
  websocketUrl: wss://api.example.com
postgres:
  host: postgres.internal
  database: agenticos
  user: agenticos
  sslMode: verify-full
trust:
  existingSecret: agenticos-trust
  postgresCaKey: postgres-ca.crt
redis:
  host: valkey.internal
  ssl: true
storage:
  bucket: agenticos-files
  region: eu-central-1
  # endpoint: https://s3.example.com
  # pathStyle: true
image:
  tag: "1.63.0"
trustedProxy:
  enabled: true
  namespaceLabels:
    kubernetes.io/metadata.name: ingress-system
  podLabels:
    app.kubernetes.io/name: your-ingress-controller
ingress:
  enabled: true
  className: your-ingress-class
  siteHost: app.example.com
  apiHost: api.example.com
  tls:
    - secretName: agenticos-tls
      hosts: [app.example.com, api.example.com]
```

```bash
helm lint charts/agenticos --strict -f cluster-values.yaml
helm upgrade --install agenticos charts/agenticos \
  --namespace agenticos --create-namespace -f cluster-values.yaml \
  --wait --timeout 15m
kubectl -n agenticos exec deployment/agenticos-agenticos-api -- agenticos cmd bootstrap
```

[Instalacja](install.md) opisuje dane bootstrapu i konfigurację dostawcy. Jeśli
przestrzeń nazw nie istnieje, utwórz ją przed Secretem. Dla prywatnych rejestrów
ustaw `imagePullSecrets`. Nie używaj `kubectl apply` na wyrenderowanym charcie:
pomija to kolejność migracji zapewnianą przez Helm.

Użyj dwóch publicznych nazw hostów, jak we
[wdrożeniu Compose](deploy.md#why-two-hostnames). Kontroler ingress musi obsługiwać
WebSocket, odpowiednio długie limity bezczynności i żądań oraz rozmiar uploadu.
Ustaw to adnotacjami swojego kontrolera w `ingress.annotations`. TLS obsłuży
istniejący Secret certyfikatu lub kontroler certyfikatów. Na OpenShift możesz
wyłączyć ingress charta i dostarczyć dwie własne Routes.

Ogranicz ruch politykami klastra: konsola łączy się z API, a API i worker z
Postgresem, Redis, S3 i jawnie skonfigurowanymi dostawcami/usługami zewnętrznymi.
Nie wystawiaj publicznie portów bazy ani workera.

Publiczny ingress wymaga `trustedProxy.enabled: true` i niepustych selektorów
etykiet przestrzeni nazw oraz podów kontrolera. Zastąp przykład rzeczywistymi
etykietami chronionego kontrolera. Włącza to `RATE_LIMIT_TRUST_FORWARDED_FOR`
razem z NetworkPolicies: do konsoli dociera tylko ten kontroler, a do API także
pody konsoli danego wydania. CNI musi egzekwować NetworkPolicy; nie wystawiaj usług
bezpośrednio. Chroń te przestrzenie nazw przed tworzeniem niezaufanych podów.
Bez egzekwowania polityk nie włączaj zaufania do nagłówka.

Dokładnie jeden zaufany proxy ma dopisywać rzeczywistego klienta do
`X-Forwarded-For`. Limiter czyta ostatni adres, a konsola zachowuje nagłówek przy
proxy żądań auth. Jeśli CDN/load balancer dodaje kolejny hop, znormalizuj
zweryfikowany adres na brzegu. Test ClusterIP nie weryfikuje wybranego kontrolera
ingress ani CNI; sprawdź izolację i nagłówki przed otwarciem ruchu produkcyjnego.
Zewnętrzne Routes/proxy wymagają takich samych ustawień zaufanego proxy.

## Zdrowie, storage i zasoby { #health-storage-and-capacity }

API sprawdza `/api/v1/health/live` przy starcie i dla liveness, a
`/api/v1/health/ready` dla gotowości bazy/Redis. Worker sprawdza plik heartbeat
zależny od bazy. Konsola używa `/login` dla startu/gotowości i nasłuchującego
socketu dla liveness. Wolny dostawca nie oznacza awarii procesu. Każdy workload
ma 60 sekund na zakończenie; worker przestaje pobierać zadania i kończy je lub
oddaje do kolejki.

Zasoby ustawiasz osobno w `api.resources`, `worker.resources`,
`frontend.resources` i `migration.resources`. Pamięć dzieci ingestu dolicza się
do procesu rodzica. Dostosuj `extraEnv.WORKER_INGEST_CHILDREN` i
`extraEnv.WORKER_INGEST_MEMORY_MB` razem z limitem poda. Skaluj przez `api.replicas`,
`worker.replicas` i `frontend.replicas`, uwzględniając pule połączeń każdego procesu.

Pliki trwale zapisuje S3; worker pobiera własną kopię do ingestu. Nie potrzeba
wspólnego systemu plików ani PVC RWX. Cache i staging używają ograniczonych
wolumenów `emptyDir`; ich utrata jest oczekiwana i nie są backupem. Zabity proces
ingestu może zostawić plik do wymiany poda; zwykłe zakończenie, błąd parsera i
anulowanie usuwają kopię. Źródła synchronizacji z lokalnego katalogu muszą być
dostępne dla wykonującego workera; chart nie montuje katalogów operatora.

## Aktualizacja i rollback { #upgrade-and-rollback }

Przed aktualizacją wykonaj backup PostgreSQL, S3 i kluczy. Sprawdź release notes
oraz zgodność migracji ze starą i nową aplikacją. Job przed instalacją lub
aktualizacją wykonuje `agenticos db upgrade`. Jego błąd zatrzymuje Helm przed
zmianą deploymentów. Nieudane zadania pozostają do diagnostyki:

```bash
kubectl -n agenticos logs job/agenticos-agenticos-migrate
helm history agenticos -n agenticos
```

Zapisz logi przed ponowieniem: następny hook usuwa poprzedni Job. Nie uruchamiaj
równoległych aktualizacji jednego wydania, nie używaj `--no-hooks` i nie startuj
ręcznie nowych podów po błędzie migracji. Operator musi ocenić częściowo wykonaną
migrację; Helm nie cofnie skutków operacji na bazie.

Aktualizacja krocząca wymaga zgodności schematu i zadań kolejki przy równoczesnym
działaniu starych procesów. Dla zmiany niezgodnej zatrzymaj ruch, poczekaj na
aktywne zadania, przeskaluj wszystkie trzy deploymenty do zera, wykonaj backup i
aktualizuj w oknie serwisowym. Przed przywróceniem ruchu sprawdź gotowość i realny run.

Przy pierwszej aktualizacji istniejącego wdrożenia S3 do 1.63.0 opróżnij ingest
i wymień workery przed aktualizacją API albo użyj okna serwisowego. Nowe API nie
zapisuje współdzielonych kopii tymczasowych oczekiwanych przez stare workery.
Lokalny storage zachowuje dotychczasową zasadę współdzielonego katalogu.

`helm rollback agenticos REVISION -n agenticos --wait --timeout 15m` przywróci
starszą aplikację tylko wtedy, gdy jej hook migracji zaakceptuje obecną bazę.
Nie cofa schematu. Gdy stary obraz nie rozpoznaje nowej rewizji, hook pre-rollback
odmówi przed wymianą podów. Jeśli wymagają tego release notes, świadomie odtwórz
zgodny backup bazy, obiekty i klucze. `helm uninstall` usuwa aplikację; zewnętrzne
bazy, bucket i Secret pozostają własnością operatora.

## Odtworzenie testu { #reproduce-the-test }

Zainstaluj Docker, kubectl 1.37.0, kind 0.33.0, Helm 4.3.1 i Python z PyYAML. Z katalogu
repozytorium uruchom `python3 scripts/kubernetes/test_chart.py`, następnie
`scripts/kubernetes/run-smoke.sh`. Skrypt tworzy i usuwa własny klaster kind,
używa oddzielnego kubeconfigu i odmawia zastąpienia istniejącego klastra. Nie używa
aktualnego kontekstu Kubernetes. Porty 18000 i 13000 muszą być wolne.

Przed pierwszym wydaniem tej zmiany zbuduj backend ze źródeł i ustaw
`SMOKE_BACKEND_IMAGE=agenticos-smoke-backend:ci` oraz `SMOKE_FRONTEND_TAG=1.62.8`,
jak workflow Kubernetes. Test obejmuje też nieudaną migrację, udaną aktualizację,
rollback tego samego schematu i rollout dowolnego UID. Bazy oraz bucket testowy są
jednowęzłowymi atrapami usług, a nie manifestami produkcyjnymi. CI zapisuje wersje
narzędzi i identyfikatory obrazów w logu. `SMOKE_KEEP_CLUSTER=true` zachowuje klaster
do diagnostyki; usuń go później przez `kind delete cluster --name agenticos-smoke`.
