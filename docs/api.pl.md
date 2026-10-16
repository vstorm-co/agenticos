---
source_sha: "ba34a88c524a"
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

Oba strumieniują tokeny w miarę ich napływania (agent z guardrailem na wyjściu
streamuje krok po kroku, zobacz [Guardrails](reference/capabilities.md#guardrails))
i oba tworzą zwyczajny run, z tymi samymi księgami co wszystko inne.

## Rozmowy głosowe { #voice-calls }

[Rozmowa głosowa](voice.md) ma własny socket, bo rozmowa nie jest pętlą tur:
**`/api/v1/ws/voice`** dla członka i
**`/api/v1/embed/{public_key}/voice/ws`** dla odwiedzającego w widgecie albo na
hostowanej stronie ([wpuszczanie](channels.md#the-call-socket)). Oba mówią tymi
samymi ramkami, zdefiniowanymi w `backend/app/schemas/voice.py`.

Socket konsoli uwierzytelnia się tak jak `/ws/agent`: token jako wpis
`Sec-WebSocket-Protocol` `access_token.<JWT>` (albo ciasteczko z tego samego
originu), nigdy w query stringu, a organizację jako `?organization_id=`.
Zamyka się z kodem `4001` bez ważnej sesji i z `4003`, gdy wywołujący nie jest
członkiem. Socket embeda zamyka się z `4029` po przekroczeniu rate limitu
i z `4003` przy każdej odmowie dotyczącej embeda. Każdy heartbeat sprawdza
sesję ponownie, więc rozmowa nie przetrwa wylogowania.

**Klient wysyła** ramki JSON, a przez relay także binarne audio:

| Ramka | Pola | Kiedy |
|---|---|---|
| `start` | `agent_id`, `conversation_id`, `sdp_offer` (WebRTC), `resume_of` i `resume_token` (ponowne połączenie), `context` (zmienne embeda) | Najpierw, w ciągu 10 sekund |
| `approval` | `id`, `decision` (`approve` albo `deny`) | Rozstrzygnięcie zatwierdzenia, na które czeka rozmowa |
| `mute` | `muted` | Relay: mikrofon wyciszony |
| `played` | `bytes` | Relay: ile audio agenta zostało odtworzone |
| `end` | - | Rozłączenie się |
| *binarna* | 16-bitowy PCM z częstotliwością wejściową modelu | Relay: audio dzwoniącego |

**Serwer wysyła:**

| Ramka | Pola | Znaczy |
|---|---|---|
| `answer` | `sdp` | WebRTC: odpowiedź providera dla połączenia peer przeglądarki |
| `ready` | `call_id`, `run_id`, `conversation_id`, `transport`, `input_sample_rate`, `output_sample_rate`, `cap_seconds`, `minutes_left`, `resume_token` | Rozmowa jest zestawiona. `resume_token` jest wysyłany tylko tutaj i tylko temu dzwoniącemu; ponowne połączenie odsyła go z powrotem |
| `state` | `state`: `connecting`, `listening`, `user_speaking`, `thinking`, `agent_speaking`, `interrupted`, `tool_running`, `awaiting_approval` | Kto mówi albo co robi agent |
| `caption` | `role`, `turn_id`, `part` oraz jedno z: `delta` (dopisz), `text` (zastąp dotychczasowym sprawdzonym tekstem) albo `final` | Napis na żywo |
| `turn_saved` | `message` | Zakończona tura, jako wiadomość, w której została zapisana; zastępuje napisy niosące jej `turn_id` |
| `tool` | `name`, `status` (`running` albo `done`) | Narzędzie, które agent uruchamia |
| `approval_required` | `id`, `tool`, `args`, `said`, `timeout_seconds` | Zatwierdzenie dla osoby w rozmowie: dokładne argumenty i to, co według transkrypcji powiedziała |
| `approval_unavailable` | `tool`, `args` | Wywołanie narzędzia, którego ten dzwoniący nie może zatwierdzić głosem |
| `approval_settled` | `id`, `outcome` (`approved`, `denied` albo `expired`) | Jak zakończyło się zatwierdzenie |
| `notice` | `kind`, `message` (opcjonalne) | Coś do powiedzenia słowami: trafienie guardraila, osiągany limit |
| `limit` | `seconds_left` | Czas rozmowy prawie się skończył |
| `clear_playback` | - | Relay: odrzuć zakolejkowane audio agenta |
| `ended` | `reason`, `message` | Rozmowa się skończyła |
| *binarna* | 16-bitowy PCM z częstotliwością wyjściową modelu | Relay: audio agenta |

**Odwiedzający widget lub hostowaną stronę dowiaduje się mniej.** Jego `ready`
nie zawiera `run_id`, a `minutes_left` przychodzi jako `null`. `cap_seconds` to
limit samej rozmowy - najdłuższa rozmowa organizacji, agenta albo to, co
zostało ze wznawianej rozmowy - a nie limit zdradzający minuty organizacji.
Serwer i tak kończy rozmowę na prawdziwym limicie. Ramki narzędzi podlegają
przełącznikom embeda `show_tool_steps` i `show_tool_results`, tak jak
odpowiedź pisana. Bez kroków narzędzi nie jest wysyłana żadna ramka `tool`, a
`tool_running` przychodzi jako `thinking`. Bez wyników narzędzi
`approval_unavailable` przychodzi z pustym `args`. Niezależnie od przełączników
`turn_saved` odwiedzającego zawiera tylko `id`, `role`, `content`,
`interrupted` i `turn_id` wiadomości: nigdy identyfikatorów runa, agenta ani
wersji, kosztu ani wywołań narzędzi.

**Ponowne połączenie musi udowodnić, że rozmowa należy do niego.** `start` z
`resume_of` musi zawierać także `resume_token` z ramki `ready` tamtego
połączenia. Bez niego albo z błędnym ponowne połączenie jest odrzucane jako
`resume_refused`, a wskazana rozmowa pozostaje nietknięta. Serwer przechowuje
tylko skrót tokena. Rozmowa złożona już z 20 połączeń nie jest wznawiana
ponownie: jej kolejne ponowne połączenie też jest odrzucane jako
`resume_refused`.

Socket, który w ciągu 10 sekund nie wyśle `start`, dostaje `ended` z `no_start`.
Rozmowa, która się nie rozpocznie, odpowiada `ended` ze stałym `reason`:
`voice_off`, `no_agent`, `forbidden`, `not_configured`, `bad_offer`,
`data_channel`, `resume_refused`, `minutes_exhausted`, `call_limit`,
`not_priced`, `budget`, `busy` albo `line_busy`, z `message`, który można
bezpiecznie pokazać. Start, który nie powiedzie się z jakiegokolwiek innego
powodu, odpowiada `ended` z `error`. Odwiedzający odrzucony jako
`not_configured`, `not_priced`, `minutes_exhausted` albo `budget` dostaje ten
sam powód z komunikatem "Calls are not available right now.", bo pełny
komunikat jest pisany dla operatora agenta. Rozmowa w zarchiwizowanej
konwersacji jest odrzucana jako `forbidden`, tak jak wiadomość pisana do niej.

Rozmowa, która trwała, kończy się z `user`, `time_limit`, `budget`, `minutes`,
`disconnected`, `revoked`, `shutdown` albo `error`. Kończy się z `minutes`, gdy
jej limit wyznaczyły minuty miesiąca, a z `time_limit`, gdy wyznaczyło go
ustawienie najdłuższej rozmowy. Rozmowa odwiedzającego kończy się z `revoked`, gdy jej
embed zostanie wstrzymany, będzie miał wyłączone rozmowy albo zostanie
skierowany na innego agenta. Żadna ramka nigdy nie niesie poświadczeń
providera.

Idą z tym cztery route'y HTTP:

| Route | Bramka | Odpowiada |
|---|---|---|
| `GET /api/v1/agents/{agent_id}/voice?surface=web` | `agents:run` na tym agencie, łącznie z grantem; w przeciwnym razie `404` | Czy rozmowa by się rozpoczęła, dlaczego nie, transport, najdłuższa rozmowa i pozostałe minuty. `surface=embed` pyta o widget albo hostowaną stronę |
| `GET /api/v1/providers/realtime-models` | `agents:view` | Katalog realtime, z którego wybiera sekcja głosu |
| `GET /api/v1/voice/usage?start=…&end=…` | `runs:view` | Sekundy rozmów i liczba rozmów dla rozmów rozpoczętych w chwili `start` lub później i przed `end`, według agenta (rozmowy usuniętego agenta jako jeden wiersz bez id i nazwy), oraz sekundy z tego miesiąca wobec miesięcznych minut organizacji. `end`, który nie jest późniejszy niż `start`, jest odrzucany z `422` |
| `GET /api/v1/runs?modality=voice` | `runs:view` | Tylko rozmowy (`text` tylko dla wpisanych runów); rozmowa, która połączyła się ponownie, to jeden wiersz z `voice_chain`, ze wszystkimi połączeniami zsumowanymi |

Zatwierdzenie należące do trwającej rozmowy jest rozstrzygane w rozmowie:
`POST /api/v1/approvals/{id}` odrzuca je z `400`.

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
