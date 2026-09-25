---
source_sha: "08e94982c326"
title: "AgenticOS vs Wonderful"
description: "Porównanie zamkniętej platformy dostarczanej przez zespoły producenta z otwartą platformą, która należy do Ciebie, z pomocą we wdrożeniu ustalaną osobno."
---

# AgenticOS vs Wonderful { #agenticos-vs-wonderful }

Wonderful sprzedaje zamkniętą platformę AI enterprise razem z zespołami forward-deployed, które budują agentów wewnątrz Twojej organizacji i etapami przekazują nad nimi własność. AgenticOS to otwarta platforma, która od pierwszego dnia należy do Twojej organizacji. Jej źródła są na licencji Apache-2.0, działa na Twojej infrastrukturze, a zakres pomocy we wdrożeniu od Vstorm ustala się osobno.

Pytanie dotyczy nie tyle tego, które oprogramowanie jest lepsze, ile tego, co chcesz mieć na własność, gdy projekt się skończy: umowę z producentem platformy czy samą platformę.

Utrzymuje zespół AgenticOS w Vstorm. Źródła sprawdzono 25 września 2026. Wersja bazowa AgenticOS: v0.0.504. Zakres Wonderful: jego publiczne strony o AI OS, wdrożeniu, agentach, gatewayu i bezpieczeństwie oraz ogłoszenie o finansowaniu, a nie negocjowana umowa ani przetestowane konto.

## W skrócie { #at-a-glance }

| Obszar | Wonderful | AgenticOS |
| --- | --- | --- |
| Co kupujesz | Platformę z zespołami wdrożeniowymi i strategami | Oprogramowanie, które uruchamiasz; pomoc we wdrożeniu uzgadniana osobno |
| Źródła | Własnościowe; eksport agentów i konfiguracji przez UI lub API | Apache-2.0; całą platformę można czytać i forkować |
| Gdzie działa | Wielotenantowy SaaS, single-tenant, Twoja chmura albo odizolowane od sieci on-premises | Twoja infrastruktura, z Docker Compose |
| Ceny | Nieopublikowane; sprzedaż przez handlowców | Bez opłaty licencyjnej; modele, infrastruktura i ewentualne uzgodnione usługi |
| Kanały | Głos, czat, e-mail, WhatsApp i SMS | Czat webowy, widget, hostowana strona, HTTP API, WebSocket, Slack, Telegram, Mattermost |
| Modele | Routing per zadanie przez platformę | Twój wybór spośród 27 providerów, ustawiany per profil modelu |
| Nadzór | AI Gateway z limitami budżetu per zespół i logami audytowymi | Budżety per agent i per organizacja, zatwierdzenia i log audytowy wykrywający manipulacje |
| Deklaracje zgodności | SOC 2 Type II, ISO 27001:2022, PCI DSS, RODO | Twoje kontrole na Twojej infrastrukturze; zobacz [bezpieczeństwo](../security.md) |

## Gdzie AgenticOS idzie dalej { #where-agenticos-goes-further }

### Masz na własność platformę, a nie licencję na nią { #you-own-the-platform-not-a-licence-to-it }

Wonderful opisuje eksport agentów, skilli, narzędzi i konfiguracji nadzoru oraz headless API. To realne zobowiązanie. Runtime pozostaje zamknięty, więc wyeksportowany agent i tak potrzebuje miejsca, w którym będzie działał.

W AgenticOS to właśnie runtime jest częścią, która należy do Ciebie. Źródła są na licencji Apache-2.0, speci [eksportują się jako YAML](../features.md#exportable-into-your-own-repository) do Twojego repozytorium, a dane leżą w [Twoim Postgresie](../data-protection.md#where-personal-data-lives). Jeśli rozstaniesz się z Vstorm, wdrożenie dalej działa, a utrzymywać je może inny zespół.

### Model kosztów, który widzisz przed podpisaniem umowy { #a-cost-model-you-can-see-before-you-sign }

Wonderful nie publikuje cen. AgenticOS nie ma opłaty licencyjnej ani opłaty za stanowisko. Płacisz providerom modeli według ich stawek, [ekran kosztów](../governance.md#what-the-cost-screen-shows) pokazuje, ile wydał każdy agent, a [budżety](../governance.md#budgets) zatrzymują agenta przed następnym żądaniem do modelu, gdy dojdzie do limitu. Zakres wdrożenia z Vstorm uzgadnia się dla każdego projektu.

### Twój zespół zachowuje know-how { #your-team-keeps-the-know-how }

Model dostawy Wonderful przechodzi etapami od pracy prowadzonej przez Wonderful do własności po stronie klienta. AgenticOS jest zbudowany tak, żeby Twoi ludzie mogli zmieniać agentów od początku. Właściciel biznesowy edytuje instrukcje i publikuje [wersję](../concepts.md#version). Inżynier dodaje [capability](../howto/add-capability.md) w typowanym Pythonie i staje się ona dostępna dla wszystkich.

### Kontrole, które możesz sprawdzić { #controls-you-can-inspect }

Certyfikaty Wonderful obejmują jego własną usługę. W AgenticOS sprawdzasz same kontrole: [katalog uprawnień](../permissions.md), [vault](../secrets.md#envelope-encryption), [log audytowy](../governance.md#audit) i jego łańcuch haszy oraz [testy odmów](../security.md#the-refusals-as-a-set), które działają w CI. [Profil HIPAA](../security.md#the-hipaa-profile-and-what-it-does-not-claim) i komenda `data-protection-report` dają dowody dla jednego wdrożenia. Twoja certyfikacja obejmuje Twoje wdrożenie.

## Kiedy Wonderful pasuje lepiej { #when-wonderful-is-the-better-fit }

- Chcesz, żeby producent odpowiadał za dostawę od początku do końca, na wielu rynkach i w wielu językach.
- Głównym zastosowaniem są agenci głosowi, WhatsApp albo SMS obsługujący klientów. AgenticOS nie ma żadnego z tych kanałów.
- Potrzebujesz własnych certyfikatów producenta, takich jak SOC 2 Type II i PCI DSS, a nie własnych kontroli.

## Pytania do umowy o dostawę { #questions-for-the-delivery-agreement }

Zadaj obu producentom te same pytania.

| Obszar | Ustal przed pilotażem |
| --- | --- |
| Infrastruktura | Gdzie działa każdy komponent i kto go aktualizuje oraz przywraca? |
| Dane i dostęp | Które usługi otrzymują dane i kto utrzymuje tożsamości oraz poświadczenia? |
| Proces | Kto definiuje zadanie, obsługuje wyjątki i akceptuje wyniki? |
| Wsparcie | Kto obsługuje incydenty i w jakim uzgodnionym zakresie? |
| Wyjście | Jaki kod, konfigurację i dane klient może zatrzymać i czy może dalej działać bez producenta? |

W przypadku AgenticOS Vstorm może omówić instalację na infrastrukturze klienta, dokumentację, projektowanie procesów i rozwój na zamówienie. Wsparcie, utrzymanie, integracje i zobowiązania dotyczące czasu reakcji uzgadnia się dla projektu; nie przychodzą automatycznie razem z repozytorium.

Zdefiniuj jedno sprawdzalne zadanie na podstawie [przykładu dokumentu](../howto/first-document-agent.md) i [przewodnika po utrzymaniu](../rollout.md). W sprawie pomocy we wdrożeniu skontaktuj się z [Vstorm](https://vstorm.co/) albo z Kacprem. Porównaj uzgodniony zakres dostawy obok [kryteriów dotyczących oprogramowania](comparison.md).

## Źródła { #sources }

- [Wonderful AI OS](https://www.wonderful.ai/ai-os): komponenty, dowolność modeli, opcje wdrożenia i deklaracje zgodności.
- [Wdrożenie](https://www.wonderful.ai/deployment): cztery modele wdrożenia i zespoły forward-deployed.
- [Agenci](https://www.wonderful.ai/agents): kanały, workspace'y, wersjonowanie i uprawnienia.
- [AI Gateway](https://www.wonderful.ai/ai-gateway): limity budżetu, dostęp do modeli według roli i logi audytowe.
- [Open by default](https://www.wonderful.ai/blog-articles/open-by-default-competitive-by-design): eksport i headless API.
- [Ogłoszenie o rundzie Series C](https://www.wonderful.ai/blog-articles/wonderful-raises-550m-series-c): rynki, wielkość firmy i wdrożenie on-premises.
