---
source_sha: "ee9dcf4d5cd6"
---

# Słownik { #glossary }

Słowa, których używa konsola, co każde z nich znaczy i jak ta sama rzecz nazywa
się w API, w spec i w YAML-u, który agent eksportuje. Konsola, przewodnik, AI
Architect i ta dokumentacja używają tych nazw; API i spec zachowują własne, żeby
skrypt napisany pod nie nie przestał działać po zmianie nazwy.

## Co budujesz { #what-you-build }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Agent | Asystent z własnymi instrukcjami, modelem, wiedzą i narzędziami | `agent` |
| Wersja robocza | Nieopublikowane zmiany agenta; nikt poza Builderem ich nie widzi | `draft_spec` |
| Opublikuj | Zamrożenie wersji roboczej jako numerowanej wersji, którą uruchamia każde miejsce | `POST /agents/{id}/publish` |
| Wersja | Jeden opublikowany stan agenta, zachowany i porównywalny | `agent_version` |
| Test | Czat obok Buildera, który odpowiada jako wersja robocza albo dowolna wersja | `is_test` na jego runach |
| Instrukcje | To, co agent słyszy przed każdą rozmową | `instructions` |
| Zmienne | `{{name}}` w instrukcjach, uzupełniane na starcie runu | `variables` |
| Capability | Coś, co agent może robić, włączane w Builderze | `capabilities[]` |
| Skill | Wiedza praktyczna zapisana raz i czytana przez każdego agenta, który jej potrzebuje | `skill` |
| Kontekst | Stała wiedza, którą agent zawsze ma, np. słownik albo polityka | `context` |
| Baza wiedzy | Dokumenty, które agent przeszukuje i cytuje | `collection` |
| Aplikacja | Strona, którą publikuje agent, np. raport albo mały dashboard | `artifact` |
| AI Architect | Asystent w rogu każdej strony, który może budować z tobą agentów | `platform-assistant` |

## Gdzie to działa { #where-it-runs }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Czat | Rozmowa z agentem w przeglądarce | `conversation` |
| Kanał | Slack, Telegram albo Mattermost, gdzie ludzie piszą do agenta | `channel_bot` |
| Rutyna | Agent działający sam, według harmonogramu albo zdarzenia | `trigger` |
| Run | Jedna odpowiedź agenta, z jej kosztem i krokami | `agent_run` |
| Środowisko | Nazwany etap, np. produkcja, wskazujący jedną wersję | `environment` |
| Serwer MCP | Zewnętrzny serwer narzędzi, z którego korzystają agenci, podłączony raz | `mcp_connection` |
| Sandbox | Odizolowany komputer, na którym agent zapisuje pliki i uruchamia kod | `sandbox` |
| Pliki agentów | Pliki, które agenci trzymają w swoich sandboxach | `workspace` |

## Kto decyduje { #who-decides }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Organizacja | Firma albo zespół, do którego wszystko należy | `organization` |
| Grupa | Dział albo zespół, któremu udostępnia się agentów, skille i wiedzę | `group` |
| Lider | Członek grupy, który decyduje, kto jeszcze do niej należy | `is_lead` |
| Zatwierdzenie | Wywołanie narzędzia czekające, aż człowiek na nie pozwoli | `approval` |
| Budget | Limit wydatków, który zatrzymuje runy po osiągnięciu | `budget` |
| Zabezpieczenia | Kontrole, które redagują albo blokują to, co przepływa przez run | `guardrails` |
| Vault | Miejsce na klucze i tokeny, zapieczętowane i nigdy więcej niepokazywane | `secret` |

## Capabilities { #capabilities }

Nazwa, którą pokazuje Builder, i id, które wiąże spec agenta. Każda jest opisana
w [Capabilities](capabilities.md).

| W konsoli | W spec |
|---|---|
| Aplikacje | `artifacts` |
| Pytania do użytkownika | `ask_user` |
| Przeglądarka (krok po kroku) | `browser_choice` |
| Przeglądarka | `browser_use` |
| Informacje o kanale czatu | `channel_tools` |
| Wykresy | `charts` |
| Data i godzina | `clock` |
| Obliczenia | `code_execution` |
| Długie rozmowy | `compaction` |
| Kontekst | `context` |
| Poprzednie rozmowy | `conversation_search` |
| Zabezpieczenia | `guardrails` |
| Generowanie obrazów | `image_generation` |
| Wyszukiwanie wiedzy | `knowledge` |
| Odciążenie z obrazów | `media` |
| Pamięć | `memory_files` |
| Pamięć (mem0) | `memory_mem0` |
| Planowanie | `planning` |
| Sandbox | `sandbox` |
| Skille | `skills` |
| Delegowanie | `subagents` |
| Przypomnienia instrukcji | `system_reminders` |
| Myślenie | `thinking` |
| Limity wyników narzędzi | `tool_output_limits` |
| Wyszukiwanie narzędzi | `tool_search` |
| Czytanie stron | `web_fetch` |
| Wyszukiwanie w internecie | `web_research` |
