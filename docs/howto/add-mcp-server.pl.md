---
source_sha: 34c34d991836
---

# Dodaj serwer do katalogu MCP { #add-a-server-to-the-mcp-catalog }

[Katalog](../mcp.md#the-catalog) jest tym, co czyni selektor połączeń użytecznym
zamiast pustego pola na URL. Dodanie wpisu to dane, a nie kod: jeden obiekt w
`backend/app/core/catalog/mcp_servers.json`.

!!! tip "Nie musisz tego robić, żeby użyć serwera"

    Każdy serwer MCP osiągalny po URL-u łączy się przez wpis *Custom server*, a
    jego narzędzia są introspekcjonowane przy połączeniu. Katalog oszczędza
    komuś szukania URL-a i akapitu zgadywania przy konfiguracji; nie jest
    bramką.

## Wpis { #the-entry }

```json
{
  "key": "acme",
  "name": "Acme",
  "description": "Read and update work orders.",
  "category": "operations",
  "auth": "token",
  "url": "https://mcp.acme.com/mcp",
  "docs_url": "https://docs.acme.com/mcp",
  "token_hint": "A read-only service token from Settings → API, scoped to work orders.",
  "icon": "acme"
}
```

| Pole | |
|---|---|
| `key` | Stabilny identyfikator. Połączenia go zapisują, więc traktuj go tak, jak traktuje się identyfikatory capability: zmieniaj nazwę do woli, klucza nigdy |
| `name` | To, co pokazuje selektor |
| `description` | Jedno zdanie, w trybie rozkazującym, o tym, co robią *narzędzia* |
| `category` | Grupuje selektor. Użyj istniejącej, chyba że serwer naprawdę nie ma gdzie się podziać |
| `auth` | `none`, `token` albo `oauth` |
| `url` | Puste, gdy serwer hostuje klient albo gdy dostawca wydaje endpoint per konto — formularz wtedy o niego zapyta |
| `docs_url` | Gdzie dostawca dokumentuje swój serwer |
| `token_hint` | Tylko dla `token`. Zobacz niżej |
| `icon` | Nazwa `BrandIcon` albo pusta |

!!! note "Walidowane w momencie importu"

    Plik jest sprawdzany wobec `CatalogEntry` przy wczytaniu modułu, więc źle
    sformułowany wpis odmawia uruchomienia aplikacji, zamiast po cichu zniknąć z
    selektora.

## Napisz podpowiedź o tokenie { #write-the-token-hint }

!!! important "To jest pole, które uzasadnia cały wpis"

    Ogólnikowe instrukcje są główną przyczyną nieudanej konfiguracji tokena, a
    "jakiś token API" nikomu nie mówi, gdzie kliknąć.

Powiedz, skąd token pochodzi i co ma umieć:

> A fine-grained personal access token with read access to the repositories the
> agent should see.

Zostaw puste dla `oauth` i `none` — nie ma czego wklejać.

## Ikony { #icons }

`icon` nazywa znak marki. Jeśli żaden wkompilowany zestaw ikon go nie niesie,
wrzuć SVG do `backend/app/core/catalog/icons/<name>.svg` — jest serwowany przez
`GET /catalog/icons` i rysowany dla każdego wpisu katalogu albo providera, którego
identyfikator pasuje.

Własne kolory pliku są **ignorowane** — jest renderowany jako sylwetka
`currentColor`, więc monochromatyczny rejestr konsoli trzyma się z konstrukcji.
Kontrakt opisuje `icons/README.md`.

Puste `icon` spada do monogramu. To wygląd celowy, a nie brakujący: każdy zestaw
ikon jest skończony, a ten katalog nie jest.

## Zanim to zacommitujesz { #before-you-commit-it }

!!! warning "Wpis jest obietnicą"

    Że ktoś obejrzał ten serwer, że przepływ uwierzytelniania działa, że opis
    jest uczciwy. To cały powód, dla którego jest to lista utrzymywana ręcznie,
    a nie lustro publicznego rejestru — więc spraw, żeby ta obietnica była
    prawdziwa:

1. Połącz go w działającym deploymencie.
2. Uruchom `POST /api/v1/mcp-connections/{id}/test` (przycisk **Test**) i
   przeczytaj listę narzędzi, którą zwróci. Jeśli narzędzia nie zgadzają się z
   twoim `description`, popraw opis.
3. Dla `oauth` przejdź cały przepływ od początku do końca. Discovery, dynamiczna
   rejestracja i wymiana tokena zawodzą każde inaczej, a serwer, który utyka na
   drugim kroku, wygląda w UI identycznie jak taki, który jest po prostu wolny.
4. Sprawdź, czy nazwa nie koliduje z
   [prefiksem narzędzi](../mcp.md#name-collisions) istniejącego wpisu.

## Co nie wymaga zmiany { #what-does-not-need-changing }

Nic poza tym. Selektor renderuje się z katalogu, a serwis połączeń, sonda,
allowlista i prefiksowanie są generyczne. Wpis dodany tutaj jest w produkcie po
następnym restarcie.
