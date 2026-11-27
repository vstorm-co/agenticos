---
title: "AgenticOS vs LobeHub"
seo_title: "AgenticOS vs LobeHub: agenci w zespole, self-hosted"
description: "Porównaj LobeHub i AgenticOS: LobeHub Community License a Apache-2.0, kanały zespołu, budżety, zatwierdzenia, audyt, role i wielotenantowość."
source_sha: "277af3a6a45c"
---

# AgenticOS vs LobeHub { #agenticos-vs-lobehub }

LobeHub nazywa swój produkt „super-agentami w Twoim zespole”: agentami dodawanymi do narzędzi czatu, których zespół już używa, z workspace'em, ponad 90 providerami, MCP, pamięcią i marketem skilli. AgenticOS składa tę samą obietnicę agentów w kanałach zespołu. Różnice to licencja, governance wokół każdego agenta i liczba organizacji, które może obsłużyć jedno wdrożenie.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 26 listopada 2026. Wersja bazowa AgenticOS: v1.95.0. Zakres LobeHub: strona produktu, cennik, dokumentacja i plik `LICENSE` w `lobehub/lobehub`, a nie przetestowany workspace ani wdrożenie self-hosted.

## W skrócie { #at-a-glance }

| Obszar | LobeHub | AgenticOS |
| --- | --- | --- |
| Czym jest | Workspace AI z agentami, którzy dołączają do czatów zespołu | Konsola, w której zespół biznesowy buduje wersjonowanych agentów, workflow, aplikacje i tabele |
| Licencja | LobeHub Community License: Apache 2.0 z dodatkowymi warunkami komercyjnymi | Apache-2.0; zobacz [licencje dołączonych komponentów](../licenses.md) |
| Gdzie działa | Chmura LobeHub albo self-hosted przez Dockera | Twoja infrastruktura |
| Modele | Ponad 90 providerów | 28 providerów, w tym lokalni |
| Kanały | Discord, Slack, Telegram, LINE, WeChat, Feishu, DingTalk i inne; WhatsApp i iMessage zapowiedziane; bez Microsoft Teams | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, e-mail, iMessage, połączenia telefoniczne |
| Kontrola wydatków | Pula kredytów ze śledzeniem użycia | Miesięczny budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu |
| Zatwierdzenia | Potwierdza osoba, która korzysta z agenta | Zatwierdzenie per capability, narzędzie i połączenie MCP, decydują osoby, które wybierzesz |
| Role i audyt | Role i audyt w planie workspace Business; SAML w Enterprise | Sześć ról, granty per zasób, OIDC SSO, LDAP, Kerberos i log audytowy wykrywający manipulacje w każdym wdrożeniu |
| AgenticOS jako serwer MCP | Klient MCP; własny serwer MCP zapowiedziany | Klient MCP i [serwer MCP](../mcp.md#agenticos-as-an-mcp-server) |
| Cennik | Plany osobiste 20, 100 i 200 USD miesięcznie; plany workspace od 19,90 USD miesięcznie | Bez opłaty licencyjnej; użycie modeli po stawkach providera |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Licencja bez warunków komercyjnych { #a-licence-without-commercial-conditions }

LobeHub Community License opiera się na Apache 2.0 z dodatkowymi warunkami. LobeHub można używać komercyjnie jako usługi frontendowej i backendowej **bez modyfikowania kodu źródłowego**. Tworzenie i dystrybucja dzieła zależnego wymaga licencji komercyjnej od producenta, a kontrybutorzy zgadzają się, że producent może zaostrzyć warunki. Funkcje biznesowe nie są częścią buildu open source.

AgenticOS jest na Apache-2.0. Możesz go zmieniać, oznaczyć własną marką i uruchamiać dla innych. Zobacz [porównanie warunków licencji](licence-terms.md).

### Governance na każdym agencie { #governance-on-every-agent }

Agent w AgenticOS ma właściciela, opublikowane [wersje](../concepts.md#version), [budżet](../governance.md#budgets) sprawdzany przed każdym wywołaniem modelu i [zatwierdzenia](../governance.md#approvals) kierowane do kogoś innego niż osoba, która rozmawia. Druga decyzja w rozstrzygniętym zatwierdzeniu jest odrzucana, a każda akcja trafia do [logu audytowego](../governance.md#audit). W LobeHub wydatki śledzi się względem puli kredytów, a wywołanie narzędzia potwierdza jego użytkownik.

### Microsoft Teams, telefon i e-mail { #microsoft-teams-phone-and-email }

Opublikowany agent AgenticOS odpowiada w [Microsoft Teams](../channels.md#microsoft-teams), przez [e-mail](../channels.md#email), [SMS](../channels.md#sms) i [połączenia telefoniczne](../voice.md#telephone-calls), a także w tych samych kanałach Slacka, Telegrama i Discorda, które obsługuje LobeHub. LobeHub nie wymienia kanału Teams.

### Wiele organizacji w jednym wdrożeniu { #many-organizations-in-one-deployment }

[Organizacje](../concepts.md#organizations) w AgenticOS to tenanci odizolowani w schemacie, więc jedno wdrożenie obsługuje kilka firm albo działów. LobeHub nie opisuje izolacji tenantów dla instalacji self-hosted.

## Kiedy LobeHub pasuje lepiej { #when-lobehub-is-the-better-fit }

- Chcesz dopracowanego czatu klasy konsumenckiej i dużego marketu skilli dla małego zespołu.
- Twoje zespoły pracują w LINE, WeChat, Feishu albo DingTalk, których AgenticOS nie obsługuje.
- Użyjesz go bez modyfikacji albo licencja komercyjna Ci odpowiada.

## Porównaj zmianę, nie tylko odpowiedź { #compare-a-change-not-only-an-answer }

Dodaj jednego agenta do tego samego kanału Slacka w obu produktach. Poproś go o narzędzie wymagające zatwierdzenia, a potem zdecyduj o zatwierdzeniu jako ktoś inny niż osoba, która pytała. Daj agentowi budżet kilku centów i przekrocz go. Zapisz, na co każdy produkt pozwala, czego odmawia i co loguje, według [metody porównania](comparison.md#a-shared-trial).

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Czy LobeHub jest open source? { #is-lobehub-open-source }

Jego kod jest publiczny na LobeHub Community License, która dodaje warunki do Apache 2.0: użycie komercyjne jest dozwolone bez modyfikacji kodu, a dystrybucja dzieła zależnego wymaga licencji komercyjnej. AgenticOS jest na czystej Apache-2.0.

### Czy agenci AgenticOS mogą dołączać do czatów zespołu jak agenci LobeHub? { #can-agenticos-agents-join-team-chats-like-lobehub-agents }

Tak. Opublikowany agent odpowiada w Slacku, Microsoft Teams, Telegramie, Mattermost, Discordzie i Matrixie, a może też pasywnie śledzić kanał. Żądania powiązanego użytkownika działają z jego tożsamością.

### Który lepiej kontroluje koszty? { #which-one-controls-cost-better }

LobeHub śledzi użycie względem puli kredytów. AgenticOS zatrzymuje kolejne wywołanie modelu agenta, gdy osiągnie on swój budżet albo limit organizacji, i zapisuje też koszt nieudanego runa.

## Powiązane porównania { #related-comparisons }

[AgenticOS vs Kortix](kortix.md) · [AgenticOS vs Open WebUI i LibreChat](open-webui-librechat.md) · [Agenci w Slacku](slack-agents.md) · [Wszystkie porównania](comparison.md)

## Źródła { #sources }

- [LobeHub](https://lobehub.com): opis produktu, kanały i cennik.
- [Licencja `lobehub/lobehub`](https://github.com/lobehub/lobehub/blob/main/LICENSE): cytowane warunki LobeHub Community License.
- [Repozytorium LobeHub](https://github.com/lobehub/lobehub): providerzy, obsługa MCP i build self-hosted.
