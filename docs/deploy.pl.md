---
source_sha: 6f2247bf1919
---

# Wdrożenie na serwer { #deploy-to-a-server }

Jeden host, Docker Compose, reverse proxy z przodu. To cała dostarczana ścieżka i
to na niej działają wdrożenia, w których ten projekt jest używany.

Nie ma manifestów Kubernetes ani jednoklikowych quickstartów dla dostawców
platform-as-a-service. To nie jest skromność co do skali. Stack to sześć
kontenerów, z których dwa trzymają stan, jeden potrafi uruchamiać własne kontenery,
a jeden jest Postgresem, który musi mieć pgvector - co już przekracza to, co
modeluje cel wdrożeniowy typu `git push`, a przewodnik udający inaczej opisywałby
wdrożenie, którego nikt nie uruchomił.

!!! tip "Przeczytaj najpierw [listę kontrolną produkcji](configuration.md#production-checklist)"

    Dziewięć ustawień ma domyślne wartości, które są w porządku na laptopie i złe
    na hoście, do którego ktoś inny może sięgnąć. `scripts/server-init.sh` poniżej
    generuje wszystkie dziewięć, więc lista kontrolna jest tym, co sprawdzasz
    potem, a nie tym, co wpisujesz.

## Czego potrzebujesz { #what-you-need }

| | |
|---|---|
| **Host** | 4 vCPU i 8 GB RAM to uruchamia. Zobacz [dobór rozmiaru](#sizing-the-host) |
| **Docker** | Engine 24+ z wtyczką Compose (2.24 lub nowszą) i twój użytkownik w grupie `docker`. Nic nie jest budowane na hoście: obrazy są ściągane z GHCR |
| **Dwie nazwy hostów** | jedna dla witryny, jedna dla API — zobacz [dlaczego dwie](#why-two-hostnames) |
| **Reverse proxy** | [Traefik](#option-a-traefik) albo [Nginx](#option-b-nginx). To on terminuje TLS |
| **Klucz OpenRouter** | każda kolekcja embeduje przez niego. Modele czatowe konfiguruje się per organizacja, w produkcie |

Host potrzebuje też otwartych portów 80 i 443, i niczego więcej. Postgres, Redis i
API Prefect nie są publikowane na żadnym interfejsie.

### Dlaczego dwie nazwy hostów { #why-two-hostnames }

Przeglądarka rozmawia z obiema. Większość wywołań idzie przez własne
serwerowe route'y frontendu, ale WebSocket czatu łączy się z API bezpośrednio,
więc API potrzebuje nazwy, którą przeglądarka potrafi rozwiązać, i własnego
certyfikatu.

`app.example.com` i `api.example.com` to ten kształt. Mogą to być dowolne dwie
nazwy; czym być nie mogą, to jedną nazwą z prefiksem ścieżki, bo ciasteczka API i
ciasteczka witryny są ograniczone do hosta.

## Dobór rozmiaru hosta { #sizing-the-host }

Zmierzone na bezczynnym wdrożeniu, nie oszacowane:

| | w spoczynku | sufit |
|---|---|---|
| `app` (2 workery uvicorna) | ~1,0 GB | 2,5 GB przy domyślnych 4 workerach |
| `db` | ~1,3 GB przy strojeniu poniżej | 2 GB |
| `prefect-runner` | 241 MiB | 1,5 GB |
| `prefect-server` | 245 MiB | 768 MB |
| `frontend` | ~300 MB | 1 GB |
| `redis` | 9 MiB | 512 MB |

Liczbą, która decyduje o hoście, jest **`UVICORN_WORKERS`**. Każdy worker to
osobny proces importujący całą aplikację — 460 MiB, spawnowany, a nie forkowany,
więc nic nie jest współdzielone. Czterech z nich to 1,9 GB, zanim dotrze
jakiekolwiek żądanie.

Dwóch workerów wystarczy zespołowi dziesięciu osób i wciąż zostawia jednego
obsługującego ruch, kiedy
[watchdog](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
zastępuje zaklinowane rodzeństwo. Jeden worker to ustawienie, którego należy
unikać: zablokowana pętla zdarzeń jest wtedy całym wdrożeniem, dopóki worker się
nie zabije.

!!! note "Baza danych jest strojona wobec własnego limitu"

    `docker-compose-prod.yml` uruchamia Postgresa z `shared_buffers=512MB` wobec
    limitu 2 GB i daje mu 512 MB `/dev/shm` — domyślne 64 MB Dockera wyczerpuje
    równoległy skan po wektorach kolekcji, raportując
    `could not resize shared memory segment`. Przesuwasz limit — przesuń strojenie
    razem z nim; są zapisane obok siebie właśnie dlatego.

## Skieruj nazwy na host { #point-the-names-at-the-host }

Dwa rekordy A, przed czymkolwiek innym. Let's Encrypt dowodzi, że kontrolujesz
nazwę, pobierając plik po HTTP stamtąd, gdzie ona się rozwiązuje, więc certyfikat
nie zostanie wystawiony, dopóki to nie jest prawdą i nie rozpropaguje się.

```
app.example.com   A   203.0.113.10
api.example.com   A   203.0.113.10
```

!!! warning "Wildcard tego za ciebie nie załatwia"

    Tam, gdzie `*.example.com` już gdzieś wskazuje — zwykle na stronę marketingową
    — obie nazwy rozwiązują się do niej. Rekord dla konkretnej nazwy bije
    wildcard, więc naprawą jest dodanie dwóch powyżej, a nie usunięcie wildcarda.

Sprawdź ze skądś, co nie jest tym hostem, bo host może mieć własną odpowiedź:

```bash
dig +short app.example.com api.example.com
```

## Wgraj to na host { #get-it-onto-the-host }

```bash
sudo install -d -o "$USER" -g "$USER" /opt/agenticos
git clone https://github.com/vstorm-co/agenticos.git /opt/agenticos
cd /opt/agenticos
bash scripts/server-init.sh
```

`server-init.sh` zapisuje `backend/.env`: generuje pięć sekretów, pyta o dwie
nazwy hostów, o adres dla Let's Encrypt i o klucz OpenRouter, a publiczne URL-e i
origin CORS wyprowadza z tego, co mu podałeś. Odmawia nadpisania istniejącego
pliku.

Klon jest miejscem, gdzie mieszkają pliki Compose i ten plik env; żaden kod z
niego nie działa. Tym, co działa, są dwa obrazy, które publikuje repozytorium.

### Obrazy { #the-images }

| | |
|---|---|
| `ghcr.io/vstorm-co/agenticos-backend` | API, runner Prefect i migracje - jeden obraz, trzy komendy |
| `ghcr.io/vstorm-co/agenticos-frontend` | Konsola |

Oba budowane są dla `linux/amd64` i `linux/arm64` przez
`.github/workflows/images.yml`. Wydanie (`v0.0.380`) publikuje `0.0.380` i
przesuwa `latest`; każdy commit na `main` publikuje `edge` i `sha-<short>`. Pliki
Compose czytają tag z `AGENTICOS_VERSION` w `backend/.env` i domyślnie biorą
`latest`.

Trzy reguły, których trzyma się workflow, każda warta poznania przed poleganiem na
tagu:

- **Publikowany jest wyłącznie commit z `main`.** Tag `v*` wypchnięty z brancha
  albo uruchomienie zlecone na branchu zostaje odrzucone, zanim cokolwiek zostanie
  zbudowane - więc `latest` nie może przejść przez granicę pull requesta.
- **Wydanie na commicie, który `main` już zbudował, nie jest budowane ponownie.**
  Jego manifest `sha-<short>` dostaje wersję i `latest` jako dodatkowe nazwy, więc
  digesty, na których host się przypiął, są dokładnie tymi, które nazywa wydanie.
- **Commitowi bez obrazów można je dać.** Uruchom workflow ręcznie z jego wejściem
  `sha` - `gh workflow run images.yml --ref main -f sha=<commit>` - a opublikuje on
  tag `sha-<short>` tego commita i nic, co się przesuwa. To ścieżka dla commita
  starszego niż workflow oraz dla takiego, którego uruchomienie zostało utracone.

!!! warning "Przypnij wydanie na hoście, na którym ci zależy"

    `AGENTICOS_VERSION=0.0.380` w `backend/.env`, tak żeby `make prod` w zły dzień
    ściągnął to, co działało wczoraj, a nie cokolwiek wydano dziś rano.
    `scripts/deploy.sh` przypina za ciebie - do tagu `sha-` commita, który wdraża -
    dokładnie na czas trwania wdrożenia.

Oba pakiety ściągają się anonimowo. Jeśli pobranie odpowiada `unauthorized`,
pakiet został ustawiony jako prywatny albo stare `docker login ghcr.io` stoi na
drodze; żadnego z tych host nie naprawi sam.

!!! danger "`backend/.env` trzyma klucz, który odpieczętowuje każde zapisane poświadczenie"

    `VAULT_MASTER_KEY` jest tym, co czyni klucze providerów organizacji, tokeny
    botów i poświadczenia MCP odczytywalnymi. Jego utrata nie zamyka ci drogi do
    produktu; czyni każdy sekret w nim nieodzyskiwalnym. Zrób kopię tego pliku
    gdzieś, skąd nie zabierze go zgubiony dysk, i rotuj przez
    [`agenticos cmd vault-rotate`](secrets.md#operations), a nie przez edycję.

Dwie opcjonalne rzeczy, o które nie pyta, obie w tym pliku: `SMTP_*`, bez którego
nie da się wysłać zaproszeń ani resetów hasła, oraz `LOGFIRE_TOKEN`, pod który idą
ślady runów agentów.

## Wybierz reverse proxy { #choose-a-reverse-proxy }

Coś musi terminować TLS i routować te dwie nazwy. Obie opcje poniżej sięgają do
tych samych kontenerów; wybierz na podstawie tego, czy już któreś uruchamiasz.

### Opcja A: Traefik { #option-a-traefik }

Krótsza ścieżka i ta, którą wybrać na hoście, który już ma Traefika: kontenery
niosą etykiety, Traefik je odkrywa, prosi o certyfikat i go odnawia. Nic do
przeładowania i żadnego drugiego pliku konfiguracji do utrzymania w zgodzie.

Jeśli Traefika jeszcze nie ma, repozytorium dostarcza jednego:
`traefik/traefik.yml` i `docker-compose-traefik.yml`, czyli entrypoint na 443 z
resolverem Let's Encrypt i 80 przekierowującym na niego.

```bash
docker network create traefik_webgateway
docker compose --env-file backend/.env -f docker-compose-traefik.yml up -d
```

Tam, gdzie Traefik **już** działa, zostaw te pliki w spokoju i skieruj
`TRAEFIK_NETWORK` na sieć, którą on obserwuje. Nakładki czytają tę nazwę, więc nic
w istniejącym proxy nie musi się zmieniać.

Potem podnieś stack z `PROXY=traefik`, co dokłada dwa pliki nakładkowe niosące
etykiety:

```bash
make prod PROXY=traefik
make prod-frontend PROXY=traefik
```

`server-init.sh` zapisał już `PROXY=traefik` do `backend/.env`, skąd czyta to
`scripts/deploy.sh` — więc późniejsze wdrożenia trzymają się proxy, z którym ten
host został postawiony, a nie tego, które założył jakiś skrypt.

!!! info "`exposedByDefault: false` wykonuje realną robotę"

    To jedno ustawienie w `traefik/traefik.yml` warte przeczytania, zanim go
    uruchomisz. Tylko `app` i `frontend` niosą `traefik.enable=true`, więc
    Postgres, Redis, serwer Prefect i demon sandboksa są nieosiągalne z niczego
    spoza hosta — a to jest właściwość *nieoznaczenia etykietą*, więc przeżywa
    dodanie przez kogoś usługi bez myślenia o proxy.

### Opcja B: Nginx { #option-b-nginx }

Dla hosta, gdzie Nginx już terminuje TLS, albo gdzie proxy w ogóle nie jest w
Dockerze. Stack publikuje oba porty na `127.0.0.1`, a Nginx sięga do nich tam:

```bash
make prod
make prod-frontend
```

`nginx/nginx.conf` jest szablonem. Dwa podstawienia, zanim cokolwiek zaserwuje:
`server_name` w każdym bloku to `${DOMAIN:-localhost}`, a Nginx tego nie rozwija —
wpisz dwie nazwy hostów ręcznie. Certyfikaty są twoje do uzyskania i odnawiania,
tak samo jak nagłówek `Strict-Transport-Security`, który backend celowo zostawia
temu, co terminuje TLS.

!!! warning "`BIND_HOST` jest ustawieniem bezpieczeństwa, a nie wygody"

    Domyślny loopback jest tym, co nadaje limitowi prób uwierzytelnienia
    jakiekolwiek znaczenie. `RATE_LIMIT_TRUST_FORWARDED_FOR` każe API liczyć próbę
    na adres, który przekazuje proxy, więc cokolwiek potrafi sięgnąć do API *poza*
    proxy, wybiera adres, na który liczone są jego próby. Ustaw
    `BIND_HOST=0.0.0.0` wyłącznie dla proxy na innej maszynie i odfiltruj ten port
    firewallem tylko do niego.

!!! warning "Frontend jest własnym projektem Compose"

    Compose nazywa projekt po katalogu, więc oba stacki nazywały się
    `agenticos` — a podniesienie frontendu raportowało wtedy pięć kontenerów
    backendu jako **osierocone**, wraz z własną podpowiedzią Compose, żeby
    uruchomić komendę ponownie z `--remove-orphans`. Posłuchanie tej rady
    zatrzymuje API, bazę danych, Redisa i obie usługi Prefect. Targety `make` i
    `scripts/deploy.sh` przekazują `-p agenticos-frontend`, więc tego ostrzeżenia
    już nie ma. Pliki Compose nie ustalają też na stałe nazw kontenerów - każdy
    projekt nazywa własne, więc dwa stacki na jednym hoście nie mogą przejąć
    swoich kontenerów nawzajem, a `deploy.sh` czeka na usługi `app` i `frontend`,
    a nie na nazwę. Wdrożenie starsze niż obie te poprawki zostaje odtworzone pod
    nowymi nazwami przy następnym `up`; niczego nie trzeba usuwać ręcznie.

    Oba projekty wciąż spotykają się na sieci o stałej nazwie - `agenticos_edge`
    na produkcji, `agenticos_backend` na serwerze deweloperskim - bo frontend
    dołącza do niej jako do sieci zewnętrznej. Host uruchamiający **dwa** stacki
    AgenticOS rozdziela `AGENTICOS_EDGE_NETWORK` i `AGENTICOS_DATA_NETWORK` (albo
    `AGENTICOS_NETWORK`) w `backend/.env` każdego stacka; w przeciwnym razie `db`,
    `redis` i `app` obu stacków rozwiązują się na jednym mostku, a żądanie może
    sięgnąć do bazy danych sąsiada.

## Uruchom to i utwórz pierwsze konto { #start-it-and-create-the-first-account }

`make prod` ściąga obrazy, uruchamia stack i wykonuje migracje - te ostatnie jako
usługę `migrate`, na którą API czeka, więc `docker compose up -d` wykonane ręcznie
na tych samych plikach robi to samo. Pierwsze pobranie to około 2 GB; kolejne to
warstwy, które się zmieniły.

Następnie utwórz organizację, właściciela i działającego agenta:

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml \
  exec -T app agenticos cmd bootstrap \
  --email you@example.com --password 'a real password' \
  --org 'Your Company' --provider anthropic --api-key sk-ant-...
```

Klucz providera tutaj jest tym, na czym działa demonstracyjny agent. Bez niego
agent zostaje utworzony i nie potrafi odpowiedzieć; każdy inny provider dodawany
jest w produkcie, per organizacja, z vaulta.

!!! tip "Sprawdź to z zewnątrz, nie z hosta"

    ```bash
    curl -fsS https://api.example.com/api/v1/health
    curl -fsSo /dev/null -w '%{http_code}\n' https://app.example.com
    ```

    Stack, który jest zdrowy na hoście i nieosiągalny z internetu, to DNS, firewall
    albo certyfikat — trzy rzeczy, których health check wewnątrz hosta nie widzi.

Potem, raz, ręcznie: zaloguj się, zaproś kogoś (co dowodzi, że działa `SMTP_*`) i
wyślij demonstracyjnemu agentowi wiadomość (co dowodzi klucza providera i
WebSocketa). Każda z tych czynności ćwiczy ścieżkę, której nic innego tutaj nie
sprawdza.

!!! info "Nagłówki bezpieczeństwa pochodzą z backendu, więc każde proxy jest pokryte"

    Content-Security-Policy, `X-Frame-Options: DENY`,
    `X-Content-Type-Options: nosniff`, `Referrer-Policy` i `Permissions-Policy`
    ustawiane są na każdej odpowiedzi — łącznie z 500 dla nieobsłużonego wyjątku,
    które budowane jest poza stosem middleware i stempluje je samo. Interaktywna
    dokumentacja API zrzuca wyłącznie CSP, bo Swagger ładuje zasoby, których
    restrykcyjna polityka zabrania.

    **HSTS jest celowo pozostawione proxy**, czyli temu, gdzie terminuje TLS.
    Proxy ustawiające własne CSP powinno być co najmniej tak restrykcyjne jak to.

### Włączanie sandboksa { #turning-the-sandbox-on }

Usługa uruchamiająca kod agenta stoi za profilem Compose, bo to jedyny kontener
trzymający socket Dockera, a podmontowanie go na współdzielonym hoście powinno być
decyzją, a nie wartością domyślną. Trzy rzeczy, raz:

```bash
make sandbox-token                       # writes SANDBOXD_TOKEN to backend/.env
sudo mkdir -p /var/lib/agenticos/sandbox-workspaces
sudo chown 10001:10001 /var/lib/agenticos/sandbox-workspaces
```

Potem wdrożenie go podnosi: `scripts/deploy.sh` przekazuje `--profile sandbox`,
gdy `SANDBOXD_TOKEN` w `backend/.env` ma wartość, więc to sam host mówi, czy go
uruchamia. Eksportuje też `DOCKER_GID` odczytane z socketu — każdy plik Compose
tutaj wstawia je do `group_add` sandboksa, a jego domyślne `0` jest właścicielem
socketu w prawie żadnej dystrybucji Linuksa. Nic więcej w `.env` nie jest
potrzebne: backend sięga do demona przez *połączenie* sandboksa, które ktoś tworzy
w konsoli, a `http://sandboxd:8080` jest rozpoznawane jako własne tego
deploymentu.

!!! warning "Profil, o którym Compose nie wie, to usługa, którą Compose zatrzymuje"

    `up -d` na tym samym projekcie bez `--profile sandbox` nie zostawia sandboksa
    w spokoju — zatrzymuje go. Więc hostowi, który uruchomił go ręcznie, zabierało
    go kolejne wdrożenie, a uruchamianie kodu agenta psuło się z powodów zupełnie
    niezwiązanych z wdrożeniem, które to spowodowało (#1506). Dlatego skrypt czyta
    token, zamiast przyjmować flagę.

## Wdrażanie zmiany { #deploying-a-change }

### Ręcznie { #by-hand }

```bash
remote=$(ssh you@your-host 'mktemp -t agenticos-deploy.XXXXXX')
ssh you@your-host "cat > $remote" < scripts/deploy.sh
ssh you@your-host "trap 'rm -f $remote' EXIT; bash $remote <commit-sha>"
```

`scripts/deploy.sh` pobiera ten commit, czeka na obrazy, które CI dla niego
opublikowało (`sha-<short>`, zwykle już tam są), ściąga je, restartuje i czeka, aż
oba kontenery zgłoszą się jako zdrowe, zanim zwróci kod niezerowy albo nie.
Przyjmuje **commit**, a nie branch, więc tym, co jest wdrożone, jest to, co zostało
zrecenzowane, a nie to, dokąd `main` przesunął się od tamtej pory - a tym, co
działa, jest bajt w bajt to, co zbudowało CI, na hoście, który nigdy nie potrzebuje
łańcucha narzędzi.

!!! warning "Skopiuj go na host, a potem uruchom — nie wpychaj go do `bash -s`"

    Pod `bash -s` skrypt jest własnym standardowym wejściem powłoki, a pierwsza
    komenda w nim, która czyta stdin, pochłania resztę. `docker compose exec`
    przekazuje stdin do kontenera nawet z `-T`, więc migracja zjadła wszystko
    poniżej siebie, bash doszedł do EOF, a wdrożenie zakończyło się **0**, nigdy
    nie zbudowawszy frontendu ani nie czekając na żaden kontener. Witryna leżała, a
    wdrożenie było zielone ([#1488](https://github.com/vstorm-co/agenticos/issues/1488)).

    Dwa połączenia zamiast jednego są tym, co odbiera procedurze możliwość obcięcia
    samej siebie.

To nie jest wdrożenie bez przestoju. Compose odtwarza kontenery, których obraz się
zmienił, więc witryna jest niedostępna przez te kilka sekund, które to zajmuje.

### Z GitHuba, z zatwierdzeniem { #from-github-with-an-approval }

`.github/workflows/deploy.yml` oferuje każdy merge do `main` do wdrożenia i czeka,
aż ktoś to zatwierdzi. Ta bramka jest **ustawieniem repozytorium, a nie krokiem w
pliku** — bez niej workflow wdraża każdy merge bez nadzoru.

Skonfiguruj to raz:

1. **Settings → Environments → New environment**, nazwane `production`.
2. Zaznacz **Required reviewers** i dodaj tych, którzy mogą zatwierdzać. To jest ta
   bramka.
3. Dodaj zmienne tego środowiska: `SITE_URL`, `API_URL` oraz `APP_DIR`, jeśli
   checkout nie jest w `/opt/agenticos`.
4. Dodaj sekrety wymienione niżej.

!!! warning "Anuluj wdrożenie, którego nie zamierzasz zatwierdzić"

    Każde uruchomienie dzieli grupę współbieżności `deploy-production`, a
    uruchomienie siedzące przy bramce zatwierdzenia ją trzyma. Nie wygasa samo z
    siebie — GitHub anuluje takie, na które nie zareagowano, po 30 dniach — więc
    dopóki ktoś go nie zatwierdzi albo nie anuluje, późniejsze merge'e stoją w
    kolejce za decyzją, której nikt nie podejmie, a serwer dalej uruchamia to, co
    zostało wdrożone ostatnio.

    Więc wdrożenie, przeciw któremu się zdecydowałeś, anulujesz, a nie zostawiasz.
    Jedno zostawione w oczekiwaniu na nieaktualny commit zablokowało tutaj trzy
    późniejsze uruchomienia, zanim ktokolwiek zauważył kolejkę, a nie uruchomienia.

| Sekret | Co |
|---|---|
| `DEPLOY_HOST` | Adres hosta |
| `DEPLOY_USER` | Konto, do którego należy checkout |
| `DEPLOY_SSH_KEY` | Klucz prywatny, którego połowa publiczna jest w `authorized_keys` tego konta |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan your-host`, uruchomione skądś, komu ufasz |

Wygeneruj klucz do tego i do niczego więcej:

```bash
ssh-keygen -t ed25519 -N '' -C 'github-actions-deploy' -f deploy_key
ssh-copy-id -f -i deploy_key.pub you@your-host
ssh-keyscan your-host                    # → DEPLOY_KNOWN_HOSTS
cat deploy_key                           # → DEPLOY_SSH_KEY, then delete it locally
```

!!! note "Klucz hosta jest sekretem, a nie `ssh-keyscan` w czasie wdrożenia"

    Skanowanie w czasie wdrożenia ufa temu, co odpowiada pod tym adresem, czyli
    dokładnie temu, czemu klucz hosta ma zapobiegać. Zeskanuj raz, skądś, komu
    ufasz, i zapisz odpowiedź.

Pojawia się wtedy uruchomienie z **Review deployments**; zatwierdzenie go
uruchamia job. `workflow_dispatch` uruchamia ten sam job wobec wskazanego przez
ciebie refa, i tak właśnie robi się rollback, a przechodzi on przez to samo
zatwierdzenie.

## Kopie zapasowe { #backups }

Liczy się jeden wolumen i nie jest oczywiste który:

| Wolumen | Trzyma | Kopia |
|---|---|---|
| `postgres_data` | wszystko — agentów, konwersacje, zapieczętowane poświadczenia | **tak** |
| `media_data` | wgrane pliki, przed ingestią | tak |
| `redis_data` | kubełki limitów i cache | nie, wszystko odtwarzalne |
| `prefect_data` | historia uruchomień flow | nie |

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "agenticos-$(date +%F).dump"
```

Identyfikatory pochodzą z własnego środowiska kontenera, zamiast być wypisane,
ponieważ oba są ustawieniami: wdrożenie, które zmieniło którekolwiek z nich,
dostałoby w przeciwnym razie pusty plik i błąd, którego nikt nie przeczyta po
drodze.

!!! danger "Kopia bazy danych bez `backend/.env` nie jest kopią zapasową"

    Poświadczenia w niej są zapieczętowane `VAULT_MASTER_KEY`. Odtworzone obok
    innego klucza, każdy klucz providera, token bota i poświadczenie MCP w zrzucie
    są nie do odczytania — a produkt powie ci to, jedną odmową na raz.

## Wycofywanie zmian { #rolling-back }

| | Jak |
|---|---|
| **Kod** | Wdróż poprzedni commit: `workflow_dispatch` z jego sha albo `scripts/deploy.sh`. Obrazy wciąż są w rejestrze, więc to pobranie, a nie budowanie. Commit bez obrazów `sha-<short>` - starszy niż `images.yml` albo taki, którego uruchomienie zaginęło - publikuje się najpierw przez `gh workflow run images.yml --ref main -f sha=<commit>`; wdrożenie nazywa tę komendę, kiedy przestaje czekać |
| **Schemat** | `agenticos db downgrade --revision=-1`, a potem wdróż kod, który do niego pasuje |
| **Dane** | `pg_restore` ze zrzutu, a potem sprawdź migrację, której oczekuje kod |

Wycofanie kodu **przez migrację jest decyzją, a nie komendą**. Stary kod spotyka
schemat, którego nigdy nie widział; czy to zadziała, zależy od migracji. Przeczytaj
ją, zanim cokolwiek założysz.

## Podsumowanie { #recap }

- **Jeden host, Compose, proxy z przodu.** Siedem kontenerów - jeden z nich
  wykonuje migracje i kończy działanie - dwa z nich ze stanem, każdy ściągnięty -
  nic nie jest budowane na hoście. Przypnij `AGENTICOS_VERSION`.
- **`UVICORN_WORKERS` decyduje, ile kosztuje host.** 460 MiB na workera, nic
  współdzielonego. Dwóch dla zespołu, czterech dla prawdziwego ruchu.
- **DNS przed wszystkim.** Żaden certyfikat nie zostaje wystawiony, dopóki nazwy
  nie rozwiązują się do hosta.
- **Zatwierdzenie jest ustawieniem repozytorium**, a nie linią w workflow. Bez
  wymaganych recenzentów na środowisku `production` każdy merge wdraża się sam.
- **Rób kopię `postgres_data` i `backend/.env` razem.** Jedno bez drugiego nie jest
  odtworzeniem.
