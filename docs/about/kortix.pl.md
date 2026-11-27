---
title: "AgenticOS vs Kortix"
seo_title: "AgenticOS vs Kortix CompanyOS: licencja i self-hosting"
description: "Porównaj Kortix CompanyOS i AgenticOS: Elastic License 2.0 a Apache-2.0, gdzie działają sesje agentów, budżety, zatwierdzenia, logowanie i kanały."
source_sha: "bf622c9110d0"
---

# AgenticOS vs Kortix { #agenticos-vs-kortix }

Kortix CompanyOS i AgenticOS opisują się niemal tymi samymi słowami: system operacyjny dla firmy, która pracuje z agentami AI. Różnica wychodzi w dwóch miejscach, które dział prawny albo IT sprawdza najpierw. Kortix przeszedł z Apache-2.0 na Elastic License 2.0 w lutym 2026, a jego wersja self-hosted nadal uruchamia sesje agentów w chmurowych sandboxach Kortix. AgenticOS jest na Apache-2.0 i działa w całości na Twojej infrastrukturze.

Utrzymuje zespół AgenticOS. Źródła sprawdzono 26 listopada 2026. Wersja bazowa AgenticOS: v1.95.0. Zakres Kortix: strona produktu, dokumentacja, cennik i historia pliku `LICENSE` w `kortix-ai/CompanyOS`, a nie przetestowany workspace ani wdrożenie self-hosted.

## W skrócie { #at-a-glance }

| Obszar | Kortix CompanyOS | AgenticOS |
| --- | --- | --- |
| Czym jest | Firma jako repozytorium git: agenci, skille, pamięć i konektory są plikami | Konsola, w której zespół biznesowy buduje wersjonowanych agentów, workflow, aplikacje i tabele |
| Licencja | Elastic License 2.0 od 18 lutego 2026; Apache-2.0 przed grudniem 2025 | Apache-2.0; zobacz [licencje dołączonych komponentów](../licenses.md) |
| Gdzie działa | Chmura Kortix albo self-hosted web, API i baza; sesje agentów nadal działają w chmurowych sandboxach Kortix | Twoja infrastruktura, łącznie z sandboxem; możliwe są wdrożenia odizolowane od sieci |
| Modele | Dowolne, z własnymi kluczami | 28 providerów, w tym lokalni |
| Kontrola wydatków | Budżet dzienny, tygodniowy albo miesięczny per workspace, z blokadą albo ostrzeżeniem | Miesięczny budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu |
| Zatwierdzenia | Allow, Ask albo Deny per narzędzie; decyduje manager workspace'u albo osoba, która uruchomiła sesję | Zatwierdzenie per capability, narzędzie i połączenie MCP; run czeka na osoby, które wybierzesz |
| Logowanie i role | SAML SSO, SCIM, grupy i role niestandardowe za kluczem licencji Enterprise | OIDC SSO, LDAP i Kerberos, sześć ról i granty per zasób w każdym wdrożeniu |
| Audyt | Zablokowane archiwum; odczyt wymaga Enterprise | Log audytowy wykrywający manipulacje, z eksportem CSV i JSONL |
| Kanały | Slack, Microsoft Teams, Telegram, Discord, e-mail; głos eksperymentalnie | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, e-mail, iMessage, połączenia telefoniczne |
| Cennik | Darmowy plan z 500 kredytami; kredyty od 50 USD miesięcznie; klucz licencji Enterprise | Bez opłaty licencyjnej; użycie modeli po stawkach providera |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Licencja, która pozwala hostować go dla innych { #a-licence-that-lets-you-host-it-for-others }

Elastic License 2.0 to licencja source-available, a nie open source. Zakazuje udostępniania oprogramowania innym jako usługi hostowanej lub zarządzanej oraz przenoszenia, zmieniania albo obchodzenia funkcji klucza licencyjnego. W Kortix klucz odblokowuje SAML, SCIM, grupy, role niestandardowe, odczyt archiwum audytu i branding.

Licencja zmieniła się trzy razy w niecały rok: Apache-2.0 w kwietniu 2025, Kortix Non-Commercial License 3 grudnia 2025, dzień później Kortix Public Source License, a 18 lutego 2026 Elastic License 2.0. AgenticOS jest na Apache-2.0: możesz go uruchomić dla każdego działu, spółki zależnej albo klienta, zmieniać go i oznaczyć własną marką.

### Self-hosting, który zostawia pracę na Twoich serwerach { #self-hosting-that-keeps-the-work-on-your-servers }

Kortix dokumentuje, że instalacja self-hosted uruchamia aplikację web, API i bazę danych, a sesje agentów nadal działają w chmurowych sandboxach Kortix; serwer musi też być osiągalny z internetu. Praca odizolowana od sieci i pełna lokalizacja danych nie są więc dostępne.

W AgenticOS [sandbox](../sandbox.md) jest częścią Twojego wdrożenia, a świeża instalacja nigdzie nie wysyła promptów ani dokumentów. Zobacz [co domyślnie wychodzi](../data-protection.md#nothing-leaves-by-default).

### Budżet per agent, nie per workspace { #a-budget-per-agent-not-per-workspace }

Budżet Kortix dotyczy całego workspace'u. AgenticOS sprawdza [miesięczny budżet](../governance.md#budgets) każdego agenta i limit organizacji [przed każdym wywołaniem modelu](../governance.md#enforcement-is-before-the-request), a [praca delegowana](../governance.md#delegation-spends-the-parents-budget) idzie z budżetu agenta nadrzędnego. Wiesz, który agent ile wydał, a jeden rozpędzony agent nie wyczerpie puli wszystkich.

### Kontrole, o które pyta przegląd, bez klucza licencji { #the-controls-a-review-asks-for-without-a-licence-key }

[OIDC SSO, LDAP i Kerberos](../directory.md#signing-in-with-a-directory-account), [sześć ról i granty per zasób](../permissions.md#layer-3-visibility-and-grants) oraz [log audytowy wykrywający manipulacje](../governance.md#audit) są w każdym wdrożeniu AgenticOS. SAML i SCIM nie są jeszcze dostępne; SAML działa przez brokera, takiego jak Keycloak.

### Wiele organizacji w jednym wdrożeniu { #many-organizations-in-one-deployment }

[Organizacje](../concepts.md#organizations) w AgenticOS to tenanci odizolowani w schemacie. Kortix obsługuje kilka workspace'ów na konto i nie opisuje izolacji tenantów na Twoich własnych serwerach.

## Kiedy Kortix pasuje lepiej { #when-kortix-is-the-better-fit }

- Chcesz opisać firmę w całości jako pliki w jednym repozytorium git i edytować ją agentem do kodowania.
- Wolisz zarządzany produkt w chmurze, który startuje w kilka minut, a Elastic License 2.0 pasuje do sposobu, w jaki go użyjesz.
- Potrzebujesz SAML albo SCIM już dziś i kupisz klucz licencji Enterprise. AgenticOS nie ma jeszcze żadnego z nich.

## Porównaj zmianę, nie tylko odpowiedź { #compare-a-change-not-only-an-answer }

Uruchom w obu produktach fixture [pierwszego agenta dokumentów](../howto/first-document-agent.md). Potem sprawdź, gdzie naprawdę działa sesja: obserwuj połączenia wychodzące z serwera self-hosted, gdy agent pracuje. Daj agentowi budżet kilku centów i przekrocz go. Zapisz, na co każdy produkt pozwala, czego odmawia i co loguje, według [metody porównania](comparison.md#a-shared-trial).

## Najczęściej zadawane pytania { #frequently-asked-questions }

### Czy Kortix CompanyOS jest open source? { #is-kortix-companyos-open-source }

Nie według licencji OSI. Jego repozytorium przeszło 18 lutego 2026 na Elastic License 2.0, która zakazuje oferowania go innym jako usługi hostowanej i obchodzenia klucza licencyjnego. AgenticOS jest na Apache-2.0.

### Czy Kortix może działać w całości na moich serwerach? { #can-kortix-run-fully-on-my-own-servers }

Według dokumentacji instalacja self-hosted uruchamia aplikację web, API i bazę, ale sesje agentów nadal działają w chmurowych sandboxach Kortix. AgenticOS uruchamia każdą część, łącznie z sandboxem, na Twojej infrastrukturze.

### Czy Kortix ma budżety i zatwierdzenia? { #does-kortix-have-budgets-and-approvals }

Tak: budżet per workspace, który blokuje albo ostrzega, oraz Allow, Ask albo Deny per narzędzie. AgenticOS ustawia budżet per agent i per organizacja, sprawdzany przed każdym wywołaniem modelu, i kieruje zatwierdzenia do osób, które wybierzesz.

## Powiązane porównania { #related-comparisons }

[AgenticOS vs LobeHub](lobehub.md) · [AgenticOS vs Agno AgentOS](agno.md) · [Porównanie warunków licencji](licence-terms.md) · [Wszystkie porównania](comparison.md)

## Źródła { #sources }

- [Kortix](https://kortix.com): opis produktu i plany cenowe.
- [Dokumentacja Kortix](https://kortix.com/docs/guide): self-hosting, sandboxy, budżety i zatwierdzenia.
- [Licencja `kortix-ai/CompanyOS`](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) i historia pliku: cytowane warunki Elastic License 2.0 i wcześniejsze licencje.
- [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license): tekst licencji.
