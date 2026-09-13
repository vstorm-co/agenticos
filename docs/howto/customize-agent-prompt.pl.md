---
source_sha: d61a7f894dfb
---

# Napisz instrukcje agenta { #write-an-agents-instructions }

!!! danger "Instrukcje są danymi, a nie kodem"

    Nie ma `prompts.py` do edycji ani stałej `DEFAULT_SYSTEM_PROMPT` do
    nadpisania. Zachowanie agenta to pole `instructions` jego
    [speca](../reference/spec.md) — edytowane w Builderze, wersjonowane przy
    publikacji i eksportowane jako YAML do repozytorium klienta. Edytowanie
    Pythona po to, żeby zmienić, co agent mówi, to najczęstsze błędne założenie
    na temat tego kodu.

## Gdzie mieszka ten tekst { #where-the-text-lives }

| | Gdzie | Kto to edytuje |
|---|---|---|
| Instrukcje jednego agenta | `AgentSpec.instructions`, edytowane w Builderze | Ten, kto może edytować agenta |
| Instrukcje wbudowanego specjalisty | `InlineSpecialistSpec.instructions`, w tym samym specu | Ten sam |
| Tekst startowy, który dostaje nowy agent | `backend/app/agents/default_instructions.py` | Deploy — to jest wyobrażenie tego deploymentu o asystencie |
| Procedura współdzielona przez wiele agentów | [Skill](../skills.md), wiersz w bazie danych | Lider wsparcia, we wtorek po południu, bez żadnego deployu |

Ostatni wiersz to ten, po który warto sięgać. Dwadzieścia procedur w jednym polu
`instructions` oznacza, że każdy run płaci za wszystkie dwadzieścia; dwadzieścia
skilli kosztuje prawie nic, bo model widzi nazwy i wczytuje tylko to, czego
potrzebuje.

## Co należy do instrukcji { #what-belongs-in-instructions }

Przeczytaj `default_instructions.py`, zanim napiszesz własne — to jest
przerobiony przykład i sam wyjaśnia swoje wybory. Dwa z nich decydują o
większości jakości:

- **Pisz pod odmowy.** Akapity, które zarabiają na swoje miejsce, to te o
  niewymyślaniu faktów, o mówieniu, z którego źródła pochodzi odpowiedź, i o
  zatrzymaniu się, żeby zapytać, zamiast zgadywać przy czymś destrukcyjnym.
  "Bądź pomocny" to ozdoba: model już próbuje być pomocny, a potrzebuje
  informacji, gdzie są krawędzie.
- **To, co jest specyficzne dla *tego* agenta, umieść na górze.** Ktokolwiek
  otworzy to jako następny, przepisze pierwszy akapit, a resztę zostawi.

```text
You are a customer support agent for Acme.

Answer questions about our products, help people troubleshoot, and escalate
anything involving a refund over £500 — the refund-policy skill has the rule.

Never quote a price you have not read from the knowledge base. If a question
needs an account change, say what you would do and ask them to confirm.
```

!!! warning "Nie wymieniaj narzędzi agenta w jego instrukcjach"

    Agent bierze swoje capability ze speca, a narzędzia niosą własne opisy z
    biblioteki. Prompt, który je wylicza, staje się błędny w chwili, gdy ktoś
    przełączy któreś — a skutkiem jest agent z przekonaniem odmawiający zrobienia
    czegoś, co teraz potrafi.

!!! tip "Nie powtarzaj też reguł samej capability"

    Capability, która potrzebuje, żeby model zachowywał się w określony sposób,
    wnosi to sama. Format cytowania przy wyszukiwaniu, sposób korzystania z
    sandboksa, moment, w którym trzeba zapytać człowieka — to przychodzi razem z
    capability, w każdym agencie, który ją włącza.

## Wiedza, skille i pliki kontekstowe { #knowledge-skills-and-context-files }

Trzy sposoby, żeby dać agentowi tekst, którego wcześniej nie miał, i nie są
wymienne:

| | Do czego | Pobierane przez |
|---|---|---|
| `collection_ids` — [wiedza](../file-processing.md) | Tysiące dokumentów: co wiemy | Wyszukiwanie semantyczne, z cytatami |
| `skill_ids` — [skille](../skills.md) | Dziesiątki procedur: jak to robimy | Model wybiera nazwę, a potem wczytuje treść |
| `context_ids` — pliki kontekstowe | Garść plików na tyle małych, żeby były zawsze obecne | Wstrzykiwane do instrukcji, bez żadnego wyszukiwania |

Wszystkie trzy są sprawdzane wobec dostępu **publikującego** w momencie
publikacji, a nie w momencie uruchomienia. Zobacz
[Uprawnienia](../permissions.md).

## Iterowanie nad nimi { #iterating-on-it }

- **Draft nie może zostać uruchomiony.** Agent uruchamia swoją opublikowaną
  wersję, więc wypróbowanie nowego promptu oznacza opublikowanie go — co jest
  tanie z założenia i dlatego rollback jest promocją, a nie przywróceniem.
  Iteruj na środowisku `dev`
  ([environment](../concepts.md#version)), które podąża za każdą publikacją, a
  `production` zostaw czekające na promocję.
- **Testuj prawdziwymi zapytaniami, a nie idealnymi.**
- **Trzymaj instrukcje tak krótkie, jak wymaga tego zachowanie.** Za dłuższy
  prompt płaci się przy każdej turze każdego runa, a rozmowa szybciej wypada
  poza okno.
- **Publikuj, gdy jest dobrze.** Publikacja zamraża wersję, więc "co ten agent
  robił w zeszły wtorek" pozostaje pytaniem z odpowiedzią po kilkunastu
  edycjach — a rollback publikuje *nową* wersję skopiowaną ze starej, zamiast
  kasować historię.
- **Temperatura i reszta to `model_settings`**, per agent i per specjalista, na
  wierzchu profilu modelu. Nie zmienna środowiskowa.
