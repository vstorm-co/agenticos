---
source_sha: "2ca7dda133d2"
title: "AgenticOS vs Viktor"
description: "Porównanie jednego zarządzanego współpracownika AI na workspace z platformą wersjonowanych agentów, którą utrzymuje Twój zespół."
---

# AgenticOS vs Viktor { #agenticos-vs-viktor }

Viktor sprzedaje jednego współpracownika AI na workspace Slacka lub Microsoft Teams, działającego w jego chmurze i rozliczanego w kredytach. AgenticOS daje tylu agentów, ilu potrzebujesz, każdego z własnymi instrukcjami, modelem, narzędziami, wiedzą, budżetem i regułami dostępu, na infrastrukturze, którą kontrolujesz.

Jeśli chcesz jeszcze dziś po południu mieć na czacie jednego pomocnego kolegę, Viktora można szybko wypróbować. Jeśli chcesz decydować, co może każdy agent, ile kosztuje i gdzie leżą dane, AgenticOS daje Ci tę kontrolę.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 25 września 2026. Wersja bazowa AgenticOS: v0.0.504. Zakres Viktor: jego publiczne strony produktu, cennika, bezpieczeństwa i oferty enterprise oraz changelog, a nie przetestowane konto ani negocjowana umowa.

## W skrócie { #at-a-glance }

| Obszar | Viktor | AgenticOS |
| --- | --- | --- |
| Co dostajesz | Jednego wspólnego „pracownika AI” na workspace | Dowolną liczbę agentów, każdy jako wersjonowany spec |
| Gdzie działa | Chmura Viktor, hostowana w AWS us-east-1 | Twoja infrastruktura, z Docker Compose |
| Źródła | Własnościowe | Apache-2.0 |
| Modele | Presety OpenAI, Anthropic, Google i Kimi; własny klucz OpenRouter | 27 providerów, w tym Ollama i LiteLLM na Twoim sprzęcie |
| Wiedza | Pamięć workspace'u i podłączone narzędzia | Kolekcje dokumentów w Twoim Postgresie, z pięcioma konektorami synchronizacji |
| Powierzchnie | Slack, Teams, Discord, własna skrzynka e-mail, aplikacje web, desktop i mobilne, API | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Telegram, Mattermost |
| Dostęp | Na poziomie workspace'u; jego strony różnią się w opisie dostępu opartego na rolach | Sześć ról, 27 uprawnień i granty per zasób, w każdej organizacji |
| Kontrola wydatków | Pula kredytów; limity dopasowywane w planie Enterprise | Miesięczny budżet per agent i per organizacja, sprawdzany przed każdym żądaniem do modelu |
| Ceny | Od $50 miesięcznie za 20 000 kredytów, stałe $2,50 za 1000 kredytów | Bez opłaty licencyjnej; płacisz providerom modeli i za infrastrukturę |
| Dowody zgodności | SOC 2 Type 1; Type II i ISO 27001 w toku | Twoje kontrole na Twojej infrastrukturze; zobacz [bezpieczeństwo](../security.md) |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Wielu agentów, każdy z własnym zadaniem { #many-agents-each-with-a-job }

Viktor to jeden współpracownik, którego dzieli cały workspace. W AgenticOS każdy agent jest budowany do własnego zadania, na przykład agent polityk HR, asystent sprzedaży albo agent do triażu zgłoszeń supportu. Każdy ma własne instrukcje, [capabilities](../reference/capabilities.md), kolekcje wiedzy i budżet.

Spec agenta jest [wersjonowany przy publikacji](../concepts.md#version) i [eksportuje się jako YAML](../features.md#exportable-into-your-own-repository) do Twojego repozytorium git. Nazwane [środowiska](../environments.md#what-an-environment-is) pozwalają przetestować wersję na stagingu, zanim zacznie nią odpowiadać produkcja.

### Dostęp decydowany per agent i per osoba { #access-decided-per-agent-and-per-person }

FAQ na stronie głównej Viktora, sprawdzone 25 września 2026, mówi, że plan dzieli jedną instancję Viktora i jeden kontekst, a podłączona integracja jest dostępna dla każdego członka zespołu. Jego strona enterprise wymienia dostęp oparty na rolach. Zapytaj, co dotyczy Twojej umowy.

W AgenticOS dostęp wynika z [katalogu uprawnień](../permissions.md#the-built-in-roles), a [granty](../permissions.md#layer-3-visibility-and-grants) udostępniają jednego agenta, skill albo kolekcję osobie lub grupie. Powiązanie MCP może korzystać z [własnego konta każdej osoby](../mcp.md#whose-account-a-binding-speaks-through) zamiast jednego wspólnego loginu. Połączony użytkownik Slacka działa [jako on sam](../channels.md#slack).

### Budżet per agent, nie tylko pula kredytów { #a-budget-per-agent-not-only-a-credit-pool }

Viktor rozlicza pulę kredytów workspace'u i podaje, że kredyty odpowiadają temu, ile pobierają providerzy modeli. AgenticOS nie ma kredytów. Każdy agent ma [miesięczny budżet](../governance.md#budgets) sprawdzany [przed każdym żądaniem do modelu](../governance.md#enforcement-is-before-the-request). Nieudany run także zapisuje swój koszt, a [alert](../governance.md#alerts) powiadamia wybrane przez Ciebie osoby, gdy agent dojdzie do limitu.

### Twoje dane zostają tam, gdzie je umieścisz { #your-data-stays-where-you-put-it }

Viktor jest hostowany w USA. Jego strony różnią się w kwestii rezydencji danych w UE i konfigurowalnej retencji, więc potwierdź oba punkty na piśmie. AgenticOS przechowuje rozmowy, dokumenty i wektory w [Twoim własnym Postgresie](../data-protection.md#where-personal-data-lives). Ustawiasz [retencję per klasa danych](../governance.md#retention). Z lokalnym modelem nic nie musi opuszczać Twojej sieci.

### Wiedza, którą możesz sprawdzić { #knowledge-you-can-inspect }

Viktor uczy się z rozmów i podłączonych narzędzi. AgenticOS dodaje zarządzane kolekcje dokumentów: dla każdej kolekcji wybierasz [parser](../file-processing.md#parser-selection-rag) i [chunking](../file-processing.md#chunking-configuration). Możesz synchronizować z Google Drive, S3, SharePoint lub OneDrive, ze strony internetowej albo z repozytorium git. Synchronizacja [usuwa dokumenty](../howto/configure-sync-sources.md#what-a-sync-removes), których źródło już nie wymienia.

## Kiedy Viktor wystarczy { #when-viktor-is-enough }

- Chcesz jednego asystenta w Slacku lub Teams bez żadnej infrastruktury do utrzymania.
- Jego katalog ponad 3200 integracji OAuth i jego sandbox do kodu pokrywają Twoje zadania.
- Rozliczanie w kredytach i hosting w USA spełniają Twoje wymagania.
- Potrzebujesz dziś Microsoft Teams, głosu albo skrzynki e-mail. AgenticOS nie ma jeszcze kanału rozmów przez Teams, głos ani e-mail.

## Wypróbuj jedno pytanie o podręcznik { #try-one-handbook-question }

Użyj [wspólnego przykładu dokumentu](../howto/first-document-agent.md). Porównaj dostęp do źródła, faktyczną odpowiedź, pytanie o brakującą zasadę i aktualizację źródła. Sprawdź, która tożsamość może pobrać źródło i jak odbiera się dostęp, gdy ktoś odchodzi.

Następnie w każdym produkcie uruchom drugiego agenta dla innego zespołu. Sprawdź, czy widzi integracje i pamięć pierwszego zespołu. To na tym drugim agencie współpracownik workspace'u i platforma agentów różnią się najbardziej. Zapisz wynik według [metody porównania](comparison.md#a-shared-trial).

## Źródła { #sources }

- [Strona produktu i FAQ Viktora](https://viktor.com/): pozycjonowanie, wspólna instancja workspace'u, integracje dzielone w całym zespole, RBAC na roadmapie.
- [Cennik](https://viktor.com/pricing): plany kredytowe, brak opłaty za stanowisko, koszt modeli przenoszony na klienta.
- [Bezpieczeństwo](https://viktor.com/security): AWS us-east-1, SOC 2 Type 1, ISO 27001 w toku, zatwierdzenia, SAML SSO w planie Enterprise.
- [Enterprise](https://www.viktor.com/enterprise.md): tożsamość natywna dla czatu, deklaracje o rezydencji danych w UE i retencji, umowy roczne.
- [Changelog](https://www.viktor.com/changelog.md): klucze OpenRouter, logi audytowe w Enterprise, Discord i e-mail.
