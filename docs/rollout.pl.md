---
source_sha: "6ff659040810"
title: "Wdrożenie i utrzymanie AgenticOS"
description: "Przypisz odpowiedzialność, poznaj koszty utrzymania i określ zakres pomocy wdrożeniowej."
---

# Wdrożenie i utrzymanie AgenticOS { #deploy-and-operate-agenticos }

AgenticOS jest aplikacją utrzymywaną przez Twoją organizację. Zacznij od [sprawdzalnego zadania](howto/first-document-agent.md), potem określ odpowiedzialność za wdrożenie i pracę agenta.

## Kto utrzymuje poszczególne elementy { #who-maintains-what }

| Obszar | Odpowiedzialność |
| --- | --- |
| Hosting i aktualizacje | Wdrożenie usług, monitoring pojemności, przegląd wydań i aktualizacje |
| Backup i odtwarzanie | Kopie baz i potrzebnych danych workspace, ochrona kluczy, test odtworzenia |
| Źródła i zachowanie | Aktualne dokumenty, instrukcje, skills i publikowane wersje |
| Dostęp i sekrety | Tożsamości, granty, klucze dostawców i rotacja |
| Błędy i zatwierdzenia | Przegląd runów, incydenty i uprawnieni decydenci |
| Usługi zewnętrzne | Modele, parsery, embeddingi, narzędzia, sandbox, kanały i tracing |

Szczegóły: [instalacja](install.md), [wdrożenie](deployment.md), [sekrety](secrets.md), [uprawnienia](permissions.md) i [bezpieczeństwo](security.md). Zachowaj dowód odtworzenia i kontakty operacyjne. Publikacja agenta nie zastępuje tych obowiązków.

## Koszty i modele dostawy { #costs-and-delivery-options }

Uwzględnij modele, infrastrukturę, usługi zewnętrzne, wdrożenie i czas utrzymania. Koszt runów to tylko część sumy. Sprawdź [licencje projektu i komponentów](licenses.md).

Możesz utrzymywać AgenticOS samodzielnie. Vstorm osobno pomaga we wdrożeniu w infrastrukturze klienta, dokumentacji, tworzeniu procesów i rozwoju customowym. Stałe utrzymanie wymaga uzgodnienia zakresu. Instalacja projektu nie obejmuje automatycznie ceny usługi, wsparcia ani SLA.

Skontaktuj się z [Vstorm](https://vstorm.co/) lub Kacprem, opisując zadanie, źródła, ograniczenia infrastruktury i właściciela utrzymania. Prywatne dokumenty nie są potrzebne na pierwszą rozmowę.

<span id="what-your-security-review-will-ask"></span>

## Granice do sprawdzenia { #boundaries-to-verify }

Self-hosting nie oznacza offline. Lokalny model zmienia jedną ścieżkę; parsowanie, embeddingi, narzędzia, hostowane sandboxy, kanały i tracing mogą korzystać z zewnętrznych usług. Sprawdź [przepływ danych](security.md).

Zatwierdzenia zależą od capability i konfiguracji. Budget sprawdza zapisany koszt przed wywołaniem modelu i nie gwarantuje braku przekroczenia. Granty kolekcji nie dowodzą dziedziczenia ACL źródłowych dokumentów. Sprawdź tożsamości i zadanie według [governance](governance.md) i [dostępu do kolekcji](file-processing.md).

## Oceń pilota { #evaluate-the-pilot }

Zapisz dotychczasowy proces, pytania akceptacyjne, wersję źródła, model, narzędzia i rzeczywiste wyniki. Uwzględnij braki, błędy, czas weryfikacji i użycie. Zmień jeden fakt i powtórz przed rozszerzeniem zakresu.

Przy wyborze użyj [porównań](about/comparison.md), a przy błędach [pomocy](help.md). Pilot może uzasadnić rozwój, poprawkę lub rezygnację; nie jest obietnicą wyniku biznesowego.
