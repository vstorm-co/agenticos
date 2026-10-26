---
title: "Odpowiedz na pocztę zatwierdzonym szkicem"
description: "Workflow czyta nową pocztę, przygotowuje odpowiedź, prosi człowieka o jej edycję i zatwierdzenie, a potem zostawia szkic w wątku albo wysyła ją przez własny serwer MCP dla Gmaila lub Microsoft 365."
source_sha: "fc39b8c85301"
---

# Odpowiedz na pocztę zatwierdzonym szkicem { #answer-mail-with-an-approved-draft }

[Strona o segregowaniu skrzynki](email-triage.md) kończy się tekstem w czacie. Ta
idzie o krok dalej: [workflow](../workflows.md) czyta nową wiadomość, przygotowuje
odpowiedź, pokazuje ją człowiekowi, który może ją poprawić, a potem zapisuje ją w
skrzynce - jako szkic w tym samym wątku albo jako wysłaną odpowiedź. Do skrzynki
sięga się przez serwer MCP, który prowadzisz sam.

To procedura do wykonania, a nie raport ze zmierzonego wdrożenia. Potrzebuje skrzynki,
rejestracji aplikacji w Google lub Microsoft i serwera, których opiekunowie nie
uruchomili na potrzeby tej strony, więc nic tutaj nie zostało uruchomione na żywej
skrzynce. Nazwy narzędzi i argumentów odczytano z kodu źródłowego serwerów, a nie z
działającego serwera.

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
- Połączenie MCP **organizacji** z tym serwerem, utworzone z tego wpisu katalogu
  przez kogoś z uprawnieniem `mcp:manage`. Każde połączenie loguje się jako jedno
  konto, więc odpowiada z jednej skrzynki. Workflow nie może jeszcze używać
  połączenia należącego do osoby, więc skrzynka osiągana w ten sposób to konto
  usługowe albo skrzynka współdzielona.
- Podłączony portal Gmaila lub Outlooka, dla triggera. Trigger czyta pocztę tylko z
  dostępem do odczytu. Prawo zapisu jest na połączeniu MCP, to osobna zgoda:
  połącz je jako konto, które ma być autorem odpowiedzi.

## Gmail { #gmail }

Zbuduj workflow w tej kolejności.

1. Trigger **Gmail** ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail)).
   Jego wyjście zawiera `thread_id`, `rfc_message_id`, `subject`, `sender` i `text`.
2. Krok przygotowujący odpowiedź: [`agent.run`](../reference/workflow-nodes.md#agent-run)
   z capability knowledge albo [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search),
   a po nim [`ai.prompt`](../reference/workflow-nodes.md#model-steps). Jego tekst to
   proponowana odpowiedź.
3. [`human.approval`](../reference/workflow-nodes.md#human-approval) z włączonym
   `editable` i `proposal` podpiętym z kroku przygotowującego. Zatwierdzający czyta
   streszczenie maila w `details`, poprawia tekst i zatwierdza.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) na połączeniu Google
   Workspace, narzędzie `draft_gmail_message`, z takimi argumentami:

   | Argument | Podpięty z |
   |---|---|
   | `thread_id` | `thread_id` triggera |
   | `in_reply_to` | `rfc_message_id` triggera |
   | `body` | `final` kroku zatwierdzenia |

   Pomiń `references`: serwer wyprowadza łańcuch z wiadomości, na którą się
   odpowiada. Pomiń też `to`, a serwer odpowie nadawcy tej wiadomości; ustaw
   `reply_all` na `true`, by odpowiedzieć wszystkim w wątku. Pomiń `subject`, a
   szkic zachowa temat wątku. `user_google_email` uzupełnia serwer, bo działa z
   `MCP_ENABLE_OAUTH21=true`.

   Ustaw **Ask for approval** tego kroku na **Never**. Człowiek zatwierdził dokładny
   tekst krok wcześniej i inaczej zostałby zapytany drugi raz.

Aby **wysłać** zamiast zostawić szkic, użyj `send_gmail_message` z tymi samymi
argumentami i jednym dodatkowym: podepnij `to` z `sender` triggera albo ustaw
`reply_all` na `true`. Narzędzie odrzuca wywołanie, które nie ma żadnego z nich
(`reply_all` wymaga `thread_id`), a tylko narzędzie szkicu samo uzupełnia `to`.
Serwer nie ma narzędzia, które wysyła zapisany szkic, więc to dwa osobne wybory, a
nie dwa kroki.

!!! warning "Bezpośrednie wysłanie nie ma zabezpieczenia"

    `send_gmail_message` nie przyjmuje klucza idempotencji, a serwer oznacza je jako
    zapis. Jeśli wywołanie poszło, a odpowiedź nie nadeszła, krok kończy się jako
    **Uncertain** i run czeka na człowieka: mail mógł wyjść albo nie. Otwórz wątek w
    Gmailu i sprawdź, zanim uruchomisz krok ponownie. Gdy chcesz mieć drugą szansę
    na wychwycenie błędu, użyj `draft_gmail_message` i niech człowiek naciśnie
    **Send** w Gmailu: powtórzenie może najwyżej zostawić drugi szkic.

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
- **Gmail: zostaw szkic** (zalecane). Powtórzenie zostawia najwyżej drugi szkic.
- **Gmail: bezpośrednie wysłanie** nie ma takiej ochrony; zobacz ostrzeżenie wyżej.

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
- Odrzuć zatwierdzenie i sprawdź, że nic nie zostaje zapisane.

## Dalsze kroki z tego samego połączenia { #next-steps-from-the-same-connection }

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Kalendarz Microsoft 365:** `list-calendar-events`, `create-calendar-event`.

Istnieje jeszcze inna droga do Microsoftu: hostowany serwer **Microsoft Work IQ**
odpowiada na pytania o pocztę, spotkania, czaty i pliki, ale blokuje zmiany, dopóki
administrator tenanta nie dopuści ich polityką. Zobacz [Microsoft 365 i Outlook](../mcp.md#outlook-setup).
