---
source_sha: 1fd2c8097097
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
