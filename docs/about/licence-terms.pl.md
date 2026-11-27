---
title: "Porównanie warunków licencji"
seo_title: "Warunki licencji: platformy agentów AI open source"
description: "Które platformy agentów AI są open source bez warunków? Porównaj Apache-2.0 ze zmodyfikowaną Apache, Elastic License 2.0, Sustainable Use i katalogami ee."
source_sha: "733a5072cfd8"
---

# Porównanie warunków licencji { #licence-terms-compared }

„Open source” na stronie produktu często oznacza publiczny kod z dołączonymi warunkami. Dla firmy, która chce modyfikować oprogramowanie, albo integratora, który chce hostować jedną instancję dla kilku klientów, to te warunki decydują, co wolno. Ta strona porządkuje platformy z tych porównań według tego, na co pozwala ich licencja, z cytatem albo streszczeniem kluczowej klauzuli z pliku licencji.

Utrzymuje zespół AgenticOS. Pliki licencji sprawdzono 26 listopada 2026 w głównym repozytorium każdego projektu. To podsumowanie dla orientacji, a nie porada prawna; przeczytaj samą licencję, zanim na niej polegniesz.

## Klasy w skrócie { #the-classes-at-a-glance }

| Klasa | Na co pozwala | Projekty |
| --- | --- | --- |
| Liberalna licencja OSI, nic nie zatrzymane | Używać, modyfikować, oznaczać własną marką i hostować dla innych | **AgenticOS** (Apache-2.0), framework Agno, Sim, OpenAgents, RAGFlow, LangBot (Apache-2.0); rdzeń LibreChat, AnythingLLM, Langflow, Hermes Agent, OpenClaw (MIT) |
| Copyleft | Używać i modyfikować; rozpowszechniane zmiany, a w przypadku AGPL także użycie sieciowe, trzeba udostępnić na tej samej licencji | OpenHuman, MaxKB (GPL-3.0); Khoj, Cherry Studio, Nextcloud (AGPL-3.0); panel admina LibreChat (AGPL-3.0) |
| Open core z katalogiem enterprise | Rdzeń jest liberalny; funkcje w katalogach `ee` albo `enterprise` wymagają licencji komercyjnej | Onyx, LiteLLM, Langfuse, Activepieces, Chatwoot, Mastra, Windmill |
| Zmodyfikowana Apache 2.0 | Apache 2.0 plus warunki dotyczące wielotenantowości albo brandingu | Dify, FastGPT |
| Source-available | Publiczny kod na warunkach zakazujących konkurencyjnego albo hostowanego użycia | Kortix CompanyOS (Elastic License 2.0), n8n (Sustainable Use License), AutoGPT Platform (Polyform Shield), Arize Phoenix (Elastic License 2.0) |
| Własna licencja z warunkami | Publiczny kod z dodanymi warunkami komercyjnymi albo dotyczącymi brandingu | LobeHub (LobeHub Community License), Open WebUI (BSD-3 z klauzulą brandingu), NocoBase (własna umowa licencyjna) |

Wśród platform open source dla agentów firmy i samodzielnie hostowanych builderów licencja bez warunków i bez katalogu enterprise jest w mniejszości.

## Klauzule, które mają znaczenie { #the-clauses-that-matter }

### Kortix CompanyOS: Elastic License 2.0 { #kortix-companyos-elastic-license-20 }

Nie wolno udostępniać oprogramowania innym jako usługi hostowanej lub zarządzanej ani przenosić, zmieniać, wyłączać czy obchodzić funkcji klucza licencyjnego. Repozytorium było na Apache-2.0 do grudnia 2025, a 18 lutego 2026 przeszło na Elastic License 2.0. Zobacz [AgenticOS vs Kortix](kortix.md).

### Dify: Apache 2.0 z warunkami { #dify-apache-20-with-conditions }

Prowadzenie środowiska wielotenantowego, gdzie jeden tenant to jeden workspace, wymaga pisemnej zgody, a logo i informacji o prawach autorskich we frontendzie nie wolno usuwać ani zmieniać. Zobacz [AgenticOS vs Dify](dify.md).

### n8n: Sustainable Use License { #n8n-sustainable-use-license }

Użycie jest ograniczone do wewnętrznych celów firmy, użytku niekomercyjnego albo osobistego. Płatne funkcje są w plikach `.ee.` i wymagają klucza licencji. Zobacz [AgenticOS vs n8n](n8n.md).

### LobeHub: LobeHub Community License { #lobehub-lobehub-community-license }

Użycie komercyjne jest dozwolone jako usługa frontendowa i backendowa bez modyfikowania kodu źródłowego. Tworzenie i dystrybucja dzieła zależnego wymaga licencji komercyjnej, a kontrybutorzy zgadzają się, że producent może zaostrzyć warunki. Zobacz [AgenticOS vs LobeHub](lobehub.md).

### Open WebUI: BSD-3 z klauzulą brandingu { #open-webui-bsd-3-with-a-branding-clause }

Zmiana albo usunięcie brandingu jest dozwolone tylko we wdrożeniach z najwyżej 50 użytkownikami w okresie 30 dni; powyżej potrzebna jest licencja enterprise. Zobacz [AgenticOS vs Open WebUI i LibreChat](open-webui-librechat.md).

### Onyx, LiteLLM, Langfuse: katalogi enterprise { #onyx-litellm-langfuse-enterprise-directories }

Rdzeń jest na MIT. Kod w katalogach `ee` albo `enterprise` jest na licencji komercyjnej; w przypadku Onyx jego użycie produkcyjne wymaga licencji na liczbę stanowisk. Zwykle właśnie tam są single sign-on, SCIM, role niestandardowe i funkcje audytu. Zobacz [AgenticOS vs Onyx](onyx.md) i [AgenticOS vs stack DIY](diy-stack.md).

### AutoGPT Platform: Polyform Shield { #autogpt-platform-polyform-shield }

Katalog `autogpt_platform` jest na licencji Polyform Shield, która zakazuje używania go do konkurowania z licencjodawcą; reszta repozytorium jest na MIT.

## AgenticOS { #agenticos }

AgenticOS jest na Apache-2.0, bez katalogu enterprise i bez funkcji zatrzymanych dla płatnej edycji. Możesz go modyfikować, oznaczyć własną marką i uruchamiać dla innych organizacji z jednego wdrożenia. Niektóre dołączone komponenty mają własne licencje: domyślny parser PDF jest na AGPL-3.0, więc zmodyfikowany obraz, który udostępniasz innym, zobowiązuje Cię do udostępnienia im jego źródeł. [Strona licencji](../licenses.md) wymienia każdy komponent, a [komponent AGPL](../licenses.md#the-agpl-component) wyjaśnia ten wyjątek.

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Które platformy agentów AI są w pełni open source? { #which-ai-agent-platforms-are-fully-open-source }

Spośród porównywanych tutaj AgenticOS, framework Agno, Sim, OpenAgents, rdzeń LibreChat, AnythingLLM i Langflow używają licencji OSI bez katalogu enterprise. Dify, n8n, Kortix, LobeHub i Open WebUI dodają warunki.

### Czy integrator może hostować AgenticOS dla kilku klientów? { #can-an-integrator-host-agenticos-for-several-clients }

Tak. Apache-2.0 na to pozwala, a organizacje w jednym wdrożeniu są odizolowanymi tenantami. Licencje Dify i FastGPT wymagają zgody na użycie wielotenantowe, a Elastic License 2.0 zakazuje oferowania Kortix jako usługi hostowanej.

### Czy ta strona zastępuje przegląd prawny? { #does-this-page-replace-a-legal-review }

Nie. Licencje się zmieniają, jak licencja Kortix trzy razy w ciągu roku. Przeczytaj plik licencji wersji, którą wdrażasz.

## Powiązane porównania { #related-comparisons }

[Wszystkie porównania](comparison.md) · [Licencje komponentów AgenticOS](../licenses.md)

## Źródła { #sources }

- [Licencja Kortix](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) · [Licencja Dify](https://github.com/langgenius/dify/blob/main/LICENSE) · [Licencja n8n](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- [Licencja LobeHub](https://github.com/lobehub/lobehub/blob/main/LICENSE) · [Licencja Open WebUI](https://docs.openwebui.com/license) · [Licencja Onyx](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE)
- [Licencja Langfuse](https://github.com/langfuse/langfuse/blob/main/LICENSE) · [LiteLLM enterprise](https://docs.litellm.ai/docs/enterprise) · [Licencja AutoGPT](https://github.com/Significant-Gravitas/AutoGPT/blob/master/LICENSE)
