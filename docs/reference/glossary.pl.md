---
source_sha: "31af61187b6b"
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
| Pierwsze wiadomości | To, co pusty czat proponuje komuś, kto otwiera agenta, każda jednym kliknięciem | `starters` |
| Capability | Coś, co agent może robić, włączane w Builderze | `capabilities[]` |
| Skill | Wiedza praktyczna zapisana raz i czytana przez każdego agenta, który jej potrzebuje | `skill` |
| Kontekst | Stała wiedza, którą agent zawsze ma, np. słownik albo polityka | `context` |
| Baza wiedzy | Dokumenty, które agent przeszukuje i cytuje | `collection` |
| Luka w wiedzy | Temat pytań, na które baza wiedzy nie znała odpowiedzi, pogrupowanych według znaczenia; Popraw liczy je jako **Braki w bazie wiedzy** | `knowledge_gap_topic` |
| Aplikacja | Strona, którą publikuje agent, np. raport albo mały dashboard | `artifact` |
| Architekt | Asystent w rogu każdej strony, który może budować z tobą agentów | `platform-assistant` |
| Agent systemowy | Agent, którego uruchamia sama platforma, na przykład sędzia, autor szkiców luk albo klasyfikator luk; wymieniony osobno w sekcji **Agenci systemowi** | `kind` inny niż `agent` |
| Asystent tworzenia | Sugeruje zmiany w agencie, skillu albo pliku kontekstowym na podstawie negatywnie ocenionych odpowiedzi; o każdej decyduje człowiek | `authoring` |
| Sugestia | Jedna proponowana zmiana w drafcie, przyjmowana, edytowana albo odrzucana osobno | `spec_proposal_hunk` |
| Zmiana ustawienia | Sugestia zmiany jednej części konfiguracji agenta, na przykład modelu albo capability | hunk `spec_field` |
| Zmiana pliku kontekstowego | Nowa treść pliku kontekstowego zaproponowana przez asystenta, stosowana albo odrzucana na stronie Context | `context_proposal` |
| AgenticOS | Agent ogólnego przeznaczenia, z którym nowa organizacja zaczyna w Chat, i to, od czego zaczyna nowy agent | `general/agenticos` |

## Gdzie to działa { #where-it-runs }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Czat | Rozmowa z agentem w przeglądarce | `conversation` |
| Kanał | Slack, Telegram albo Mattermost, gdzie ludzie piszą do agenta | `channel_bot` |
| Rutyna | Agent działający sam, według harmonogramu albo zdarzenia | `trigger` |
| Suita ewaluacji | Dataset, na którym sprawdzany jest agent, uruchamiany według harmonogramu, po publikacji albo promocji, albo po zmianie | `eval_suite` |
| Run | Jedna odpowiedź agenta, z jej kosztem i krokami | `agent_run` |
| Środowisko | Nazwany etap, np. produkcja, wskazujący jedną wersję | `environment` |
| Strażnik | Suita ewaluacji, która musi przejść na wersji, zanim środowisko ją przyjmie | `guard_suite_ids` |
| Pominięcie | Promocja z pominięciem strażników, którzy nie przeszli, z podanym powodem | `override_reason` |
| Serwer MCP | Zewnętrzny serwer narzędzi, z którego korzystają agenci, podłączony raz | `mcp_connection` |
| Zdalny agent | Agent innego dostawcy, osiągalny przez A2A, do którego delegują agenci | `external_agent` |
| Agent2Agent (A2A) | Protokół, przez który agenci innych systemów wysyłają agentowi zadania | `a2a_enabled` |
| Sandbox | Odizolowany komputer, na którym agent zapisuje pliki i uruchamia kod | `sandbox` |
| Dokumenty | Pliki, które agenci trzymają dla człowieka, załączone lub napisane, w swoich sandboxach | `workspace` |

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
| Wsparcie AI | Przełącznik organizacji dla modeli, które oceniają odpowiedzi, przygotowują przypadki, proponują zmiany i szkicują brakującą wiedzę, także w Popraw; wyłączone, dopóki ktoś go nie włączy | `ai_assistance_enabled` |

## Jak to jest testowane { #how-it-is-tested }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Dataset | Wersjonowane przypadki testowe, z którymi porównuje się odpowiedzi agenta; w Popraw to **Pytania testowe** | `dataset` |
| Przypadek | Jedno pytanie i to, z czym porównuje się dobrą odpowiedź; w Popraw to pytanie testowe | `dataset_case` |
| Ocenianie | Jak oceniane są odpowiedzi w datasecie: sprawdzenia, odpowiedź wzorcowa i sędzia | `scoring` |
| Kryterium | Jedna rzecz, którą sędzia ocenia w każdej odpowiedzi, na skali albo jako tak lub nie | `criteria[]` |
| Reguła | Sprawdzenie, które odpowiedź przechodzi albo nie bez żadnego modelu, np. fraza, wzorzec albo długość; wymienione w **Sprawdzenia** | `checks[]` |
| Sędzia | Agent oceniający odpowiedzi w ewaluacjach; uruchamia go tylko platforma | `kind: judge` |
| Model oceniający | Model, na którym oceniają nowi sędziowie, wybierany raz dla organizacji | `grading_model_profile_id` |
| Ewaluacja | Agent odpowiadający na każdy przypadek datasetu, oceniony i porównany z wcześniejszą wersją | `eval_run` |
| Potwierdzona regresja | Przypadek, który wcześniej przechodził, a w każdej powtórce znów nie przechodzi; Popraw mówi **Nowo zepsute** | `flip: regression`, `confirmed: true` |
| Potwierdzona naprawa | Przypadek, który wcześniej nie przechodził, a w każdej powtórce znów przechodzi; Popraw mówi **Nowo naprawione** | `flip: fixed`, `confirmed: true` |
| Niepotwierdzona | Przypadek, który zmienił się raz, ale przy powtórce już nie tak samo, więc nie liczy się ani jako regresja, ani jako naprawa; Popraw pokazuje go w **Jeszcze niepotwierdzone** | `confirmed: false` |
| Szum | Odpowiedzi ocenione inaczej przy ponownym pytaniu, choć nic się nie zmieniło; wynik, który da się nim wyjaśnić, mieści się w szumie, a **Zadaj każde pytanie dwa razy** go mierzy | `measurement_noise`, `purpose: stability` |
| Przegląd | Wyniki czekające, aż człowiek je potwierdzi albo zmieni | `review_state` |
| Generator przypadków | Agent systemowy, który przygotowuje przypadki z agenta, jego wiedzy, prawdziwych czatów i red teamingu | `kind: generator` |
| Proponowany przypadek | Przygotowany przypadek czekający w **Wygenerowane**, aż człowiek go zaakceptuje albo odrzuci | `case_proposal` |
| Red teaming | Przypadki sprawdzające, czy agent odmawia tego, czego musi odmówić | tag `red-team` |

## Jak to jest poprawiane { #how-it-is-improved }

| W konsoli | Co to jest | W API i spec |
|---|---|---|
| Popraw | Sesja, która odczytuje, co poszło nie tak z agentem, pisze zmiany i je testuje, a między krokami czeka na człowieka; sama nigdy niczego nie publikuje | `improvement` |
| Zrozumienie | Pierwszy krok: dzieli odpowiedzi z ocenami na to, co agent może poprawić, i to, czego brakuje w bazie wiedzy | `stage: analyzing`, `stage: classifying` |
| Zmiany | Krok, w którym pomocnik pisze zmiany próby, a ty wybierasz, które przetestować | `stage: proposing`, `stage: filtering` |
| Sprawdzenie | Krok, w którym dzisiejsza i zmieniona wersja odpowiadają na te same pytania i obie są oceniane; **Otwórz pełne sprawdzenie** otwiera jego run ewaluacji | `stage: evaluating`, `stage: judging` |
| Wynik | Do czego doszła sesja: która próba poprawiła agenta albo że żadna, i co można zrobić dalej | `status: ready`, `status: stopped` |
| Akceptacja | Ostatni krok: **Opublikuj wersję N** albo **Zachowaj jako wersję roboczą**; każde z nich kończy sesję | `POST /{run_id}/finish` |
| Próba | Jedno podejście w sesji: zmiany napisane, a potem sprawdzone na własnych pytaniach; najwyżej trzy na sesję | `improvement_iteration` |
| Agent, który pisze zmiany | Agent, który czyta oceny i pisze zmiany każdej próby; asystent tworzenia, chyba że wybrano innego | `improver_agent_id` |
| Odłożone | Pytania testowe, które próba odkłada, żeby pomocnik ich nie widział, a o jej wyniku decydowały tylko one | `improvement_partition: holdout` |
| Pomagają napisać zmiany | Pytania testowe, które pomocnik czyta, pisząc zmiany próby; nigdy nie decydują o jej wyniku | `improvement_partition: train` |
| Spróbuj ponownie | Zaczyna z wyniku kolejną próbę, z polem **Notatka dla pomocnika** (opcjonalnie); próba pisze nowe zmiany i zatrzymuje się na kroku **Zmiany** | `/{run_id}/continue` z `note` |
| Limit wydatków | Ile sesja może wydać łącznie, z analizą i każdą próbą; każdy krok jest wyceniany, zanim się zacznie | `budget_usd` |
| Automatyczne sprawdzenie | **Sprawdzaj te pytania automatycznie przy każdej zmianie**: przy akceptacji suita, która zadaje pytania sesji przed każdą publikacją i nie dopuszcza żadnej potwierdzonej regresji | `automatic_check` |

## Capabilities { #capabilities }

Nazwa, którą pokazuje Builder, i id, które wiąże spec agenta. Każda jest opisana
w [Capabilities](capabilities.md).

| W konsoli | W spec |
|---|---|
| Aplikacje | `artifacts` |
| Pytania do użytkownika | `ask_user` |
| Przeglądarka | `browser_use` |
| Informacje o kanale czatu | `channel_tools` |
| Wykresy | `charts` |
| Data i godzina | `clock` |
| Obliczenia | `code_execution` |
| Coding agent | `coding_agent` |
| Długie rozmowy | `compaction` |
| Kontekst | `context` |
| Poprzednie rozmowy | `conversation_search` |
| Następne kroki | `follow_ups` |
| Zabezpieczenia | `guardrails` |
| Generowanie obrazów | `image_generation` |
| Wyszukiwanie wiedzy | `knowledge` |
| Odciążenie z obrazów | `media` |
| Pamięć | `memory_files` |
| Pamięć (mem0) | `memory_mem0` |
| Planowanie | `planning` |
| Praca w trakcie narzędzi | `background_tools` |
| Sandbox | `sandbox` |
| Skille | `skills` |
| Subagenci | `subagents` |
| Przypomnienia instrukcji | `system_reminders` |
| Zamiana tekstu na mowę | `text_to_speech` |
| Myślenie | `thinking` |
| Limity wyników narzędzi | `tool_output_limits` |
| Wyszukiwanie narzędzi | `tool_search` |
| Generowanie wideo | `video_generation` |
| Wizualizacje | `visuals` |
| Czytanie stron | `web_fetch` |
| Wyszukiwanie w internecie | `web_research` |
