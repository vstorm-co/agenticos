---
source_sha: "dbf40f028eaa"
title: "Wywołaj agenta z własnej aplikacji"
description: "Uwierzytelnij się, wyślij nagłówek organizacji i uruchom opublikowanego agenta przez HTTP, a potem odczytaj tę samą kopertę błędu, budżet i limit żądań, które dostaje każda inna powierzchnia."
---

# Wywołaj agenta z własnej aplikacji { #call-an-agent-from-your-own-application }

Wywołaj opublikowanego agenta tak samo jak konsola, Slack i każda inna powierzchnia: jednym uwierzytelnionym `POST`, który przechodzi przez ten sam runner, to samo sprawdzenie budżetu i tę samą bramkę zatwierdzeń. Ta strona przechodzi przez [HTTP API](../api.md) z małym agentem i wkleja jego prawdziwe, przycięte odpowiedzi. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu i konto członka organizacji, na które się zalogujesz.
- Opublikowany agent bez capability, która wymaga konta, którego nie masz. Zapisany run poniżej używa agenta w ogóle bez capabilities, więc nic tu nie zależy od sandboksa, kolekcji ani połączenia MCP.

## Zbuduj agenta { #build-the-agent }

Utwórz agenta w **Agents → New agent**, wybierz swój profil modelu, zostaw Toolbox pusty, ustaw mały budżet i limit kroków oraz krótkie instrukcje:

```text
You are a small support assistant reachable over the HTTP API.
Answer briefly, in two or three sentences.
If asked something you cannot know, say so plainly rather than guessing.
```

Zrób **Publish** i skopiuj jego id z adresu URL albo z `GET /agents`.

## Uwierzytelnij się i uruchom go { #authenticate-and-run-it }

Zaloguj się po token dostępu, a potem wywołaj endpoint runu z tym tokenem i nagłówkiem organizacji:

```bash
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL&password=$PASSWORD" | jq -r .access_token)

curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "In one sentence, what is a model profile?"}'
```

```python
import httpx

login = httpx.post(f"{BASE}/api/v1/auth/login",
                    data={"username": EMAIL, "password": PASSWORD})
token = login.json()["access_token"]

resp = httpx.post(
    f"{BASE}/api/v1/agents/{AGENT_ID}/run",
    headers={"Authorization": f"Bearer {token}", "X-Organization-Id": ORG_ID},
    json={"prompt": "In one sentence, what is a model profile?"},
)
resp.raise_for_status()
print(resp.json()["output"])
```

`X-Organization-Id` decyduje, w której organizacji wykonuje się wywołanie. Zobacz [nagłówek organizacji](../api.md#the-organization-header). Nagłówek `X-API-Key` działa tak samo dla usługi, za którą nie stoi żadna osoba. Dwa wywołania powyżej używają JWT członka organizacji.

## Albo streamuj odpowiedź { #stream-it-instead }

`ws://…/api/v1/ws/agent` to ten sam uwierzytelniony socket, którego używa czat w konsoli. Token jest w subprotokole (`access_token.<JWT>` i `chat`), a nie w nagłówku, bo `WebSocket` w przeglądarce nie może ustawić nagłówka. Ramka zawiera `message`, `agent_id` i opcjonalne `conversation_id`. Socket odpowiada zdarzeniami `text_delta`, gdy model pisze, `tool_call` i `tool_result` przy każdym kroku, `tool_approval_required`, jeśli coś zaparkuje, i `complete` z użyciem runu na końcu. Zobacz [streaming](../api.md#streaming).

## Obsłuż błędy, budżety i limity żądań { #handle-errors-budgets-and-rate-limits }

Każda odmowa wraca w tej samej kopercie: `error.code`, `error.message` i `error.details`:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "prompt: Field required",
  "details": {"fields": [{"field": "prompt", "message": "Field required"}]}}}
```

Run przyjęty przez ten endpoint nadal przechodzi przez governance: [budżet](../governance.md#budgets) jest sprawdzany przed żądaniem do modelu i run kończy się błędem zamiast przekroczyć limit, a narzędzie za bramką [parkuje do zatwierdzenia](../governance.md#approvals) dokładnie tak jak w czacie. Wywołujący przez API nie może pominąć żadnego z nich. Sama trasa ma limit żądań zamiast bramki uprawnień, liczony per wywołujący: domyślnie 30 runów na minutę (`RATE_LIMIT_RUN_PER_MINUTE`), a nadmiar jest odrzucany z prośbą o odczekanie, a nie kolejkowany.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Zwykły run | `status: "completed"`, tekst w `output`, `cost_usd` i liczby tokenów |
| Brak nagłówka `Authorization` | `401`, `www-authenticate: Bearer` |
| Błędny `X-Organization-Id` | `404`, `NOT_FOUND`, taki sam kształt jak dla agenta, który nie istnieje |
| Nieznane `agent_id` | `404` z `agent_id` w `details` |
| Treść bez `prompt` | `422` (`VALIDATION_ERROR`), `details.fields` nazywa pole |
| Dwie organizacje, jeden wywołujący | Run widzi tylko organizację wskazaną w nagłówku tego wywołania |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, agent `uc-api-demo`. `POST /run` z prawdziwym promptem odpowiedział `{"status": "completed", "cost_usd": "0.000582", "output": "A model profile is a structured description of an AI model's key characteristics, capabilities, limitations, and intended use cases."}`.

    Pominięcie `X-Organization-Id` **nie** odrzuciło tu wywołania: API wróciło do osobistej organizacji zalogowanego członka i wykonało run tam, zamiast odpowiedzieć „no tenant to act in”. Wymyślone id organizacji wróciło jako `404` z `"Organization not found or access denied"`. Pominięcie `Authorization` wróciło jako `401` z `www-authenticate: Bearer`. Pusta treść wróciła jako `422` z `details.fields: [{"field": "prompt", "message": "Field required"}]`, dokładnie zgodnie z kopertą powyżej.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **`404` dla id agenta, o którym wiesz, że istnieje.** Najpierw sprawdź nagłówek organizacji. Odczyt z innej organizacji celowo odpowiada `404`, tak samo jak brakujący agent.
- **`429` w trakcie testu integracyjnego.** Limit żądań na trasie runu jest per wywołujący, a nie per agent. Odczekaj, zamiast od razu ponawiać.
- **Run odpowiada, ale nie dociera do włączonego narzędzia.** Sprawdź w Activity, czy nie czeka zaparkowane zatwierdzenie. Ścieżka HTTP parkuje dokładnie tak jak czat, a `POST /run` sam się nie wznawia.
- **Koszt nie zgadza się z panelem Twojego dostawcy.** `cost_is_partial` w odpowiedzi mówi, czy liczba jest dolnym oszacowaniem, a nie wartością końcową. `true` oznacza, że części runu nie dało się wycenić.

## Zapisz próbę { #record-the-trial }

Zachowaj żądanie i odpowiedź dla każdego sprawdzenia, wersję agenta i profil modelu. Człowiek nadal decyduje, jaką capability może mieć agent wywoływany między serwerami, czy potrzebuje własnego klucza API zamiast współdzielonego i jaki budżet go ogranicza. Endpoint egzekwuje te decyzje, ale ich nie podejmuje.

## Kolejne kroki { #next-steps }

Jeśli chcesz tokenu, którego nikt nie musi odświeżać, użyj klucza API zamiast logowania po JWT. Oba sposoby opisuje [uwierzytelnianie](../api.md#authenticating). Jak wywołania narzędzi i koszt runu wyglądają, gdy trafią do produktu, pokazuje [governance](../governance.md#budgets).
