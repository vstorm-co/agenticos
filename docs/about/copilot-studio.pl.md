---
source_sha: "b7162a5c58d3"
title: "AgenticOS vs Copilot Studio"
seo_title: "AgenticOS vs Copilot Studio: alternatywa self-hosted"
description: "Porównaj Microsoft Copilot Studio z AgenticOS: bez Copilot Credits, dowolny provider modeli, własna infrastruktura, budżety per agent i otwarty audyt."
---

# AgenticOS vs Copilot Studio { #agenticos-vs-copilot-studio }

Microsoft Copilot Studio buduje agentów wewnątrz Power Platform. Ma konektory Power Platform, publikowanie w Teams i Microsoft 365 oraz zarządzanie przez Purview i Entra, wszystko w chmurze Microsoftu i rozliczane w Copilot Credits. AgenticOS buduje agentów na twojej własnej infrastrukturze, z dowolnym providerem modeli, i nie pobiera własnej opłaty: płacisz providerowi za model.

Jeśli twoja firma żyje w Microsoft 365, Copilot Studio jest naturalnym kandydatem. AgenticOS jest kandydatem, gdy chcesz być właścicielem platformy, trzymać dane tam, gdzie wybierzesz, i uniknąć licznika naliczanego za każdą funkcję.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 25 września 2026. Wersja bazowa AgenticOS: v0.0.504. Zakres Copilot Studio: strona Microsoftu z cennikiem, API cen detalicznych Azure i Microsoft Learn, bez testowanego tenanta.

## W skrócie { #at-a-glance }

| Obszar | Copilot Studio | AgenticOS |
| --- | --- | --- |
| Gdzie działa | Chmura Microsoftu, w środowiskach Power Platform | Twoja infrastruktura |
| Kod | Własnościowy | Apache-2.0 |
| Modele | Domyślnie modele GPT, modele Claude ogólnie dostępne, modele Azure Foundry rozliczane osobno | 27 providerów, w tym lokalne |
| Rozliczenie | 200 USD miesięcznie za 25 000 Copilot Credits albo 0,01 USD za kredyt w modelu pay-as-you-go | Brak opłaty licencyjnej; użycie modeli według stawek twojego providera |
| Jak liczone jest użycie | Kredyty za funkcję: odpowiedź generatywna to 2, akcja agenta 5, ugruntowanie w grafie tenanta 10 | Tokeny modelu, wyceniane według providera |
| Egzekwowanie wydatków | Miesięczne limity na agenta; agenci są wyłączani przy 125% przedpłaconej puli | Budżet na agenta i na organizację, sprawdzany przed każdym zapytaniem do modelu |
| Powierzchnie | Teams, Microsoft 365, SharePoint, strona internetowa, WhatsApp, głos oraz Slack lub Telegram przez Azure Bot Service | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Telegram, Mattermost |
| Tożsamość | Microsoft Entra ID | OIDC SSO, w tym Entra, LDAP i Kerberos |
| Zarządzanie | Polityki danych Power Platform, audyt Purview, Entra Agent ID | Katalog uprawnień, uprawnienia do zasobów, zatwierdzenia i log audytowy wykrywający manipulacje |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Rachunek przewidywalny z ceny modelu { #a-bill-you-can-predict-from-the-model-price }

Copilot Studio nalicza kredyty za każdą funkcję, dolicza stawkę premium za modele rozumujące i rozlicza swój nowszy harness GitHub Copilot od chwili, gdy zaczynasz budować. AgenticOS zapisuje własny koszt modelu przy [każdym runie](../governance.md#what-run-history-shows) na podstawie dołączonego zestawu cen. Model zbyt nowy dla zestawu cen zapisywany jest jako [częściowo wyceniony](../models.md#what-a-run-costs), a provider hostowany samodzielnie bez klucza nie zapisuje żadnego wydatku. [Budżet](../governance.md#budgets) agenta jest sprawdzany [przed każdym zapytaniem do modelu](../governance.md#enforcement-is-before-the-request), zamiast wyłączać agenta, gdy wyczerpie się pula.

### Dowolna chmura albo żadna { #any-cloud-or-none }

Copilot Studio działa w chmurze Microsoftu. Microsoft zaznacza, że modele Anthropic są poza EU Data Boundary i domyślnie wyłączone w UE, EFTA i Wielkiej Brytanii. AgenticOS działa tam, gdzie go wdrożysz. Możesz wybrać providera w potrzebnym regionie albo [uruchomić model samodzielnie](../models.md#self-hosted), tak że prompty nigdy nie opuszczają twojej sieci.

### Każdy provider modeli na równych prawach { #every-model-provider-first-class }

Standardowy harness Copilot Studio oferuje modele GPT i Claude, a do własnych modeli Azure Foundry, rozliczane osobno. AgenticOS traktuje [27 providerów](../models.md#providers) jednakowo. Mają wspólny format [profilu modelu](../models.md#a-model-profile), te same [fallbacki](../models.md#fallbacks) i ten sam zapis kosztów.

### Otwarty tam, gdzie to ważne dla audytora { #open-where-it-matters-to-an-auditor }

Zarządzanie w Copilot Studio jest mocne wewnątrz stosu Microsoftu. AgenticOS pozwala przeczytać same kontrole: [katalog uprawnień](../permissions.md), [vault](../secrets.md#envelope-encryption), [łańcuch haszy audytu](../governance.md#audit) i [testy odmów](../security.md#the-refusals-as-a-set) w CI. Spec [eksportuje się do YAML](../features.md#exportable-into-your-own-repository), więc odejście oznacza zachowanie agentów, a nie budowanie ich od nowa.

### Tożsamość Microsoftu bez hostingu Microsoftu { #microsoft-identity-without-microsoft-hosting }

AgenticOS loguje użytkowników przez Entra ID po [OIDC](../configuration.md#single-sign-on-generic-oidc), mapuje [grupy katalogowe](../directory.md#the-groups-claim-over-oidc) na role i czyta pliki z [SharePoint i OneDrive](../howto/configure-sync-sources.md#sharepoint-and-onedrive-setup). Microsoft zostaje źródłem tożsamości i dokumentów, a agentów uruchamiasz sam.

## Kiedy Copilot Studio pasuje lepiej { #when-copilot-studio-is-the-better-fit }

- Twoi agenci mają działać w Teams i Microsoft 365 Copilot, a twoi użytkownicy mają już licencje Microsoft 365 Copilot.
- Potrzebujesz konektorów Power Platform, agent flows, głosu lub WhatsAppa. AgenticOS nie ma kanału Teams, głosowego ani WhatsApp.
- Purview, Sentinel i polityki danych Power Platform to sposób, w jaki twoja organizacja zarządza wszystkim innym.

## Wypróbuj na jednym zadaniu { #try-it-on-one-task }

Zbuduj [wspólnego agenta dokumentowego](../howto/first-document-agent.md) w obu, na porównywalnych modelach. Zadaj sto pytań i porównaj rachunek: kredyty po jednej stronie, koszt modelu po drugiej. Wybierz model objęty zestawem cen, aby wynik AgenticOS był kompletny. Następnie sprawdź, co się dzieje po osiągnięciu limitu. Zapisz wynik według [metody porównania](comparison.md#a-shared-trial).

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Czy AgenticOS to alternatywa dla Microsoft Copilot Studio? { #is-agenticos-an-alternative-to-microsoft-copilot-studio }

Tak, jeśli chcesz mieć platformę na własność. AgenticOS działa na twojej infrastrukturze z dowolnym providerem modeli i bez licznika kredytów. Copilot Studio pasuje lepiej, gdy agenci żyją w Teams i Microsoft 365.

### Czy AgenticOS działa z Microsoft Entra ID i SharePoint? { #does-agenticos-work-with-microsoft-entra-id-and-sharepoint }

Tak. Użytkownicy logują się przez Entra ID po OIDC, grupy katalogowe mapują się na role, a kolekcje synchronizują pliki z SharePoint i OneDrive.

### Ile kosztuje Copilot Studio w porównaniu z AgenticOS? { #how-much-does-copilot-studio-cost-compared-with-agenticos }

Copilot Studio sprzedaje 25 000 Copilot Credits za 200 USD miesięcznie albo po 0,01 USD za kredyt w modelu pay-as-you-go. AgenticOS nie ma własnej opłaty; płacisz providerowi modeli za tokeny zużyte przez agenta.

### Czy AgenticOS publikuje agentów w Microsoft Teams? { #can-agenticos-publish-agents-to-microsoft-teams }

Jeszcze nie. Publikuje w czacie webowym, widgecie, na hostowanej stronie, przez HTTP API, WebSocket, w Slacku, Telegramie i Mattermost.

## Powiązane porównania { #related-comparisons }

[AgenticOS vs Gemini Enterprise](gemini-enterprise.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs n8n](n8n.md) · [Wszystkie porównania](comparison.md)

## Źródła { #sources }

- [Cennik Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/pricing/copilot-studio): pakiet kredytów i pay-as-you-go.
- [Ceny detaliczne Azure](https://prices.azure.com/api/retail/prices?$filter=contains(productName,'Copilot%20Studio')): 0,01 USD za kredyt.
- [Stawki i zarządzanie rozliczeniami](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management): kredyty za funkcję, limity na agenta i egzekwowanie przy 125%.
- [Harnessy](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview) i [rozliczanie harnessów](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/billing-credit-overview): rozliczanie od etapu budowania.
- [Wybór modelu](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-select-agent-model): dostępne modele.
- [Anthropic jako podprocesor](https://learn.microsoft.com/en-us/microsoft-365/copilot/connect-to-ai-subprocessor): wyłączenie z EU Data Boundary.
- [Kanały publikacji](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-fundamentals-publish-channels): powierzchnie i uwierzytelnianie.
