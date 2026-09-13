---
source_sha: df924dfc3bb7
---

<div class="agenticos-hero" markdown>

![AgenticOS](assets/mark.svg){ .agenticos-hero__mark }

<p class="agenticos-hero__name">AgenticOS</p>

<p class="agenticos-hero__tagline">
Jedno miejsce, w którym budujesz, uruchamiasz i nadzorujesz agentów AI swojej firmy. Hostowany u siebie, otwarty źródłowo i Twój.
Dlaczego nazywa się to systemem operacyjnym, wyjaśnia
<a href="#why-it-is-called-an-operating-system">siedem funkcji niżej</a>.
</p>

<p class="agenticos-hero__badges">
<a href="https://github.com/vstorm-co/agenticos/actions"><img src="https://img.shields.io/github/actions/workflow/status/vstorm-co/agenticos/ci.yml?branch=main&label=tests" alt="Tests"></a>
<a href="https://github.com/vstorm-co/agenticos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="Licence"></a>
<a href="https://github.com/vstorm-co/agenticos"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat" alt="Stars"></a>
<img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

<p class="agenticos-hero__links" markdown>
**Dokumentacja**: <a href="https://vstorm-co.github.io/agenticos/">vstorm-co.github.io/agenticos</a><br>
**Kod źródłowy**: <a href="https://github.com/vstorm-co/agenticos">github.com/vstorm-co/agenticos</a>
</p>

</div>

---

AgenticOS to hostowana u siebie, wielotenantowa platforma do budowania,
nadzorowania i uruchamiania agentów AI firmy.

Najważniejsza rzecz jest taka:

!!! quote "Kod definiuje, konfiguracja komponuje"

    Zespół biznesowy komponuje agentów w przeglądarce — instrukcje, model,
    zestaw capabilities, budżet — a wynik działa tak samo wszędzie: czat webowy,
    HTTP API, Slack, Telegram, osadzony widget. Sama konsola jest aplikacją
    webową; [aplikacja desktopowa](desktop.md) to ta sama konsola we własnym
    oknie, dodatek dla tych, którzy chcą mieć ją w docku.

    Inżynierowie rozszerzają to, z czego można komponować, w typowanym Pythonie.
    Konfiguracja nigdy nie sięgnie dalej niż to, co zarejestrował kod, i to
    właśnie sprawia, że Builder bez kodu można bezpiecznie oddać komuś, kto nie
    jest inżynierem.

Wszystko inne na tej stronie wynika z tego jednego zdania. Sufitem nie jest plik
konfiguracyjny — sufitem jest to, co Twoi inżynierowie włożą do rejestru, a
źródła są Twoje.

## Zacznij tam, gdzie jesteś { #start-where-you-are }

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **Chcę to wypróbować**

    [Instalacja](install.md) to cztery komendy, a potem
    [pierwszy agent](first-agent.md) działa w jakieś dziesięć minut.

- :material-account-tie:{ .lg .middle } **Decyduję, czy to wdrożymy**

    [Wdrożenie u siebie](rollout.md) — kto co robi, ile to kosztuje i o co
    zapyta Twój przegląd bezpieczeństwa. Bez terminala.

- :material-code-braces:{ .lg .middle } **Chcę się z tym zintegrować**

    [HTTP API](api.md) do wywoływania, [MCP](mcp.md) do dawania agentom Twoich
    narzędzi i [kod konsoli](frontend.md), jeśli zmieniasz UI.

- :material-cog:{ .lg .middle } **Już to prowadzę i coś jest nie tak**

    [Konsola](console.md) opisuje każdy ekran, a *Podsumowanie* każdej strony to
    wersja krótka. [Konfiguracja](configuration.md) to każde ustawienie.

</div>

## Dlaczego nazywa się to systemem operacyjnym { #why-it-is-called-an-operating-system }

Bo to słowo wykonuje pracę. System operacyjny uruchamia i izoluje procesy,
egzekwuje limity zasobów, kontroluje dostęp, sięga sprzętu przez sterowniki,
prowadzi system plików, daje wielu interfejsom jedną powłokę i pisze log
audytowy.

AgenticOS robi każdą z tych rzeczy dla agentów: runy, budżety sprawdzane przed
żądaniem do modelu, katalog uprawnień z approvalami jako jego `sudo`, MCP i
profile modeli jako jego sterowniki, kolekcje w Twoim własnym Postgresie, jeden
runner za każdą powierzchnią i ślad audytowy zapisywany nawet wtedy, gdy run się
nie powiedzie.

[Te siedem, jedna po drugiej, z tym, co sprawdzić w dowolnym innym produkcie →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Dlaczego to istnieje { #why-it-exists }

Większość frameworków agentowych daje Ci bibliotekę. Piszesz Pythona, wdrażasz
go, a każda zmiana zachowania agenta to pull request, przegląd i wydanie.

To właściwy kształt dla funkcji produktu. Jest to niewłaściwy kształt dla
czterdziestu małych agentów, których firma naprawdę chce, bo **osoba, która wie,
co agent ma mówić, to nie jest osoba z dostępem do commitowania.**

Dlatego AgenticOS wyprowadza agenta poza kod, a w zamian otacza go nadzorem.

<div class="grid cards" markdown>

- :material-shield-check:{ .lg .middle } **Budżety, które zatrzymują run**

    Sprawdzane *przed* każdym żądaniem do modelu, a nie po nim. Run, który się
    nie powiódł, i tak zapisuje, ile wydał, bo budżet ignorujący porażki nie jest
    budżetem.

- :material-hand-back-right:{ .lg .middle } **Approval dla wszystkiego, co ma skutki uboczne**

    Narzędzie działające na świat zewnętrzny parkuje run i czeka na człowieka.
    Ustawiany per capability, nadpisywalny per narzędzie.

- :material-account-key:{ .lg .middle } **Uprawnienia w kodzie, role złożone z nich**

    Miejsca wywołań sprawdzają uprawnienia, nigdy nazwy ról. Grant poszerza to,
    co jedna osoba może zrobić z jednym wierszem; nigdy tego nie zawęża.

- :material-database-lock:{ .lg .middle } **Izolacja tenantów w schemacie**

    Nie tylko w warstwie serwisów. Szyfrogram z jednej organizacji nie może
    zostać odszyfrowany dla innej.

</div>

## Wymagania { #requirements }

Docker i Docker Compose. To cała lista — Postgres (z pgvector), Redis, API,
worker i konsola wstają razem.

Wolisz uruchamiać usługi ręcznie? Python 3.12, Node z [bun](https://bun.sh),
PostgreSQL 16 z [pgvector](https://github.com/pgvector/pgvector) oraz Redis.

## Instalacja { #installation }

```bash
git clone https://github.com/vstorm-co/agenticos.git
cd agenticos
make dev
```

To podnosi Postgresa, Redisa, API, workera i frontend.

Następnie utwórz organizację, właściciela, model i pierwszego agenta:

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

I otwórz konsolę:

```bash
open http://localhost:3000
```

Zaloguj się jako `admin@example.com` / `admin123`.

!!! tip

    Nie masz pewności, czy wdrożenie faktycznie uruchomi agenta? Zapytaj je.

    ```bash
    uv run agenticos cmd doctor
    ```

## Z czego zbudowany jest agent { #what-an-agent-is-made-of }

Sześć decyzji i żadna z nich nie jest kodem. Ktoś, kto wie, co agent ma mówić,
podejmuje wszystkie sześć w przeglądarce; publikacja zamraża tę kombinację jako
wersję i to ta wersja odpowiada.

| | O czym decyduje |
|---|---|
| **Instrukcje** | Co agent robi, zwykłym językiem — i czego ma odmawiać |
| **Profil modelu** | Który model odpowiada, z jakimi parametrami i na co przechodzi podczas awarii |
| **Capabilities** | Co w ogóle wolno mu robić: przeszukać Twoją wiedzę, przeczytać stronę, uruchomić Pythona, narysować wykres |
| **Wiedza** | Które kolekcje może przeszukiwać i nic poza nimi |
| **Approval** | Które z tych akcji czekają na człowieka, zanim dotkną świata zewnętrznego |
| **Budżet** | Ile może wydać w miesiącu, sprawdzane *przed* każdym żądaniem, a nie liczone po fakcie |

Zmień którąkolwiek z nich, a nic nie ruszy, dopóki nie opublikujesz. Wersja,
która była na żywo, pozostaje czytelna, więc *jak ten agent wyglądał w marcu* ma
odpowiedź.

=== "Co się edytuje"

    ![Agents — każdy z wersją, która jest na żywo, i z tym, kto może do niego sięgnąć](assets/screens/light/agents.webp#only-light)
    ![Agents — każdy z wersją, która jest na żywo, i z tym, kto może do niego sięgnąć](assets/screens/dark/agents.webp#only-dark)

=== "Czym się to staje"

    Zamrożoną wersją i plikiem, który możesz wyeksportować do własnego
    repozytorium git, przejrzeć w pull requeście i z niego przywrócić:

    ```yaml
    name: Support Copilot
    instructions: |
      Answer from the product wiki and cite the document you used.
      If the wiki does not cover it, say so rather than guessing.
    model_profile_id: 8f1c...
    capabilities:
      - id: knowledge
        config: { default_top_k: 8 }
      - id: web_research
        approval: required
    collection_ids: [b2a9...]
    budget:
      monthly_usd: 50
    ```

## Sprawdź to { #check-it }

Opublikuj go, a będzie działał tak samo na każdej powierzchni: czat w konsoli,
hostowana strona, osadzony widget, HTTP API, Slack, Telegram, Mattermost.

```bash
curl -X POST http://localhost:8000/api/v1/agents/$AGENT_ID/run \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Organization-Id: $ORG_ID" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "How do I rotate a provider key?"}'
```

Za wszystkimi stoi jeden runner, więc odpowiedź nie zależy od tego, skąd
przyszło pytanie.

## Co dostajesz { #what-you-get }

| | |
|---|---|
| **Agenci** | Budowani w UI, wersjonowani przy publikacji, eksportowalni jako YAML do Twojego własnego repozytorium git |
| **[Capabilities](reference/capabilities.md)** | Wyszukiwanie w wiedzy, wyszukiwanie i pobieranie z sieci, prawdziwa przeglądarka, Python, sandbox z plikami i powłoką, wykresy, obrazy, delegacja, planowanie, guardraile — włączane per agent |
| **[Integracje](mcp.md)** | Dowolny serwer MCP po URL, z 59 popularnymi w wyborze — GitHub, Linear, Notion, Slack, Stripe, Postgres |
| **[Modele](models.md)** | 27 providerów, klucze per organizacja, fallbacki oraz hostowana u siebie Ollama albo proxy LiteLLM |
| **[Wiedza](file-processing.md)** | Wyszukiwanie po Twoich dokumentach z trzema parserami PDF, własnym chunkingiem, OCR-em i opisem obrazów — per kolekcja, nadpisywalne per wgranie. Synchronizacja Google Drive i S3 |
| **[Skille](skills.md)** | Spisane know-how, które agent wczytuje tylko wtedy, gdy uzna je za istotne |
| **[Nadzór](governance.md)** | Miesięczne budżety, zatwierdzanie przez człowieka, ślad audytowy, alerty per agent |
| **[Powierzchnie](channels.md)** | Czat webowy, hostowana strona bez logowania, osadzalny widget, HTTP API, surowy WebSocket dla Twojego własnego frontendu, Slack, Telegram, Mattermost — za wszystkimi jeden runner |
| **[Sekrety](secrets.md)** | Pieczętowane per organizacja. Żadna odpowiedź, linia logu ani wpis audytowy nigdy nie niesie klucza otwartym tekstem |

[Pełna lista funkcji →](features.md)

## Podsumowanie { #recap }

- Agent jest **plikiem**, a nie modułem. Instrukcje, model, capabilities, budżet.
- Jest **publikowany jako wersja** i to ta wersja działa.
- Jest **eksportowalny jako YAML** do Twojego repozytorium, do przejrzenia w
  pull requeście.
- Jest **nadzorowany**: budżety zatrzymujące run, approvale czekające na
  człowieka, uprawnienia sprawdzane w każdym miejscu wywołania.
- Jest **Twój**: Twój Postgres, Twój sprzęt, nic nie dzwoni do domu.

## Dalej { #next }

<div class="grid cards" markdown>

- :material-school:{ .lg .middle } **[Nauka](learn/index.md)**

    Zalecana droga przez całość, po kolei: instalacja, pierwszy agent, pojęcia, a
    potem poszczególne części.

- :material-star-four-points:{ .lg .middle } **[Funkcje](features.md)**

    Wszystko, co platforma robi, na jednej stronie.

- :material-book-open-variant:{ .lg .middle } **[Referencja](configuration.md)**

    Ustawienia, komendy CLI, spec agenta, katalogi capabilities i uprawnień.

- :material-account-group:{ .lg .middle } **[Wdrożenie u siebie](rollout.md)**

    Dla tego, kto odpowiada za decyzję, a nie za instalację: kto co robi, ile to
    kosztuje i o co zapyta Twój przegląd bezpieczeństwa.

- :material-information-outline:{ .lg .middle } **[O projekcie](about/index.md)**

    Dlaczego istnieje, czym celowo nie jest i sześć decyzji, które go kształtują.

</div>

## Stack { #stack }

FastAPI i Pydantic v2 na PostgreSQL, [Pydantic AI](https://ai.pydantic.dev) jako
środowisko uruchomieniowe agentów, pgvector do wyszukiwania, Prefect do pracy w
tle i Next.js 15 dla konsoli.

Nic tutaj nie dzwoni do domu: ceny modeli pochodzą z dołączonego snapshotu, a
jedyne wywołania wychodzące to te, które robią Twoi agenci.

## Licencja { #licence }

Apache-2.0. Zobacz
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
