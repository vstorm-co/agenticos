---
title: "AgenticOS vs Onyx"
seo_title: "AgenticOS vs Onyx: wyszukiwarka firmowa czy agenci firmy"
description: "Porównaj Onyx i AgenticOS: wyszukiwanie i czat firmowy a agenci firmy z governance, licencja ee, limity wydatków, zatwierdzenia, kanały i ceny."
source_sha: "e335c0e76f47"
---

# AgenticOS vs Onyx { #agenticos-vs-onyx }

Onyx to platforma AI open source zbudowana wokół wyszukiwania firmowego: czat z dowolnym modelem na ponad 40 konektorach, z agentami, MCP i botami w Slacku i Discordzie. AgenticOS zaczyna od agenta: każdy ma właściciela, wersje, budżet i zatwierdzenia oraz odpowiada w wielu kanałach. Jeśli całą pracą jest wyszukiwanie w wielu źródłach SaaS, Onyx jest mocny. Jeśli agenci działają w imieniu firmy, governance wygląda inaczej.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 26 listopada 2026. Wersja bazowa AgenticOS: v1.95.0. Zakres Onyx: repozytorium, pliki licencji, dokumentacja i cennik, a nie przetestowane wdrożenie.

## W skrócie { #at-a-glance }

| Obszar | Onyx | AgenticOS |
| --- | --- | --- |
| Czym jest | Czat i wyszukiwanie firmowe w źródłach firmy, z agentami | Wersjonowani agenci firmy, workflow, aplikacje i tabele, budowane w przeglądarce |
| Licencja | MIT, z katalogami `ee` na Onyx Enterprise License | Apache-2.0; zobacz [licencje dołączonych komponentów](../licenses.md) |
| Gdzie działa | Self-hosted, także odizolowany od sieci, albo chmura Onyx | Twoja infrastruktura |
| Wiedza | Ponad 40 konektorów, mocne wyszukiwanie | [Bazy wiedzy](../file-processing.md) z kontrolą parsera i synchronizowanymi konektorami; jeszcze bez rerankera |
| Kontrola wydatków | Limity wydatków per workspace w Business, per użytkownik i grupa w Enterprise | Miesięczny budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu |
| Zatwierdzenia | Potwierdza użytkownik, w funkcji Craft | Zatwierdzenie per capability, narzędzie i połączenie MCP, decydują osoby, które wybierzesz |
| Role i logowanie | Role niestandardowe i SCIM w Enterprise | Sześć ról i granty per zasób; OIDC SSO, LDAP i Kerberos |
| Tenanci | Jedna organizacja na instalację self-hosted | Wiele organizacji w jednym wdrożeniu |
| Kanały | Web, boty w Slacku i Discordzie, widget, aplikacja desktop, rozszerzenie Chrome | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, e-mail, iMessage, połączenia telefoniczne; aplikacje desktop i na telefon |
| Cennik | Community za darmo; Business 20 USD za użytkownika miesięcznie; Enterprise indywidualnie | Bez opłaty licencyjnej; użycie modeli po stawkach providera |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Agent to obiekt z właścicielem { #an-agent-is-an-object-with-an-owner }

W AgenticOS agent to [wersjonowany spec](../concepts.md#version): instrukcje, model, capabilities i budżet, publikowane jako wersja, którą [środowiska](../environments.md#what-an-environment-is) promują dalej i którą można wyeksportować do YAML. Właściciel biznesowy zmienia go w [Builderze](../features.md#exportable-into-your-own-repository), a każdą zmianę da się później odczytać.

### Governance w produkcie open source { #governance-in-the-open-source-product }

Produkcyjne użycie katalogów `ee` w Onyx wymaga licencji na liczbę stanowisk, a limity wydatków per użytkownik i grupa, SCIM i role niestandardowe to funkcje Enterprise. AgenticOS dostarcza [budżety](../governance.md#enforcement-is-before-the-request), [zatwierdzenia](../governance.md#approvals), [log audytowy wykrywający manipulacje](../governance.md#audit) i [logowanie przez katalog](../directory.md#signing-in-with-a-directory-account) w każdym wdrożeniu, bez opłaty za stanowisko.

### Zatwierdzenie przez kogoś innego niż użytkownik { #approval-by-someone-other-than-the-user }

Wywołanie narzędzia w AgenticOS może czekać na wybraną osobę, [powiadamianą](../governance.md#alerts) w konsoli, w kanale albo w [aplikacji na telefon](../mobile.md). Onyx opisuje potwierdzanie przez użytkownika w funkcji Craft.

### Kanały poza czatem { #channels-beyond-chat }

Ten sam opublikowany agent odpowiada w [Microsoft Teams](../channels.md#microsoft-teams), przez [e-mail](../channels.md#email), [SMS](../channels.md#sms), [połączenia telefoniczne](../voice.md#telephone-calls) i na [hostowanej stronie](../channels.md#a-hosted-page), a inni agenci docierają do niego przez [A2A](../channels.md#a2a).

## Kiedy Onyx pasuje lepiej { #when-onyx-is-the-better-fit }

- Główną pracą jest wyszukiwanie w wielu źródłach SaaS, a jego konektory obejmują Twoje systemy.
- Jakość wyszukiwania w tych źródłach liczy się dla Ciebie bardziej niż governance nad tym, co robią agenci.
- Wystarczy jedna organizacja na instalację, a cennik za stanowisko Ci odpowiada.

## Porównaj zmianę, nie tylko odpowiedź { #compare-a-change-not-only-an-answer }

Podłącz to samo źródło w obu produktach i zadaj pytania z [pierwszego agenta dokumentów](../howto/first-document-agent.md). Potem daj agentowi narzędzie, które zmienia coś niegroźnego, wymagaj zatwierdzenia przez drugą osobę i ogranicz budżet do kilku centów. Zapisz, na co każdy produkt pozwala, czego odmawia i co loguje, według [metody porównania](comparison.md#a-shared-trial).

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Czy Onyx jest open source? { #is-onyx-open-source }

W większości jest na MIT. Kod w katalogach `ee` jest na Onyx Enterprise License, która wymaga licencji na stanowiska do użytku produkcyjnego. AgenticOS nie ma katalogu enterprise: jego własny kod jest na Apache-2.0, a dołączone komponenty mają własne licencje, jak domyślny parser PDF na AGPL-3.0 ([szczegóły](../licenses.md#the-agpl-component)).

### Czy AgenticOS zastępuje wyszukiwarkę firmową? { #does-agenticos-replace-enterprise-search }

Odpowiada z baz wiedzy z synchronizowanymi konektorami i kontrolą parsera, ale skupia się na agentach, którzy działają. Jeśli główną potrzebą jest wyszukiwanie w dziesiątkach narzędzi SaaS, najpierw porównaj pokrycie konektorów.

### Czy oba mogą działać w odizolowanej sieci? { #can-both-run-air-gapped }

Tak. Onyx dokumentuje wdrożenie odizolowane od sieci, a AgenticOS działa z lokalnymi modelami, lokalnymi embeddingami i lokalnym parsowaniem na Twoim sprzęcie.

## Powiązane porównania { #related-comparisons }

[AgenticOS vs Open WebUI i LibreChat](open-webui-librechat.md) · [AgenticOS vs stack DIY](diy-stack.md) · [AgenticOS vs Dify](dify.md) · [Wszystkie porównania](comparison.md)

## Źródła { #sources }

- [Repozytorium Onyx](https://github.com/onyx-dot-app/onyx): funkcje, konektory, opcje wdrożenia i cytowany podział licencji.
- [Cennik Onyx](https://onyx.app/pricing): plany Community, Business i Enterprise.
- [Limity wydatków](https://docs.onyx.app/admins/advanced_configs/spending_limits): limity per workspace, użytkownik i grupa.
