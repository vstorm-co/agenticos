---
source_sha: "97048db675bf"
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
| **Klucz API organizacji** | `Authorization: Bearer aos_…` | Skryptu, klienta HTTP takiego jak Postman albo klienta MCP. Działa jako członek, który go wydał, zawężony do uprawnień, z którymi został wydany |
| **JWT** | `Authorization: Bearer <access token>` | Osoby albo czegoś, co działa w jej imieniu. Krótko żyjący, odświeżany refresh tokenem |
| **Ciasteczko sesji** | ustawiane przez konsolę | Wyłącznie przeglądarki — token jest HttpOnly i nigdy nie trafia do JavaScriptu |

### Klucze API organizacji { #organization-api-keys }

Klucz wydaje członek, w jednej organizacji, w **Ustawienia → Klucze API** (albo
przez `POST /api/v1/api-keys` z zalogowanej sesji). Niesie uprawnienia tego
członka, zawężone dwukrotnie:

- **Do uprawnień, z którymi został wydany.** Wybierz preset — *Tylko odczyt*,
  *Zasilanie bazy wiedzy*, *Pełny dostęp* — albo zaznacz uprawnienia z
  [katalogu](permissions.md). Możesz nadać tylko to, co sam masz.
- **Do tego, co wydający może zrobić teraz.** Każde żądanie odczytuje członkostwo
  wydającego na nowo, więc jego degradacja od razu zawęża każdy z jego kluczy, a
  usunięcie go z organizacji zatrzymuje wszystkie wydane przez niego klucze. Grant
  na zasobie poszerza to, co może zrobić z jednym wierszem *osoba*; nigdy nie
  poszerza klucza ponad jego uprawnienia.

Klucz jest pokazywany **raz**, w odpowiedzi, która go tworzy. Przechowywany jest
wyłącznie jego SHA-256 i nigdy nie trafia do linii logu, wpisu audytu ani treści
błędu. Listy pokazują jego prefiks (`aos_1a2b3c4d`) — i tak samo wpis audytu
nazywa klucz, który zadziałał: każdy wpis zapisany w trakcie żądania
uwierzytelnionego kluczem niesie w szczegółach `via_api_key`. Klucz może mieć datę
wygaśnięcia, a jego unieważnienie (`DELETE /api/v1/api-keys/{id}`) działa od
następnego żądania.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Warto znać dwie odmowy:

- **`403` "API keys are not accepted on this endpoint"** — klucze są przyjmowane
  wyłącznie w publicznym API: agenci, runy i zatwierdzenia, bazy wiedzy i RAG,
  skille, pliki kontekstu, artefakty, usługi ML, `/me/permissions` oraz
  członkowie, zaproszenia, grupy i ustawienia organizacji. Własne trasy konsoli,
  twoje konto, opuszczenie lub przekazanie organizacji i samo zarządzanie kluczami
  pozostają tylko dla sesji, więc wyciekły klucz nie wybije swojego następcy.
- **`401` "Invalid, expired or revoked API key"** — to samo zdanie w każdym
  przypadku, więc zły klucz nie dowiaduje się niczego o tym, jakie klucze istnieją.

Każdy klucz ma też własny limit, `RATE_LIMIT_API_KEY_PER_MINUTE` żądań na minutę
(domyślnie 600), a run albo wywołanie ML, które wykona, liczy się do tych limitów
dla klucza, a nie dla jego wydającego.

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

**Klucz API działa we własnej organizacji** i nie potrzebuje nagłówka. Wysłanie
`X-Organization-Id` razem z kluczem jest dozwolone tylko wtedy, gdy nazywa tę samą
organizację; wskazanie innej kończy się `400` z
`details.header = "X-Organization-Id"` zamiast zmiany najemcy.

**Token sesji bierze najemcę z `X-Organization-Id`.** Wywołujący, który należy do
trzech organizacji, jest w każdej z nich innym podmiotem, z inną rolą i innymi
grantami, więc wysyłaj nagłówek przy każdym żądaniu. Gdy go brakuje, żądanie
wraca do **osobistej organizacji** wywołującego — skrypt, który o nim zapomni,
działa tam, z agentami, grantami i budżetem tej organizacji, i nie dostaje żadnego
błędu. Wyślij zły, a dostaniesz odmowę, która wygląda dokładnie jak nieistniejący
zasób — celowo, żeby identyfikatorów nie dało się sondować.

## Uruchamianie agenta { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

Odpowiedź niesie identyfikator runa, wynik i status. Dwa opcjonalne pola w ciele
warto znać: `conversation_id` kontynuuje istniejący wątek, a `environment_id`
wybiera, [które środowisko](environments.md) odpowiada.

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
## Usługi ML { #the-ml-services }

Cztery usługi platformy odpowiadają samodzielnie, bez rozmowy i bez agenta za
nimi: analiza dokumentu, OCR, zamiana mowy na tekst i wykrywanie danych
osobowych. Bramkuje je `ml:invoke`, a nie `agents:run`; ich dokumentacją są
[Usługi ML](ml-services.md).

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Przykłady krok po kroku { #worked-examples }

Każdy działa z kluczem organizacji w `$AGENTICOS_KEY` i adresem API w `$BASE`.
Utwórz klucz w **Ustawienia → Klucze API** z uprawnieniami, które przykład
wymienia; konsola pokaże klucz raz.

**Wgraj dokument do bazy wiedzy i przeszukaj ją** — klucz z `collections:view` i
`collections:edit` (preset *Zasilanie bazy wiedzy*). Ingest działa w tle, więc
wyszukiwanie zaraz po wgraniu może jeszcze nie znaleźć dokumentu; jego status
pokazuje `GET /api/v1/kb/$KB_ID/documents`.

```bash
# Find the knowledge base, upload a file into it, and search it.
curl "$BASE/api/v1/kb" -H "Authorization: Bearer $AGENTICOS_KEY"

curl -X POST "$BASE/api/v1/kb/$KB_ID/documents" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -F "file=@policy.pdf"

curl -X POST "$BASE/api/v1/rag/search" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION_NAME\", \"query\": \"refund window\"}"
```

**Uruchom agenta i sprawdź, ile kosztował** — `agents:run` i `runs:view`. Odczyt
runu niesie jego status, tokeny i koszt.

```bash
RUN_ID=$(curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this week'"'"'s tickets"}' | jq -r .run_id)

curl "$BASE/api/v1/runs/$RUN_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

**Zaproś członka** — `members:manage`. Zaproszenie idzie mailem; odpowiedź niesie
jego token raz, na wypadek gdyby mail do zapraszającego nie doszedł.

```bash
curl -X POST "$BASE/api/v1/orgs/$ORG_ID/invitations" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.hire@example.com", "role": "member"}'
```

**Ponawiaj tylko to, co trafiło na limit.** `429` niesie `Retry-After`; każda inna
odmowa jest dla tego żądania ostateczna, a `401` znaczy, że klucza już nie ma —
unieważniony, wygasły albo jego wydający usunięty — więc ponawianie tylko zużywa
limit.

```python
import time

import httpx


def call(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    for _ in range(5):
        response = client.request(method, path, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(int(response.headers.get("Retry-After", "60")))
    response.raise_for_status()
    return response


client = httpx.Client(
    base_url="https://agenticos.example.com/api/v1",
    headers={"Authorization": f"Bearer {KEY}"},
)
print(call(client, "GET", "/me/permissions").json())
```

## Streaming { #streaming }

Dwa endpointy WebSocket, dla dwóch odbiorców.

- **`/api/v1/ws/agent`** — uwierzytelniony, którego używa konsola. Ramka niosąca
  `agent_id` uruchamia tego opublikowanego agenta; ramka bez niego trafia do
  ogólnego asystenta. Uwierzytelnij się subprotokołem `access_token.<token>`, gdzie
  token to JWT sesji. Klucz API organizacji jest tu odrzucany: tura na tym gnieździe
  to osoba przy klawiaturze, z jej osobistymi połączeniami. Integracje uruchamiają
  agentów przez `POST /api/v1/agents/{id}/run`.
- **`/api/v1/embed/{public_key}/ws`** — publiczny, stojący za
  [embedem](channels.md), dla odwiedzającego, który nie ma konta.

Oba strumieniują tokeny w miarę ich napływania (agent z guardrailem na wyjściu
streamuje krok po kroku, zobacz [Guardrails](reference/capabilities.md#guardrails))
i oba tworzą zwyczajny run, z tymi samymi księgami co wszystko inne.

Trzeci, **`/api/v1/ws/events`**, tylko nasłuchuje. Dzięki niemu otwarta konsola
[nadąża za zmianami wprowadzonymi gdzie indziej](console.md#changes-made-elsewhere):
uwierzytelniony tak samo, z organizacją w `?organization_id=`, wysyła jedną ramkę
JSON na każdy udany zapis przez publiczne API w tej organizacji — `resource`,
`id`, `action` (`created`, `updated` albo `deleted`), `surface` (`console`,
`api_key`, `mcp` albo `assistant`) i kto go wykonał — i tylko o wierszach, które
wywołujący może odczytać.

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

**Publiczne API ma spisaną obietnicę zgodności; reszta `/api/v1` jej nie ma.**
Trasy, które może wywołać klucz API, są w osobnym dokumencie OpenAPI pod
**`/api/v1/public/openapi.json`**, serwowanym w każdym środowisku. W ramach v1 zmiana
którejś z nich jest addytywna — nowa trasa, nowe opcjonalne pole, nowe pole
odpowiedzi albo wartość enuma — a klient musi ignorować pola odpowiedzi, których
nie zna. Usunięcie albo zmiana nazwy następuje dopiero po co najmniej 90 dniach
oznaczenia jako `deprecated` w tym dokumencie i wpisie w
[notatkach do wydań](release-notes.md); zmiana, której nie da się tak przeprowadzić,
trafia do `/api/v2`, obok v1.

Własne trasy konsoli nie mają takiej obietnicy i zmieniają się razem z konsolą;
klucz nie może ich wywołać. Biblioteki klienckiej jeszcze nie ma.

[Spec agenta](reference/spec.md) ma własną obietnicę: jest wersjonowany i idzie
tylko do przodu.

## Podsumowanie { #recap }

- **`/docs`** na deploymencie to generowana referencja; na produkcji jest
  wyłączona z założenia.
- Trzy drogi wejścia: **klucz API organizacji, JWT albo ciasteczko konsoli**.
- Klucz niesie uprawnienia wydającego **zawężone do swoich uprawnień i do jego
  obecnej roli**, jest pokazywany raz i działa wyłącznie w publicznym API.
- **Klucz działa we własnej organizacji; sesja czyta `X-Organization-Id`** i bez
  niego wraca do organizacji osobistej. Zły nagłówek wygląda jak brakujący zasób.
- Uruchomienie agenta przez HTTP to **ten sam runner** — budżet, zatwierdzenie i
  audyt obowiązują tak samo.
- **Publiczne API jest w `/api/v1/public/openapi.json`** i w ramach v1 zmienia
  się tylko addytywnie, z 90 dniami deprecjacji; SDK jeszcze nie ma.
