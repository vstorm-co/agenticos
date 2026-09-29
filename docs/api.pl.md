---
source_sha: "10772d5fcdb4"
---

# API HTTP { #the-http-api }

Wszystko, co robi konsola, robi przez to API. Nie ma prywatnej powierzchni: te
same endpointy są dostępne dla ciebie.

Interaktywna referencja jest generowana z kodu i serwowana przez sam deployment
pod **`/docs`**, ze schematem pod `/api/v1/openapi.json`. Oba są włączone w
środowisku deweloperskim i wyłączone na produkcji — decyduje `ENVIRONMENT`, więc
produkcyjny deployment nie publikuje własnej listy tras.

## Uwierzytelnianie { #authenticating }

Trzy drogi wejścia, dla trzech różnych wywołujących.

| | Nagłówek | Dla |
|---|---|---|
| **JWT** | `Authorization: Bearer <access token>` | Osoby albo czegoś, co działa w jej imieniu. Krótko żyjący, odświeżany refresh tokenem |
| **Klucz API** | `X-API-Key: <key>` | Komunikacji usługa–usługa. Nie stoi za nim żaden użytkownik |
| **Ciasteczko sesji** | ustawiane przez konsolę | Wyłącznie przeglądarki — token jest HttpOnly i nigdy nie trafia do JavaScriptu |

Klucze są porównywane przez `secrets.compare_digest`, nigdy przez `==`, a klucz
jest przechowywany tak samo jak
[każde inne poświadczenie](secrets.md).

### Sesje i unieważnianie { #sessions-and-revocation }

Access token JWT jest związany z sesją, którą otworzyło logowanie — identyfikator
sesji podróżuje wewnątrz tokena. Wylogowanie się wszędzie (`DELETE /sessions`)
dezaktywuje te sesje, a związany token zostaje wtedy odrzucony przy następnym
użyciu, zamiast dożyć swoich kilku pozostałych minut. Sięga to również otwartego
WebSocketu czatu: następna ramka na unieważnionej sesji zamyka gniazdo, a nie
tylko następne żądanie HTTP.

Odświeżenie nie zaczyna nowej sesji — refresh token rotuje w miejscu, a access
token dalej nazywa tę samą sesję — więc długo żyjące połączenie nie zostaje
przerwane przez rutynowe odświeżenie.

## Nagłówek organizacji { #the-organization-header }

**`X-Organization-Id` podróżuje z każdym żądaniem** i nie jest opcjonalną
ozdobą: decyduje, w którym najemcy działa wywołanie.

Wywołujący, który należy do trzech organizacji, jest w każdej z nich innym
podmiotem, z inną rolą i innymi grantami. Pomiń nagłówek, a żądanie nie ma
najemcy, w którym miałoby działać; wyślij zły, a dostaniesz odmowę, która wygląda
dokładnie jak nieistniejący zasób — celowo, żeby identyfikatorów nie dało się
sondować.

## Uruchamianie agenta { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

Odpowiedź niesie identyfikator runa, wynik i status. Dwa opcjonalne pola w ciele
warto znać: `conversation_id` kontynuuje istniejący wątek, a `environment_id`
wybiera, [które środowisko](environments.md) odpowiada. Agent z
[formatem odpowiedzi](concepts.md#spec) odpowiada obiektem: jest on w `structured`,
już sprawdzony względem `output_schema` agenta, a `output` pokazuje ten sam obiekt
jako blok JSON.

!!! info "Wywołujący API nie może obejść nadzoru"

    Ten endpoint przechodzi przez ten sam runner co konsola, Slack i widget. Run
    zostaje zapisany, budżet jest sprawdzany przed żądaniem do modelu, obowiązuje
    bramka zatwierdzeń, a koszt ląduje na tym samym dashboardzie.

    Na tym polega jeden runner i dlatego nie ma "szybkiej ścieżki", która by go
    omijała.

Ta trasa niesie **limit tempa, a nie bramkę uprawnień**. Uprawnienie jest
rozstrzygane wewnątrz serwisu, wobec grantów tego konkretnego agenta — bramka
rolowa na trasie per zasób [nie widzi ich](permissions.md).

`PATCH /api/v1/agents/{id}/metadata` ustawia **categories** i **tags** agenta
ciałem w rodzaju `{"categories": [...], "tags": [...]}`, gdzie pusta lista
czyści dany aspekt. Wartości są normalizowane — przycinane, ze scaloną spacją,
zwinięte wielkością liter i odduplikowane — oraz ograniczone: najwyżej 10
categories i 20 tagów, każdy najwyżej 32 znaki, a dłuższy element odpowiada
`422`. Podobnie jak trasa run, nie niesie bramki rolowej; rozstrzyga
uwzględniające granty sprawdzenie `agents:edit` wewnątrz serwisu, więc viewer z
grantem edycji na jednym agencie może go otagować.

`GET /api/v1/agents` filtruje ten katalog powtarzalnymi parametrami zapytania
`category` i `tag`: wartości łączą się przez **OR w obrębie aspektu** i **AND
między aspektami**, dopasowywane bez względu na wielkość liter (wartość zapytania
zwija się tak jak zapisana, a pusta wartość jest pomijana). Filtr tylko zawęża
to, co i tak już widzisz — nigdy nie przekracza granicy najemcy ani grantu.

Odpowiedź niesie też `categories` i `tags`: każdą odrębną etykietę na agentach,
które możesz wylistować, niezależnie od filtra i strony — wybory, które podaje menu
filtra. Prywatny agent, którego nie widzisz, nie dodaje żadnej.

## Uruchamianie workflowu { #running-a-workflow }

```bash
curl -X POST "$BASE/api/v1/workflow-runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "'"$WORKFLOW_ID"'", "input": {"question": "How long do refunds take?"}, "deadline_seconds": 3600}'
```

To uruchamia run opublikowanej wersji workflowu i od razu odpowiada `201`;
węzły działają w tle. `input` to to, co przekazuje dalej wyzwalacz [`core.input`](reference/workflow-nodes.md#core-input) grafu, najwyżej `WORKFLOW_RUN_MAX_INPUT_BYTES` jako JSON (powyżej `413`). Tutaj uruchamia się tylko wersja, która startuje od tego wyzwalacza albo bez żadnego: każda inna odpowiada `409
WORKFLOW_TRIGGER_MISMATCH`, bo uruchamia ją webhook, harmonogram, wiadomość na czacie albo rekord tabeli. `"mode": "test"` uruchamia zamiast tego bieżący draft, od dowolnego wyzwalacza, i
wymaga `workflows:edit`.

`deadline_seconds` (do trzydziestu dni) ustawia termin
sprawdzany za każdym razem, gdy węzeł ma zostać wysłany: pierwszy węzeł gotowy
po jego upływie kończy run błędem `DEADLINE_EXCEEDED`, a węzeł, który już działa,
albo run czekający na zatwierdzenie nie są przez niego przerywane. Trasa ma limit żądań na wywołującego, tak jak trasa runów agenta, i
po przekroczeniu limitu odpowiada `429` z `Retry-After`.

`GET /api/v1/workflow-runs/{id}` zwraca status runa, `spent_cost`, `error` oraz, gdy jego węzeł [`core.output`](reference/workflow-nodes.md#core-output) już się wykonał, `output`, a
`POST /api/v1/workflow-runs/{id}/cancel` go zatrzymuje. `GET
/api/v1/workflow-runs/{id}/events?after=<cursor>` zwraca strumień zdarzeń runa
od najstarszego, z `next_cursor` do odesłania jako `after`: pozostaje taki sam,
dopóki nie ma nic nowszego, więc odpytywanie z nim śledzi trwający run. Kto może
robić każdą z tych rzeczy, opisuje strona [Uprawnienia](permissions.md#workflow-runs).

`GET /api/v1/workflow-runs/{id}/nodes` wymienia każdy krok, który wykonał run,
łącznie z iteracjami pętli, każdy z jego `scope_path`, statusem, próbami, kosztem i
typowanym błędem, którym ostatnio się zakończył, a `GET
/api/v1/workflow-runs/{id}/graph` zwraca graf, który run wykonuje: graf jego wersji
albo snapshot draftu runa testowego.

### Śledzenie runa przez WebSocket { #following-a-run-over-a-websocket }

`/api/v1/ws/workflow-runs?organization_id=<org>` uwierzytelnia się tak jak gniazdo
czatu, z tokenem dostępu jako subprotokołem `access_token.<token>`. Wyślij
`{"type": "start", "workflow_id": ..., "input": {...}}`, żeby uruchomić run, albo
`{"type": "attach", "run_id": ..., "after": <cursor>}`, żeby śledzić istniejący.
Serwer wysyła `{"type": "run", "run": {...}}`, gdy zaczyna śledzić, i ponownie, gdy
run się kończy, oraz `{"type": "event", "event": {...}, "cursor": ...}` dla każdego
zdarzenia pomiędzy. Odrzucona ramka dostaje `{"type": "error", "code": ...,
"message": ...}`, a unieważniona sesja zamyka gniazdo kodem `4001`. Jedno gniazdo
śledzi jeden run; nowa ramka zastępuje run, który śledziło. Ramka `start` zużywa ten
sam limit na minutę co `POST /workflow-runs`, a po jego przekroczeniu dostaje
`RATE_LIMIT_EXCEEDED`.

### Webhooki i harmonogramy { #workflow-webhooks-and-schedules }

Workflow, którego węzłem wyzwalacza jest webhook albo harmonogram, dostaje swoją
ekspozycję przy publikacji tej wersji, a odpowiedź na publikację niesie ją jako
`exposure`. Sekret do podpisu webhooka jest w `webhook_secret` publikacji, która
pierwszy raz go włącza, i nigdzie indziej. `GET /api/v1/workflows/{id}/exposure`
odczytuje ją z powrotem albo zwraca `null` dla workflow, który startuje inaczej.
`PATCH .../exposures/{exposure_id}` z `{"is_active": false}` ją wstrzymuje, a `POST
.../exposures/{exposure_id}/rotate-secret` wymienia sekret webhooka i raz zwraca
nowy. Oba wymagają `workflows:edit` i `workflows:run` na workflow. `webhook_url`
webhooka to adres, na który dostarcza nadawca:

```bash
BODY='{"lead": 42}'
SIGNATURE="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"
curl -X POST "$WEBHOOK_URL" \
  -H "X-Signature-256: $SIGNATURE" \
  -H "X-Delivery-Id: lead-42" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

Odpowiada `202` z `{"run_id": ..., "duplicate": false}`, gdy tylko run zostanie
przyjęty, nigdy nie czekając na sam run. Id dostarczenia, które już przyjęto,
odpowiada `"duplicate": true` z id pierwszego runa. Podpis, który się nie weryfikuje,
to `403`, dostarczenie bez id albo z treścią, która nie jest obiektem JSON, to `400`,
a wstrzymany albo nieznany webhook to `404`.

## Praca z tabelami { #working-with-tables }

`values` rekordu są kluczowane id kolumn; `GET /api/v1/tables/{id}` wymienia kolumny.
Każdy zapis przyjmuje `Idempotency-Key`: ponowienie z tym samym kluczem i treścią
odpowiada wynikiem pierwszego zapisu i `Idempotent-Replayed: true` zamiast zapisywać
znowu, a ten sam klucz z inną treścią to `422`.

```bash
curl -X POST "$BASE/api/v1/tables/$TABLE_ID/records" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Idempotency-Key: lead-ada-2026-09-29" \
  -H "Content-Type: application/json" \
  -d '{"external_id": "ada@example.com", "values": {"'"$EMAIL_COLUMN"'": "ada@example.com"}}'
```

`PATCH .../records/{record_id}` zmienia część komórek i wymaga `expected_revision`,
którą ostatnio odczytałeś; nieaktualna to `409 REVISION_CONFLICT`. `PUT
.../records/by-external-id/{external_id}` tworzy rekord albo go aktualizuje, a gdy już
istnieje, wymaga `expected_revision`. `POST .../records/query` filtruje i sortuje po
jednej stronie naraz.

Workflow, którego węzłem wyzwalacza jest **New table record**, po publikacji
uruchamia się dla każdego rekordu dodanego do jego tabeli. `GET .../triggers`
wymienia workflow, które startują od tabeli, `PATCH .../triggers/{trigger_id}` z
`{"is_active": false}` wstrzymuje jeden, a `GET .../triggers/{trigger_id}/admissions`
wymienia, co zdecydował o każdym rekordzie. Zobacz [Wyzwalacze](virtual-tables.md#triggers).

## Usługi ML { #the-ml-services }

Cztery usługi platformy odpowiadają samodzielnie, bez rozmowy i bez agenta za
nimi: analiza dokumentu, OCR, zamiana mowy na tekst i wykrywanie danych
osobowych. Bramkuje je `ml:invoke`, a nie `agents:run`; ich dokumentacją są
[Usługi ML](ml-services.md).

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Streaming { #streaming }

Dwa endpointy WebSocket, dla dwóch odbiorców.

- **`/api/v1/ws/agent`** — uwierzytelniony, którego używa konsola. Ramka niosąca
  `agent_id` uruchamia tego opublikowanego agenta; ramka bez niego trafia do
  ogólnego asystenta.
- **`/api/v1/embed/{public_key}/ws`** — publiczny, stojący za
  [embedem](channels.md), dla odwiedzającego, który nie ma konta.

Oba strumieniują tokeny w miarę ich napływania i oba tworzą zwyczajny run, z
tymi samymi księgami co wszystko inne.

## Błędy { #errors }

Jedna koperta, wszędzie:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "..." }
  }
}
```

`details` niesie wartości, a nie wiersze, więc nazywa pole wyjaśniające odmowę i
nigdy nie rekord bazy danych. Gdy odmowa dotyczy czegoś, co wywołujący przesłał,
`details.fields` jest listą `{field, message}` — a to właśnie pozwala formularzowi
oznaczyć pole zamiast pokazywać zdanie, którego ktoś musi szukać, przeglądając
stronę ponownie.

Odpowiedź `401` niesie `WWW-Authenticate: Bearer`. Odczyt spoza najemcy
odpowiada `404`, a nie `403`, z podanego wyżej powodu.

## Konwencje { #conventions }

| | |
|---|---|
| Prefiks | `/api/v1` |
| Tworzenie | `POST`, `201` |
| Częściowa aktualizacja | `PATCH` |
| Usuwanie | `DELETE`, `204`, bez ciała |
| Stronicowanie | parametry zapytania `skip` (≥ 0) i `limit` (1–100); odpowiedzi listowe niosą `items` i `total` |
| Ścieżki | kebab-case |

## Stabilność, szczerze { #stability-honestly }

**Nie ma jeszcze opublikowanej obietnicy kompatybilności ani biblioteki
klienckiej.** API jest publiczne od pierwszego commita, a kontrakt wersjonowania
to praca z [roadmapy](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md)
(R10).

W praktyce kształty były stabilne, a prefiks `/api/v1` oznacza, że zmiana
łamiąca zgodność wylądowałaby obok obecnej, a nie na niej — ale dopóki nie jest
to spisane, traktuj to jak to, czym jest: jako API, wobec którego warto przypiąć
testy swojej integracji.

Jedynym formatem, który *faktycznie* niesie obietnicę, jest
[spec agenta](reference/spec.md) — wersjonowany i poruszający się tylko do
przodu.

## Podsumowanie { #recap }

- **`/docs`** na deploymencie to generowana referencja; na produkcji jest
  wyłączona z założenia.
- Trzy drogi wejścia: **JWT, `X-API-Key` albo ciasteczko konsoli**.
- **`X-Organization-Id` decyduje o najemcy** przy każdym żądaniu, a zły nagłówek
  wygląda jak brakujący zasób.
- Uruchomienie agenta przez HTTP to **ten sam runner** — budżet, zatwierdzenie i
  audyt obowiązują tak samo.
- **Jeszcze bez obietnicy kompatybilności i bez SDK** (R10); spec agenta jest
  jedynym wersjonowanym formatem.
