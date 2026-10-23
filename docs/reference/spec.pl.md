---
source_sha: "892833d0bab5"
---

# Spec agenta { #the-agent-spec }

Najbardziej nośny typ na całej platformie: Builder go edytuje, baza danych
wersjonuje, factory tworzy z niego instancje, a klienci eksportują go jako YAML
do własnych repozytoriów git.

Generowany ze źródła, bo uzasadnienie mieszka w docstringach — i dlatego
wygenerowana niżej dokumentacja pól pozostaje po angielsku.

::: app.agents.spec.AgentSpec

## Zmienne { #variables }

`{{nazwa}}` w `instructions` jest uzupełniane na początku każdego runa: zmienną
systemową, którą zna platforma (data i godzina, zalogowana osoba i jej
[grupy](../departments.md), organizacja, agent, kanał), albo jedną z własnych `variables` agenta. `time_zone` decyduje,
który zegar czyta `{{current_time}}`. Publikacja odrzuca nazwę, która nie jest
żadną z nich.

::: app.agents.spec.PromptVariableSpec

## Delegowanie { #delegation }

Dwie formy, a [Koncepcje](../concepts.md#delegate-vs-inline-specialist)
wyjaśniają, po którą sięgnąć. `subagents` trzyma pierwszą; druga mieszka w
konfiguracji samej [capability `subagents`](capabilities.md#delegation).

::: app.agents.spec.SubagentRef

`external_agents` wskazuje zdalnych agentów A2A zarejestrowanych w organizacji, których
[delegowanie](capabilities.md#remote-agents) wywołuje obok powyższych.

::: app.agents.spec.ExternalAgentRef

::: app.agents.spec.SpecialistSpec

## Budżety { #budgets }

::: app.agents.spec.BudgetSpec

## Alerty { #alerts }

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Ustawienia modelu { #model-settings }

::: app.agents.spec.ModelSettingsSpec

## Observability { #observability }

::: app.agents.spec.ObservabilitySpec

## Mowa na tekst { #speech-to-text }

Provider, model, klucz i język, którymi transkrybowane są dyktowanie do agenta i
dziedziczone notatki głosowe z kanałów, tam gdzie różnią się od tych organizacji.
Klucz to identyfikator sekretu z vaultu, nigdy sam klucz.
[Usługi ML](../ml-services.md#which-engine-a-recording-reaches) opisują
kolejność, w jakiej się rozwiązują. Speca z tym blokiem nie da się zaimportować
do wdrożenia starszego niż ten blok: jego spec odrzuca pola, których nie zna.

::: app.agents.spec.SpeechToTextSpec

## Głos { #voice }

Jak agent prowadzi [rozmowę głosową](../voice.md): model realtime, klucz z
vaultu, głos i własne limity rozmowy. Blok jest opcjonalny, a blok z samymi
pustymi polami czyta się jak brak bloku, więc speci zapisane przed nim wczytują
się bez zmian, a `SPEC_VERSION` się nie przesunął. Tak jak bloku mowy na tekst,
speca z tym blokiem nie da się zaimportować do wdrożenia starszego niż ten blok.

| Pole | Co zawiera |
|---|---|
| `provider` | Provider z katalogu realtime: `openai`, `azure`, `google` albo `xai` |
| `model` | Model realtime tego providera. Dla Azure zostaw je puste i użyj dwóch pól poniżej |
| `deployment` | Tylko Azure: nazwa wdrożenia, do którego trafiają rozmowy |
| `base_model` | Tylko Azure: model z katalogu, który to wdrożenie uruchamia; od niego zależą głosy i cena |
| `secret_id` | Klucz z vaultu, którym prowadzone są rozmowy - identyfikator, nigdy sam klucz |
| `voice` | Jeden z głosów modelu; puste oznacza domyślny głos modelu |
| `language` | Kod ISO-639-1 języka, w którym mówi agent; puste dostosowuje się do rozmówcy |
| `max_call_seconds` | Najdłuższa rozmowa, od 60 do 3000; puste to 600 (10 minut) |
| `voice_note` | Do 1000 znaków dodawanych do instrukcji agenta tylko w rozmowach |

Każda reguła obejmująca kilka pól jest sprawdzana przy publikacji wersji, a nie
przy zapisie szkicu, bo Builder zapisuje automatycznie między wyborem providera
a wyborem jego modelu. Publikacja jest odrzucana, ze wskazaniem sekcji głosu,
gdy:

- brakuje providera albo katalog tego wdrożenia nie ma takiego providera;
- brakuje modelu albo nie jest on modelem realtime, który katalog oferuje dla
  tego providera (dla Azure - modelem bazowym), albo sekcja Azure nie podaje
  wdrożenia;
- głos nie jest jednym z głosów modelu;
- nie wybrano klucza albo klucz nie przechodzi wspólnego sprawdzenia: jego
  przeznaczeniem nie jest ten provider, jego rodzaj nie jest rodzajem providera
  (`api_key` albo `azure_openai` dla Azure), należy do innej organizacji albo
  publikujący go nie widzi;
- język nie jest kodem, który przyjmują rozmowy.

Capabilities, których rozmowa nie może uruchomić, nie blokują publikacji; są
pomijane w rozmowach, a Builder je wymienia.

::: app.agents.spec.VoiceSpec
