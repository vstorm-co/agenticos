---
source_sha: "9121fc5ca757"
title: "Segreguj zgłoszenia wsparcia z własnej aplikacji"
description: "Uruchamiaj agenta z własnego backendu podpisanym webhookiem i niech klasyfikuje zgłoszenia, przygotowuje szkic odpowiedzi i oznacza zgłoszenia bezpieczeństwa."
---

# Segreguj zgłoszenia wsparcia z własnej aplikacji { #triage-incoming-support-requests-from-your-own-app }

Podłącz własny formularz wsparcia albo system zgłoszeń do agenta przez [trigger zdarzeń](../triggers.md) ze źródłem **API**, czyli ogólnym źródłem `webhook`, które uruchamia się przy każdej podpisanej dostawie JSON. Trzy syntetyczne zgłoszenia, w tym jedno dotyczące bezpieczeństwa, sprawdzają, czy klasyfikacja, szkic odpowiedzi i oznaczenie bezpieczeństwa działają, zanim skierujesz tu prawdziwy system. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

[Działająca instalacja](../install.md) z profilem modelu. Bez sandboksa, modelu embeddingów i zewnętrznego konta: źródło API samo podpisuje dostawy, więc nie ma konsoli dostawcy do konfiguracji.

## Przygotuj dane wejściowe { #prepare-the-input }

Trzy zgłoszenia w takiej postaci, w jakiej wysłałby je Twój backend. Cała treść JSON trafia do promptu agenta, więc zadziała dowolny kształt, o ile napiszesz pod niego instrukcje:

```json
{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}
{"ticket_id":"T-1002","from":"marek@example.org","subject":"Export button does nothing","body":"Clicking Export CSV on the reports page just spins forever and nothing downloads. Chrome, latest version."}
{"ticket_id":"T-1003","from":"researcher@example.net","subject":"Found an issue with account access","body":"By changing the id in the /api/v1/invoices/{id} URL I was able to view another customer's invoice PDF without being logged in as them. Tested with three different ids, all worked."}
```

Kryterium: T-1001 dotyczy rozliczeń, priorytet średni. T-1002 jest techniczne, priorytet średni. T-1003 opisuje IDOR i powinno wrócić jako bezpieczeństwo, priorytet pilny, z jawnym oznaczeniem.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu. Ta próba nie wymaga żadnej capability.
2. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You triage inbound support tickets for a small SaaS product.
Be concise and factual. Never invent facts not in the ticket.
```

3. Otwórz **Routines → New event trigger**, wybierz agenta i źródło **API**. Ustaw własny prompt triggera. To on jest wysyłany przed dostawą przy każdym uruchomieniu:

```text
A support ticket just arrived as JSON below. Classify it by category (billing,
technical, account, security, other) and priority (low, medium, high, urgent).
Draft a reply the support team can send. If the ticket describes a possible
security vulnerability or exposure of somebody else's data, say so explicitly in
a line starting with 'SECURITY:' and set priority to urgent.
```

4. Zapisz. Skopiuj **webhook URL** i **signing secret**, które zostaną pokazane jeden raz. Źródło API ma dostawę typu `manual`, więc nic nie rejestruje się samo, a sekret wybierasz sam. Co oznaczają oba elementy, opisują [triggery](../triggers.md#the-mechanism-once).

## Uruchom { #run-it }

Podpisz dokładne bajty każdego zgłoszenia sekretem triggera i wyślij je POST-em. Dwie pułapki opisuje [samodzielne podpisanie dostawy](../triggers.md#signing-a-delivery-yourself): nie serializuj treści ponownie i podpisuj wyłącznie te bajty, które wysyłasz.

```bash
SECRET='your-signing-secret'
URL='http://localhost:8110/api/v1/webhooks/triggers/webhook/<trigger_id>'
BODY='{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "X-Signature-256: $SIG" \
  --data-raw "$BODY"
```

Powtórz dla T-1002 i T-1003. Każda przyjęta dostawa odpowiada `202`, czyli „przyjęto”, a nie „zakończono”. Uruchomione runy przeczytasz w **Activity** albo w rozmowie samego triggera w **Routines**.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| T-1001 | Kategoria rozliczenia, priorytet średni, odpowiedź potwierdzająca podwójne obciążenie |
| T-1002 | Kategoria techniczna, priorytet średni, odpowiedź prosząca o szczegóły do odtworzenia problemu |
| T-1003 | Kategoria bezpieczeństwo, priorytet pilny, linia zaczynająca się od `SECURITY:` nazywająca wyciek |
| Odpowiedź `202` | Przychodzi od razu; sam run kończy się kilka sekund później, asynchronicznie |
| Niepodpisana dostawa tej samej treści | `403`, odrzucona, zanim agent w ogóle się uruchomi |
| Dostawa z treścią ponownie zserializowaną przez klienta HTTP zamiast wysłanej bez zmian | `403`, bo podpis nie zgadza się już z faktycznie wysłanymi bajtami |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Wszystkie trzy dostawy odpowiedziały `202` i zakończyły się w około 6 sekund każda, zapisane na powierzchni `schedule`: uruchomienia triggerów zdarzeń dzielą tę powierzchnię z harmonogramami.

    T-1001: *"Category: Billing, Priority: Medium"*, odpowiedź prosząca o ID faktury do przetworzenia zwrotu. T-1002: *"Category: Technical, Priority: Medium"*, odpowiedź prosząca o wynik z konsoli przeglądarki. T-1003: *"Category: Security, Priority: Urgent"*, a potem `SECURITY: Reporter claims unauthenticated/unauthorized access to other customers' invoice PDFs via IDOR (Insecure Direct Object Reference) on /api/v1/invoices/{id}. Multiple accounts confirmed affected.` oraz szkic odpowiedzi proszący zgłaszającego, żeby nie testował dalej, dopóki sprawa jest badana. Łączny koszt trzech runów: 0,013 USD.

    Sprawdzono też obie ścieżki odmowy: ta sama treść wysłana bez nagłówka `X-Signature-256` odpowiedziała `403`, a treść podpisana jako tekst, ale wysłana przez klienta z własnym przekodowaniem `json=` (ta sama zawartość, inne bajty), też odpowiedziała `403 AUTHORIZATION_ERROR: Webhook signature did not verify`. To potwierdza, że podpis obejmuje dokładne bajty na łączu, a nie logiczną zawartość JSON-a.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Każda dostawa wraca jako `403`.** Podpis obejmuje *dokładne* wysłane bajty. `echo` dodaje końcowy znak nowej linii, który może, ale nie musi zgadzać się z tym, co podpisano. Użyj `printf '%s'` i `curl --data-raw` i nigdy nie pozwól klientowi przekodować słownika po podpisaniu tekstu.
- **`202`, ale run się nie pojawia.** To znaczy „przyjęto”, a nie „zakończono”: run wykonuje flow Prefecta w workerze. Daj mu kilka sekund i sprawdź Activity z filtrem na tego agenta.
- **Oznaczenie bezpieczeństwa nie zadziałało.** Oznaczenie wynika z instrukcji, a nie z wbudowanego klasyfikatora. Przeczytaj ponownie prompt triggera i doprecyzuj, co liczy się jako zgłoszenie bezpieczeństwa, jeśli umyka syntetyczny przypadek jak T-1003.
- **Chcesz przetestować tylko prompt, a nie ścieżkę dostawy.** Najpierw użyj **Run now** na triggerze. Uruchamia podstawowy prompt agenta bez kontekstu dostawy, bez podpisu i bez webhooka. Nie sprawdzi klasyfikacji, bo nie ma JSON-a ze zgłoszeniem do sklasyfikowania, ale potwierdzi, że agent, jego budżet i stan publikacji działają.
- **Zapier albo Make zamiast skryptu.** Żadne z nich nie ma wbudowanej akcji HMAC. Zaplanuj godzinę na krok z kodem, który podpisze treść, a nie pięć minut klikania. Zobacz [triggery](../triggers.md#zapier-and-make-cannot-do-this-without-a-code-step).

## Zapisz próbę { #record-the-trial }

Zachowaj treść trzech zgłoszeń, prompt triggera, pochodzenie sekretu podpisu (bez jego wartości), status HTTP każdej dostawy i run, który każda z nich wywołała w Activity. Człowiek nadal czyta każdy szkic, zanim trafi do klienta, i decyduje, czy próg oznaczenia bezpieczeństwa jest wystarczająco ścisły dla prawdziwej skrzynki, zanim skieruje na ten webhook działający system zgłoszeń.

## Kolejne kroki { #next-steps }

To samo źródło API działa dla wszystkiego, co potrafi podpisać i wysłać JSON: zgłoszenia formularza, zmiany oferty na marketplace'ie, alertu z monitoringu. Segregację skrzynki zamiast zgłoszeń z własnej aplikacji opisuje strona [Segreguj skrzynkę i przygotowuj szkice odpowiedzi](email-triage.md), która zamiast podpisanej dostawy używa źródła Gmail.
