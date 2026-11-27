---
title: "AgenticOS vs Dust"
seo_title: "AgenticOS vs Dust: agenci hostowani czy na Twoich serwerach"
description: "Porównaj Dust i AgenticOS: francuski SaaS dla agentów firmy a platforma na Apache-2.0, którą hostujesz. Hosting, limity wydatków, audyt, kanały i ceny."
source_sha: "be4cedd13c05"
---

# AgenticOS vs Dust { #agenticos-vs-dust }

Dust nazywa się wieloosobowym systemem operacyjnym dla AI w firmie: agenci, którzy pracują na danych firmy, z MCP jako klientem i serwerem, oraz agenci w Slacku, Microsoft Teams, e-mailu i Zendesku. To usługa hostowana w regionie USA albo UE, z hostingiem single-tenant w Enterprise. AgenticOS oferuje agentów dla tego samego kupca na infrastrukturze, którą utrzymujesz sam, na Apache-2.0, bez opłaty za stanowisko.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 26 listopada 2026. Wersja bazowa AgenticOS: v1.95.0. Zakres Dust: strona produktu, cennik, dokumentacja dla administratorów i doniesienia prasowe o finansowaniu z maja 2026, a nie przetestowany workspace.

## W skrócie { #at-a-glance }

| Obszar | Dust | AgenticOS |
| --- | --- | --- |
| Czym jest | Hostowany workspace dla agentów firmy na danych firmy | Platforma dla agentów firmy, workflow, aplikacji i tabel, którą uruchamiasz u siebie |
| Licencja | Własnościowa | Apache-2.0; zobacz [licencje dołączonych komponentów](../licenses.md) |
| Gdzie działa | Chmura Dust, region USA albo UE; single-tenant w Enterprise; bez self-hostingu | Twoja infrastruktura, dowolna chmura albo on-premises |
| Modele | Kilku providerów | 28 providerów, w tym lokalni |
| Kontrola wydatków | Limity kredytów per osoba, grupa i klucz API, sprawdzane przed każdą wiadomością | Miesięczny budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu |
| Audyt | Wykrywający manipulacje w Enterprise | Log audytowy wykrywający manipulacje w każdym wdrożeniu |
| MCP | Klient i serwer | Klient i [serwer](../mcp.md#agenticos-as-an-mcp-server) |
| Kanały | Web, Slack, Microsoft Teams, e-mail, Zendesk | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, e-mail, iMessage, połączenia telefoniczne |
| Cennik | Pro 24 €, Max 120 € za użytkownika miesięcznie przy płatności rocznej; Enterprise indywidualnie | Bez opłaty licencyjnej i za stanowisko; użycie modeli po stawkach providera |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Hosting, który wybierasz { #hosting-you-choose }

Dust działa tylko we własnej chmurze. AgenticOS działa [tam, gdzie go wdrożysz](../deploy.md), także on-premises i w sieci odizolowanej, z lokalnymi modelami, jeśli Twoje dane nie mogą wyjść. Zobacz [co domyślnie wychodzi](../data-protection.md#nothing-leaves-by-default).

### Limity na agencie, nie tylko na osobie { #limits-on-the-agent-not-only-on-the-person }

Dust limituje kredyty per osoba, grupa i klucz API. AgenticOS limituje też każdego agenta: [miesięczny budżet](../governance.md#budgets) sprawdzany [przed każdym wywołaniem modelu](../governance.md#enforcement-is-before-the-request), więc agent, który się zapętli albo jest intensywnie używany, zatrzymuje się na własnym limicie i nikogo innego nie blokuje.

### Governance w produkcie open source { #governance-in-the-open-source-product }

[Log audytowy wykrywający manipulacje](../governance.md#audit), [zatwierdzenia](../governance.md#approvals), [logowanie przez katalog](../directory.md#signing-in-with-a-directory-account) i [wiele organizacji](../concepts.md#organizations) są w każdym wdrożeniu AgenticOS, a nie zarezerwowane dla kontraktu enterprise.

### Bez opłaty za stanowisko { #no-seat-fee }

Dust pobiera opłatę za użytkownika. AgenticOS nie pobiera nic za użytkownika; płacisz providerom modeli i utrzymujesz infrastrukturę, sam albo z Vstorm.

## Kiedy Dust pasuje lepiej { #when-dust-is-the-better-fit }

- Chcesz zarządzanej usługi, która startuje w kilka minut, i nie masz zespołu do utrzymania serwerów.
- Jego konektory i integracja z Zendeskiem obejmują Twoje systemy.
- SAML i SCIM są wymagane; AgenticOS nie ma jeszcze żadnego z nich.

## Porównaj zmianę, nie tylko odpowiedź { #compare-a-change-not-only-an-answer }

Zbuduj tego samego agenta na tych samych dokumentach w obu produktach. Ogranicz wydatki agenta do kilku centów i sprawdź, co dzieje się na granicy. Potem zapytaj swój zespół bezpieczeństwa, który z dwóch może zatrzymać wszystkie prompty i dokumenty w Twojej sieci. Zapisz wyniki według [metody porównania](comparison.md#a-shared-trial).

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Czy Dust można hostować samodzielnie? { #can-dust-be-self-hosted }

Nie według jego publicznych stron: działa w chmurze Dust, w regionie USA albo UE, z hostingiem single-tenant w Enterprise. AgenticOS jest z założenia hostowany samodzielnie.

### Czy Dust ma limity wydatków? { #does-dust-have-spend-limits }

Tak, limity kredytów per osoba, grupa i klucz API, sprawdzane przed każdą wiadomością. AgenticOS dodaje budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu.

## Powiązane porównania { #related-comparisons }

[AgenticOS vs Langdock](langdock.md) · [AgenticOS vs deepset](deepset.md) · [Agenci w Slacku](slack-agents.md) · [Wszystkie porównania](comparison.md)

## Źródła { #sources }

- [Dust](https://dust.tt) i [cennik](https://dust.tt/pricing): opis produktu, regiony hostingu i plany.
- [Zarządzanie kredytami](https://docs.dust.tt/docs/user-documentation/admins/usage-seats-and-credits/credit-management): limity kredytów per osoba, grupa i klucz API.
- [Dust pozyskuje 40 mln USD w serii B](https://tech.eu/2026/05/18/dust-raises-40m-series-b-to-build-the-multiplayer-operating-system-for-enterprise-ai/): opis „wieloosobowego systemu operacyjnego”.
