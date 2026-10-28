---
title: "Odpowiedz na pocztę zatwierdzonym szkicem"
description: "Workflow czyta nową pocztę, przygotowuje odpowiedź, prosi człowieka o jej edycję i zatwierdzenie, a potem zostawia szkic w wątku albo wysyła ją przez własny serwer MCP dla Gmaila lub Microsoft 365."
source_sha: "bc960ef3277b"
---

# Odpowiedz na pocztę zatwierdzonym szkicem { #answer-mail-with-an-approved-draft }

[Strona o segregowaniu skrzynki](email-triage.md) kończy się tekstem w czacie. Ta
idzie o krok dalej: [workflow](../workflows.md) czyta nową wiadomość, przygotowuje
odpowiedź, pokazuje ją człowiekowi, który może ją poprawić, a potem zapisuje ją w
skrzynce - jako szkic w tym samym wątku albo jako wysłaną odpowiedź. Do skrzynki
sięga się przez serwer MCP, który prowadzisz sam.

Workflow dla Gmaila opisany niżej uruchomiono od początku do końca na testowej
skrzynce we wdrożeniu deweloperskim, z `workspace-mcp` 2.2.1. Przepisu dla Microsoft 365
nie uruchomiono: nazwy jego narzędzi i argumentów odczytano z kodu źródłowego serwera,
a nie z działającego serwera.

## Czego potrzebujesz { #what-you-need }

- Jeden z dwóch serwerów, działający tam, gdzie wdrożenie może go osiągnąć, z
  adresem kończącym się na `/mcp`:
  [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
  dla Gmaila, z `--transport streamable-http`, `MCP_ENABLE_OAUTH21=true` i Twoim
  własnym klientem Google OAuth, albo
  [`softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server) dla
  Outlooka, z `--http` i aplikacją zarejestrowaną w Microsoft Entra (dodaj
  `--org-mode`, by sięgnąć do skrzynek współdzielonych). Katalog wymienia je jako
  **Google Workspace (self-hosted)** i **Microsoft 365 (self-hosted)**.
- Serwer w Twojej własnej sieci jest odrzucany, dopóki operator nie wpisze jego
  hosta do `OUTBOUND_PRIVATE_ALLOWLIST` albo `MCP_ALLOWED_HOSTS`. Zobacz [serwery
  MCP](../mcp.md) i [ustawienia](../configuration.md#project-settings).
- Przy `MCP_ENABLE_OAUTH21=true` serwer Google Workspace odmawia startu na zwykłym
  `http` wszędzie poza `localhost`, a wdrożenie odrzuca adres pętli zwrotnej dla
  serwera MCP. Udostępnij go więc przez HTTPS pod nazwą hosta, którą wdrożenie może
  osiągnąć. Aby wypróbować workflow na laptopie, uruchom serwer z `--single-user` i bez
  `MCP_ENABLE_OAUTH21`: loguje się raz do Google, zachowuje token tego konta i
  odpowiada wdrożeniu bez logowania. Każdy, kto sięga do serwera, może wtedy używać tej
  skrzynki, więc ogranicz to do konta testowego na maszynie, do której nikt inny nie
  ma dostępu.
- Połączenie MCP **organizacji** z tym serwerem, utworzone z tego wpisu katalogu
  przez kogoś z uprawnieniem `mcp:manage`. Każde połączenie loguje się jako jedno
  konto, więc odpowiada z jednej skrzynki. Workflow nie może jeszcze używać
  połączenia należącego do osoby, więc skrzynka osiągana w ten sposób to konto
  usługowe albo skrzynka współdzielona.
- Podłączony portal Gmaila lub Outlooka, dla triggera. Trigger czyta pocztę tylko z
  dostępem do odczytu. Prawo zapisu jest na połączeniu MCP, to osobna zgoda:
  połącz je jako konto, które ma być autorem odpowiedzi.

## Gmail { #gmail }

Workflow opiera się na typowym wzorcu autorespondera w Gmailu: ocenić, czy mail wymaga
odpowiedzi, przygotować ją i wstawić do wątku. Dodaje dwie rzeczy. Człowiek sprawdza
każdą odpowiedź, zanim trafi do skrzynki, i tam wybiera, czy ją wysłać, czy zostawić
jako szkic. Zbuduj go w tej kolejności.

1. Trigger **Gmail** ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail))
   z **Label** `INBOX`. Jego wyjście zawiera `sender`, `subject`, `text`,
   `message_id`, `thread_id` i `rfc_message_id`. Skrzynka jest sprawdzana co minutę,
   chyba że w kroku wybierzesz dłuższy odstęp.
2. **Czy wymaga odpowiedzi?** [`ai.classify`](../reference/workflow-nodes.md#model-steps)
   z trzema kategoriami: `needs_reply`, `fyi` (newslettery, rachunki, powiadomienia,
   podziękowania) i `spam`, z `text` podpiętym z nadawcy, tematu i treści. Ustaw
   **Minimum confidence**, na przykład `0.7`: mail, co do którego model jest mniej
   pewny, wychodzi portem `unsure`, więc decyduje o nim człowiek, a nie model. Pewność
   modelu to jego własna deklaracja i nie jest skalibrowana, więc wypróbuj próg na
   własnej poczcie za pomocą [ewaluacji](../workflows.md#evals-for-a-model-step) kroku.
3. **Połącz dwie drogi do odpowiedzi.** Poprowadź `needs_reply` i `unsure` do jednego
   [`logic.merge`](../reference/workflow-nodes.md#logic-if-and-logic-merge). `fyi`,
   `spam` i `other` kończą się tam albo prowadzą do kroku, który je zapisuje.
4. **Przygotuj odpowiedź.** [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   na kolekcji z Twoimi odpowiedziami, z `query` podpiętym z tematu i treści, a potem
   [`ai.prompt`](../reference/workflow-nodes.md#model-steps) z mailem i `sources` z
   wyszukiwania w prompcie. Instrukcje, które dobrze działają: odpowiadaj w języku
   nadawcy, zwykłym tekstem, zacznij od powitania i zakończ pozdrowieniem, korzystaj z
   fragmentów i nigdy nie zmyślaj odpowiedzi, a tam, gdzie odpowiedzi nie znasz, wstaw
   zastępnik, na przykład `[YOUR_ANSWER_HERE]`. Uzupełnia go zatwierdzający.
   [`agent.run`](../reference/workflow-nodes.md#agent-run) z capability knowledge robi to
   samo w jednym kroku.
5. **Sprawdź ją.** [`human.approval`](../reference/workflow-nodes.md#human-approval) z
   włączonym `editable`, `proposal` podpiętym z przygotowanej odpowiedzi, samym mailem
   w `details` i dwoma **wyborami (`choices`)**: `send` (**Send now**) i `draft`
   (**Save as draft**). Zatwierdzający poprawia tekst i naciska przycisk odpowiadający
   temu, co ma się z nim stać, albo **Reject**.
6. **Zapisz ją w skrzynce.** Jedno
   [`mcp.call`](../reference/workflow-nodes.md#mcp-call) na połączeniu Google Workspace
   na każdy wybór:

   | Wybór | Narzędzie | Argumenty |
   |---|---|---|
   | `send` | `send_gmail_message` | `thread_id`, `in_reply_to`, `body` oraz `to` z `sender` triggera |
   | `draft` | `draft_gmail_message` | `thread_id`, `in_reply_to`, `body` |

   Podepnij `thread_id` z `thread_id` triggera, `in_reply_to` z jego `rfc_message_id`, a
   `body` z `final` wyjścia zatwierdzenia na porcie tego wyboru. Pomiń `references`:
   serwer wyprowadza łańcuch z wiadomości, na którą się odpowiada. Pomiń `subject`, a
   odpowiedź zachowa temat wątku. Narzędzie wysyłania odrzuca wywołanie, w którym nie
   ustawiono ani `to`, ani `reply_all` na `true`; narzędzie szkicu samo uzupełnia `to`.
   `user_google_email` uzupełnia serwer działający z `MCP_ENABLE_OAUTH21=true`; w trybie
   single-user podepnij je z adresu skrzynki.

   Ustaw **Ask for approval** obu kroków na **Never**. Człowiek zatwierdził dokładny
   tekst krok wcześniej i inaczej zostałby zapytany drugi raz.

Aby zachować ślad, dodaj po którymś z tych kroków krok zapisu wiersza do
[tabeli](../virtual-tables.md), z kategorią, decyzją i wysłanym tekstem.

!!! warning "Bezpośrednie wysłanie nie ma zabezpieczenia"

    `send_gmail_message` nie przyjmuje klucza idempotencji, a serwer oznacza je jako
    zapis. Jeśli wywołanie poszło, a odpowiedź nie nadeszła, krok kończy się jako
    **Uncertain** i run czeka na człowieka: mail mógł wyjść albo nie. Otwórz wątek w
    Gmailu i sprawdź, zanim uruchomisz krok ponownie. **Save as draft** tego nie robi:
    powtórzenie może najwyżej zostawić drugi szkic. Serwer nie ma narzędzia, które
    wysyła zapisany szkic, więc szkic wysyła się z Gmaila.

## Microsoft 365 { #microsoft-365 }

1. Trigger **Outlook** ([`trigger.outlook`](../reference/workflow-nodes.md#trigger-outlook)).
   Jego wyjście zawiera `message_id` i, dla skrzynki współdzielonej, `mailbox`.
2. Ten sam krok przygotowujący i ten sam edytowalny `human.approval` co wyżej.
3. **Przygotuj treść odpowiedzi.** Krok **Map fields** ([`data.map`](../reference/workflow-nodes.md#data-map))
   buduje jedno pole, `reply_body`, typu `json` z `final` zatwierdzenia:

   ```text
   {Message: {body: {contentType: 'text', content: source.final}}}
   ```

   z `source` podpiętym do kroku zatwierdzenia; wynikiem jest `values.reply_body`.

   Wskazówka samego serwera dla `create-reply-draft` każe podać tekst jako
   `Message.body.contentType` i `Message.body.content`; podana treść zastępuje całą
   treść szkicu, więc cytowanej historii w niej nie ma.

   Sprawdź nazwy argumentów w
   formularzu narzędzia w edytorze po wybraniu narzędzia i odświeżeniu jego listy:
   serwer buduje je z Microsoft Graph i nie widziano ich na działającym serwerze.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) na połączeniu Microsoft 365,
   narzędzie `create-reply-draft`, z `messageId` podpiętym z `message_id` triggera i
   `body` podpiętym z `values.reply_body` poprzedniego kroku. Graph sam wiąże szkic z
   wątkiem. Dla skrzynki współdzielonej czytanej przez trigger użyj zamiast tego
   `create-shared-mailbox-reply-draft`, dodając `userId` podpięte z `mailbox`
   triggera; serwer musi działać z `--org-mode`. Serwer rejestruje swoje parametry
   ścieżki w camelCase i je wymaga.

5. *Opcjonalnie.* Aby wysłać szkic, najpierw odczytaj jego identyfikator. Serwer
   odpowiada JSON-em wewnątrz swojego `text`, a nie jako dane `structured`, więc
   wyjmuje go krok [`code.python.simple`](../reference/workflow-nodes.md#python):
   podepnij `args.text` do `text` kroku tworzącego i uruchom

   ```python
   import json
   json.loads(args['text'])['id']
   ```

   Nie uruchamiaj serwera z `--toon`: jego wyjście nie jest wtedy JSON-em. Potem
   wywołaj `send-draft-message` z `messageId` podpiętym z `result` tego kroku
   (`send-shared-mailbox-draft` dla skrzynki współdzielonej, które przyjmuje też
   `userId` podpięte z `mailbox` triggera).

Po edytowalnym zatwierdzeniu ustaw **Ask for approval** każdego kroku `mcp.call` na
**Never**. Gdy przed krokiem nic nie zatwierdzono, zostaw wartość domyślną,
**Before a tool that can change something**. Ta zasada pyta przed każdym narzędziem,
którego serwer nie oznacza jako tylko do odczytu, więc pyta także przed
`create-reply-draft` i przed `draft_gmail_message` w Gmailu.

### Co robi powtórzenie { #what-a-repeat-does }

Żaden z serwerów nie przyjmuje klucza idempotencji, więc zostaw **Idempotency key
argument** puste w tych krokach. Poniższe sposoby sprawiają, że powtórzenie jest
nieszkodliwe bez niego.

- **Microsoft 365: utwórz, a potem wyślij po identyfikatorze szkicu.** Drugie
  `send-draft-message` dla tego samego szkicu kończy się błędem, bo wysłany szkic
  opuścił Wersje robocze; nie wysyła drugiego maila. Powtórzone `create-reply-draft`
  może zostawić zbędny szkic, nigdy drugiego wysłanego maila. Jeśli krok wysyłania
  urwie się po wywołaniu, kończy się jako **Uncertain**: zajrzyj do Elementów
  wysłanych, potem uruchom go ponownie. Ponowne uruchomienie wysyłki, która doszła
  do skutku, kończy się błędem zamiast wysłać mail jeszcze raz.
- **Gmail: Save as draft.** Powtórzenie zostawia najwyżej drugi szkic.
- **Gmail: Send now** nie ma takiej ochrony; zobacz ostrzeżenie wyżej.

Awaria przed wywołaniem - serwer nie działa, połączenie odrzucone - jest ponawiana
sama. Po wywołaniu bez klucza narzędzia, którego serwer nie oznacza jako tylko do
odczytu, krok nigdy nie jest powtarzany automatycznie. Zasadę opisuje [dokumentacja
`mcp.call`](../reference/workflow-nodes.md#mcp-call).

## Bezpieczeństwo { #safety }

Poczta to dane z zewnątrz i może zawierać polecenia skierowane do modelu; ostrzega
przed tym dokumentacja serwera Google Workspace. Zostaw krok zatwierdzenia między
krokiem przygotowującym a skrzynką i nie dawaj agentowi przygotowującemu odpowiedź
narzędzia, które potrafi zapisywać.

Załączniki trafiają do workflow jako pliki, ale odpowiedź napisana w ten sposób
żadnych nie niesie.

## Sprawdź to { #check-it }

- Szkic albo wysłana odpowiedź jest widoczna w oryginalnym wątku w skrzynce; wysłana trafia też do nadawcy.
- `In-Reply-To` wysłanej lub zapisanej wiadomości jest równe `rfc_message_id`
  triggera.
- Zmień tekst w zatwierdzeniu i sprawdź, że w skrzynce ląduje zmieniony tekst, a nie
  propozycja.
- Naciśnij raz **Save as draft** i raz **Send now** i sprawdź, że każdy zrobił tylko
  to, co mówi jego przycisk.
- Wyślij newsletter i sprawdź, że nie uruchamia żadnego zatwierdzenia.
- Odrzuć zatwierdzenie i sprawdź, że nic nie zostaje zapisane.

Poczta wysłana do skrzynki z jej własnego adresu dostaje etykietę SENT, a trigger
pomija pocztę SENT, więc testuj pocztą z innego konta.

## Dalsze kroki z tego samego połączenia { #next-steps-from-the-same-connection }

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Kalendarz Microsoft 365:** `list-calendar-events`, `create-calendar-event`.

Istnieje jeszcze inna droga do Microsoftu: hostowany serwer **Microsoft Work IQ**
odpowiada na pytania o pocztę, spotkania, czaty i pliki, ale blokuje zmiany, dopóki
administrator tenanta nie dopuści ich polityką. Zobacz [Microsoft 365 i Outlook](../mcp.md#outlook-setup).
