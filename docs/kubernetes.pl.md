---
source_sha: "40e46eb28642"
---

# Wdrożenie na Kubernetes { #deploy-on-kubernetes }

`charts/agenticos` instaluje API, worker i konsolę z opublikowanych obrazów.
Wymaga zewnętrznego PostgreSQL z pgvector, Redis/Valkey oraz istniejącego bucketa
S3. Nie instaluje baz ani nie zapewnia ich backupów. `appVersion` charta określa
domyślną wersję obrazów. Inną wersję przypniesz przez `image.tag`, a konkretne
obrazy przez `image.backendDigest` i `image.frontendDigest`.

Obrazy backendu starsze niż 1.63.0 oczekują współdzielonych plików tymczasowych
ingestu i nie są obsługiwane przez ten chart.


## Kubernetes a OpenShift { #kubernetes-and-openshift }

Kubernetes uruchamia kontenery i zarządza nimi. Red Hat OpenShift to platforma
Kubernetes z dodatkowymi komponentami i politykami, w tym Security Context
Constraints (SCC), integracją SELinux i Routes. Ten sam chart stanowi punkt
wyjścia dla obu platform. Udany test Kubernetes nie weryfikuje tych komponentów
OpenShift ani integracji tożsamości i storage u dostawcy chmury.

| Sposób wdrożenia | Dowody i pozostałe sprawdzenia |
| --- | --- |
| Kubernetes z Helm | Odtwarzalny smoke na kind opisany poniżej; publiczny ingress i egzekwowanie NetworkPolicy wymagają testów w Twoim klastrze |
| OpenShift z Helm | Lokalny OpenShift 5.0.0 przeszedł restricted-v2, cykl Helm, HTTPS Routes, WSS i egzekwowanie NetworkPolicy; swój klaster i storage zweryfikuj osobno |
| Argo CD na lokalnym OpenShift | Argo CD Core 3.6.1 przeszedł instalację przez pełny sync, odmowę migracji, zmianę konfiguracji i zgodny powrót rewizji Git na tym samym schemacie bazy |
| Sandbox i OIDC | Opcjonalne integracje z osobną konfiguracją i testami akceptacyjnymi poniżej |

## Zgodność i ograniczenia { #compatibility-and-limits }

Odtwarzalny test używa kind 0.33.0, Kubernetes 1.37.0 i Helm 4.3.1. Sprawdza
restrykcyjną politykę Pod Security, system plików tylko do odczytu, dowolne numeryczne
UID, migracje, logowanie, odpowiedź opublikowanego agenta, upload S3, ingest i
trwały run w tle. Model jest deterministyczną atrapą protokołu; test nie sprawdza
dostępności ani jakości odpowiedzi płatnego dostawcy.

**OpenShift Local został przetestowany** z CRC 2.65.0, OpenShift 5.0.0
(Kubernetes 1.36.5), Helm 4.3.1 i obrazami aplikacji 1.80.0. API, worker i konsola
przeszły `restricted-v2`, z UID przypisanymi przez namespace, systemem root tylko
do odczytu i bez uprawnień `anyuid`, uprzywilejowanego SCC ani socketu węzła.
`values-openshift.yaml` pozostawia wybór UID i `fsGroup` polityce SCC. Wynik nie
obejmuje innych wersji OpenShift, integracji Azure ani sterowników storage.

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
  tag: "1.80.0"
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

## Poświadczenia S3 i diagnoza bootstrapu { #s3-credentials-and-bootstrap-troubleshooting }

S3 to protokół storage, a nie wymóg korzystania z AWS. Dla zgodnej usługi, np.
MinIO, ustaw `storage.endpoint`, `storage.bucket`, `storage.region` oraz wymagane
przez dostawcę `storage.pathStyle` i szyfrowanie. Natywne API Azure Blob Storage nie
jest endpointem S3; ten chart wymaga usługi zgodnej z S3.

Stałe poświadczenia umieść w Secrecie wskazanym przez `existingSecret`, pod dokładnymi
kluczami `FILE_STORAGE_S3_ACCESS_KEY` i `FILE_STORAGE_S3_SECRET_KEY`. API, worker i
migracja wczytują go przez `envFrom`. Nie umieszczaj kluczy pod `storage` lub
`extraEnv`, w Git ani w publicznym komentarzu diagnostycznym. Tożsamość workloadu
musi dostarczać łańcuch poświadczeń rozumiany przez klienta S3; sama tożsamość
klastra Azure nie zapewnia poświadczeń S3.

`botocore.exceptions.NoCredentialsError` podczas `agenticos cmd bootstrap` oznacza,
że klient S3 nie znalazł poświadczeń przy zapisie awatara agenta startowego.
Transakcja bazy jest wycofywana; wcześniejsze „Created owner” nie potwierdza jej
zatwierdzenia. Popraw Secret, zrestartuj API i worker, aby odczytały zmienne,
poczekaj na gotowość i ponów bootstrap. Osobno sprawdź istnienie bucketa, dostępność
endpointu, zaufanie TLS i prawa zapisu. Nie wypisuj wartości sekretów podczas diagnozy.

## Instalacja OpenShift i katalogi zapisywalne { #openshift-installation-and-writable-directories }

Najpierw utwórz projekt, Secret konfiguracji i konto usługi. W poniższych poleceniach
zachowaj nazwę release'u `agenticos`. Zastosuj profil kandydujący przed konfiguracją
klastra i pozostaw nieustawione UID oraz grupy:

```bash
oc new-project agenticos
helm upgrade --install agenticos charts/agenticos --namespace agenticos \
  -f charts/agenticos/values-openshift.yaml -f cluster-values.yaml \
  --wait --timeout 15m
oc -n agenticos get pods
oc -n agenticos get pods -o 'custom-columns=NAME:.metadata.name,SCC:.metadata.annotations.openshift\.io/scc'
```

Sprawdź, czy przyjęty SCC odpowiada zamierzonej restrykcyjnej polityce. Nie naprawiaj
uprawnień przez `anyuid`, uprzywilejowane SCC lub zapisywalny główny system plików.
Frontend montuje zapisywalne `emptyDir` w `/tmp` i `/app/.next/cache`; mounty backendu
są w `templates/_helpers.tpl`. Zgłoszenie błędu `router-cache` wymaga **dokładnej
ścieżki absolutnej**, tagu/digestu obrazu, wersji OpenShift, przyjętego SCC i logu
bez danych poufnych. Cache poza tymi mountami nie jest objęty obecnym chartem.
Nie montuj wolumenu nad całym `/app/.next`, bo ukryje zbudowaną aplikację.

Przy `ingress.enabled: false` zapewnij dwie Routes HTTPS do Services API i frontendu,
obie z nazwanym portem `http`. Ustaw `public.siteUrl`, `public.apiUrl` i
`public.websocketUrl` na adresy zewnętrzne. Skonfiguruj timeouty routera, WebSockets,
limity uploadu, chronione selektory routera pod `trustedProxy` i egzekwowanie
NetworkPolicy. Sama terminacja TLS nie potwierdza poprawnej obsługi adresu klienta.

## Kolejność migracji w Argo CD { #argo-cd-migration-ordering }

Argo CD renderuje szablony Helm; nie uruchamia `helm upgrade`.
[Mapowanie hooków Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/#helm-hooks)
przekształca Job migracji `pre-install` i `pre-upgrade` tego charta w `PreSync`;
`before-hook-creation` pozwala ponowić go podczas następnej synchronizacji.
Przygotuj namespace, Secrets i konto usługi **przed** tą fazą, poza tą Application
lub we wcześniejszej, zakończonej operacji przygotowawczej.

Uruchom pełną synchronizację Application i potwierdź sukces migracji przed zmianą
Deploymentów. Synchronizacja selektywna pomija hooki. Adnotacje hooków Argo CD
zmieniają obsługę hooków Helm; nie mieszaj cykli życia bez testów wyniku. Zachowaj
nazwę Application równą nazwie release'u Helm, chyba że świadomie konfigurujesz
śledzenie zasobów Argo CD tak, aby zachować selektory instancji tego charta.

Cofnięcie Git nie cofa bazy. Argo CD nie implementuje hooka Helm `pre-rollback`;
pełna synchronizacja starszego charta przechodzi własną ścieżkę PreSync. Przed
automatyczną synchronizacją sprawdź na swojej wersji Argo CD odmowę wdrożenia po
błędzie migracji, udany upgrade i zgodne cofnięcie. Nie używaj Helm i Argo CD jako
konkurencyjnych właścicieli tego samego release'u.

Dla OpenShift wczytaj profil jako **plik wartości** Helm w Argo CD:

```yaml
helm:
  releaseName: agenticos
  valueFiles:
    - values-openshift.yaml
```

To konfiguracja `spec.source.helm` dla źródła `charts/agenticos`; dodaj ustawienia klastra
bez sekretów i referencje do istniejących Secretów
zgodnie z przykładem instalacji. Nie polegaj na `null` w inline `valuesObject`,
aby usunąć domyślne UID lub `fsGroup`. W lokalnym teście nie dotarły do Helm zgodnie
z zamiarem; plik profilu rozwiązał odmowę SCC dla UID/grupy 1000 bez rozszerzania uprawnień.

Lokalny Argo CD Core 3.6.1 przeszedł pierwszy pełny sync, odmowę po błędzie PreSync bez zmiany specyfikacji Deploymentów, zmianę konfiguracji konsoli i zgodny powrót rewizji Git na tym samym schemacie bazy. Controller mógł zapisywać tylko w namespace walidacji i używał [`resource.respectRBAC: strict`](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/). Nie otrzymał prawa użycia `anyuid` ani uprzywilejowanych SCC. Nie jest to walidacja operatora Red Hat OpenShift GitOps ani downgrade bazy.

## Konfiguracja OIDC i sandboxa { #oidc-and-sandbox-configuration }

Lokalna konfiguracja OIDC zachowuje zainstalowane tagi i digesty obrazów Helm dla backendu i konsoli; skonfigurowanie logowania nie wybiera innego obrazu aplikacji.

Jawne ustawienia backendu OIDC dodaj do głównego `extraEnv`, `OIDC_CLIENT_SECRET`
umieść w `existingSecret`, a przycisk logowania włącz osobno:

```yaml
extraEnv:
  OIDC_ISSUER: https://identity.example.com/realms/company
  OIDC_CLIENT_ID: agenticos
  OIDC_REDIRECT_URI: https://api.example.com/api/v1/oauth/oidc/callback
frontend:
  extraEnv:
    OAUTH_PROVIDERS: oidc
    OIDC_DISPLAY_NAME: Company SSO
```

`frontend.extraEnv` jest dostępne od wersji charta `0.1.1`; starsze charty je ignorują.
Zawiera publiczne ustawienia konsoli, nigdy sekret klienta. Adresy backendu i publiczne
zarządzane przez chart mają pierwszeństwo przed powtórzonymi kluczami frontendu.
Zarejestruj dokładny callback u dostawcy tożsamości. Sprawdź przycisk, przekierowanie,
callback, claim potwierdzonego e-maila, dostęp do organizacji, wylogowanie i politykę
rejestracji wdrożenia. [Opis OIDC](configuration.md#single-sign-on-generic-oidc)
podaje ustawienia i claimy dostawców. Smoke z logowaniem hasłem nie testuje SSO.

Dla narzędzi sandbox uruchom osobny serwer OpenSandbox i zarejestruj jego URL,
obraz oraz klucz z sejfu w **Ustawienia → Sandboxes → Connections**. Bazowy chart
nie instaluje tej usługi. Lokalny test OpenShift używał serwera, controllera,
execd i gateway 1.2.1, providera Kubernetes BatchSandbox oraz Secure Access.
Rzeczywiste narzędzie zapisało plik, a kolejny run dołączył do sesji i odczytał go;
próba połączenia wykonała polecenie powłoki POSIX. Test obejmuje uwierzytelnianie
endpointów i restrykcyjny workload, a nie gVisor, izolację VM, politykę egress,
przeglądarkę czy rendering.

Chart serwera dostawcy 1.2.1 deklaruje port kontenera 80. W tym restrykcyjnym teście
`configToml` ustawiał `server.port = 8080`, a
`scripts/kubernetes/opensandbox_ports.py` zmieniał nazwany port HTTP kontenera na
8080, zachowując odwołania Service i sond. Ten wykonywalny post-renderer wymaga
Helm 3 (przetestowano 3.22.1); Helm 4 wymaga pluginu post-renderera. Szablon workloadu
montował prywatne `emptyDir` w `/workspace` i `/tmp`, pozostawiając UID i grupy SCC.
Secure Access używał prywatnego gateway i osobnego Secretu z keyringiem. To ustawienia
dostawcy, nie wartości charta AgenticOS.

**Sprzątanie wymaga poprawki usuwania rozmowy z tej zmiany.** Wydana wersja 1.80.0
usuwała referencje workspace przed zakolejkowaniem zdalnego usunięcia. Test kandydującego
handlera na tym obrazie potwierdził usunięcie sandboxa i poda po skasowaniu rozmowy.
Sam tag obrazu nie potwierdza obecności poprawki. Przeglądanie i pobieranie plików
OpenSandbox przez API archiwum workspace konsoli nie jest zaimplementowane; narzędzia
plikowe agenta korzystają z osobnej ścieżki. Zobacz [konfigurację sandboxa](sandbox.md).

Usuwanie autoryzuje dostęp, blokuje rozmowę i ponownie sprawdza dostęp przed usunięciem wierszy workspace. Dzięki temu usuwanie konta i sprzątanie workspace zachowują tę samą kolejność blokad: najpierw rodzic. Oczekujące usunięcie i jego przekazanie po commicie zachowują ochronę przy rollbacku.

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

## Testy lokalne i kryteria akceptacji { #local-validation-and-acceptance }

Obie platformy można testować lokalnie, ale wymagają osobnych klastrów. Użyj kind
dla Kubernetes i [OpenShift Local (CRC)](https://crc.dev/docs/getting-started/)
dla rzeczywistego OpenShift. Instalacja `oc` nie dodaje SCC ani Routes do kind.
CRC obsługuje Apple Silicon w profilu OpenShift; profil OKD go nie obsługuje.
[Aktualne minimum](https://crc.dev/docs/installing/) dla OpenShift to cztery
fizyczne rdzenie CPU, 10,5 GB wolnego RAM i 35 GB dysku, przed zasobami aplikacji.
Na laptopie z ograniczonymi zasobami nie uruchamiaj obu klastrów jednocześnie.

Smoke Kubernetes tworzy jednorazowe usługi pgvector, Valkey, MinIO i atrapę protokołu
modelu; nie wymaga konta AWS ani płatnego klucza modelu. `SMOKE_IMAGE_TAG` przypina
testowany release dla obu obrazów. `SMOKE_BACKEND_IMAGE` i `SMOKE_FRONTEND_TAG`
nadpisują odpowiednie obrazy przy testach kodu źródłowego.

```bash
python3 scripts/kubernetes/test_chart.py
SMOKE_IMAGE_TAG=1.80.0 scripts/kubernetes/run-smoke.sh
```

Automatyczny test konsoli potwierdza tylko ustawienia wyświetlania OIDC; nie łączy
się z dostawcą tożsamości. Atrapa modelu sprawdza protokół runa, nie jakość modelu.
Smoke używa port-forwardingu ClusterIP, więc nie weryfikuje publicznego TLS,
WebSockets przez router, egzekwowania CNI ani Argo CD.

Dla OpenShift Local zainstaluj CRC od Red Hata, uzyskaj własny pull secret,
następnie przygotuj i uruchom profil OpenShift na hoście:

```bash
crc config set preset openshift
crc setup
crc start --cpus 6 --memory 13312 --disk-size 45 \
  --pull-secret-file /path/to/pull-secret
```

`crc setup` konfiguruje sieć i wirtualizację hosta; może wymagać administratora.
Zaloguj się według instrukcji CRC z osobnym kubeconfigiem. Przed zmianami potwierdź
wybrany klaster. Przygotuj osiągalne usługi danych, Secrets i konto usługi jak
powyżej, a następnie zainstaluj profil OpenShift. Nie wdrażaj zależności testowych
kind na OpenShift jako zamiennika walidacji zależności zgodnych z restrykcyjną
polityką. Po testach zatrzymaj lokalny klaster przez `crc stop`.

Zapisz digesty obrazów, rewizję charta, wersje klastra i Argo CD, przyjęty SCC,
polecenia, wyniki i logi błędów bez danych poufnych. Przed potwierdzeniem tej
ścieżki wdrożenia sprawdź:

- Migracja kończy się przed zmianą workloadów; celowy błąd migracji blokuje rollout.
  Zgodny upgrade i cofnięcie zachowują dane.
- API, worker i konsola pozostają gotowe pod zamierzoną restrykcyjną polityką;
  nawigacja frontendu i uploady nie generują błędów systemu plików tylko do odczytu.
- Działają bootstrap, logowanie, odpowiedź agenta, upload, ingestion i trwały job.
- Oba publiczne adresy HTTPS, WebSockets, limity uploadu, forwarding i izolacja sieci
  działają przez rzeczywisty ingress lub Routes.
- OIDC działa z wybranym dostawcą, wymaganymi claimami i polityką rejestracji;
  pliki sandboxa przeżywają kolejne tury, a sprzątanie działa.
- Dla Argo CD powtórz instalację, błędną migrację, upgrade i cofnięcie przez pełne
  synchronizacje; przebieg Helm nie jest walidacją GitOps.

Lokalny sukces OpenShift dotyczy danej wersji i konfiguracji. Tożsamość i sieć Azure,
sterowniki storage oraz konfiguracja Argo CD użytkownika nadal wymagają testu w jego
środowisku. Nieukończone punkty oznaczaj jako nietestowane, nie zaliczone.

### Wyniki lokalnej walidacji OpenShift { #measured-local-openshift-validation }

Bazowy test przeszedł bootstrap, logowanie, deterministyczny run agenta, upload S3,
ingest workera przez pgvector i trwałe zadanie w tle. Błąd migracji zatrzymał Helm
bez zmiany specyfikacji Deploymentów; upgrade i zgodny rollback na tym samym
schemacie przeszły. HTTPS Routes ze sprawdzaniem certyfikatów przeszły logowanie
przez BFF konsoli, cookies Secure/HttpOnly, renderowanie stron na serwerze oraz
uwierzytelniony upgrade WSS i ping. Obcy namespace nie mógł połączyć się bezpośrednio
z żadną chronioną usługą. Nie jest to pomiar całego łańcucha adresów klienta ani
maksymalnych rozmiarów uploadu.

Keycloak 26.8.2 przeszedł discovery, PKCE, walidację podpisanego tokena, jednorazową
wymianę kodu konsoli, dostęp do organizacji i unieważnienie refresh po wylogowaniu
przez Routes z TLS. Odrzucono niezweryfikowany email, niedozwoloną domenę i rejestrację
bez zaproszenia. To walidacja generycznego OIDC, nie Microsoft Entra ani Azure.
Testy renderowania serwerowego nie odtwarzają zgłoszonej ścieżki `router-cache`
i nie zastępują interaktywnego przejścia przez wszystkie ekrany.

Bazowy run potrzebował **6 CPU, 13 GiB RAM maszyny wirtualnej i dysku wirtualnego 45 GB**.
Przy minimum CRC 10.5 GB pody migracji tych fixtures nie mogły dostać zasobów.
Zaawansowane integracje testowano etapami: SDK sandboxa rezerwuje 2 GiB na workspace.
Zaplanuj dodatkowe zasoby i zapas na rolling update; 13 GiB jest wynikiem tego bazowego
testu, a nie zaleceniem produkcyjnym.

Po uruchomieniu CRC użyj Pythona z PyYAML, `oc`, `helm` i osobnego kubeconfig:

```bash
export KUBECONFIG="$HOME/.crc/machines/crc/kubeconfig"
scripts/kubernetes/run-openshift-smoke.sh
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" routes
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" oidc
```

Bazowy runner odmawia użycia istniejących namespace testowych; helper integracji
wymaga ich etykiet własności i odmawia pracy poza API CRC. Zachowuje jednorazowe
namespace i prywatne pliki tymczasowe do inspekcji. `sandbox_probe.py` wymaga osobno
przygotowanego stosu dostawcy zgodnego z konfiguracją powyżej; bazowy runner go nie
instaluje. Po inspekcji usuń tylko utworzone przez siebie namespace i zasoby dostawcy,
usuń wskazany katalog tymczasowych certyfikatów i zatrzymaj CRC. Pull secret zachowaj prywatny.

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
