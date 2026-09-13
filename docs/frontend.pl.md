---
source_sha: d3a6a1847ec0
---

# Kod konsoli { #the-consoles-code }

[Architektura](architecture.md) to backend. To jest druga połowa: aplikacja
Next.js w `frontend/`, dla kogoś, kto zaraz ją zmieni.

**Stack.** Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind ·
`next-intl` · TanStack Query · Zustand · vitest i Testing Library ·
Playwright. Menedżer pakietów i runner: **bun**.

## Gdzie co leży { #where-things-live }

| Ścieżka | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | Produkt. Ścieżki mają **prefiks lokalizacji** |
| `src/app/api/…` | Route handlery proxujące do backendu |
| `src/lib/` | Typowani klienci API, `query-keys.ts` i rejestry opisane niżej |
| `src/hooks/` | Jeden na zasób — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, jeden na zagadnienie |
| `src/components/<domain>/` | UI według domeny; prymitywy w `ui/`, stany puste i błędu w `states/` |

Server Components są domyślne. `"use client"` jest od stanu, efektów i
handlerów, a nie z przyzwyczajenia.

## Przeglądarka nigdy nie woła backendu { #the-browser-never-calls-the-backend }

Każde żądanie idzie do `/api/*` w tej aplikacji, która przekazuje je do FastAPI
z tokenem dostępu pobranym z ciasteczka **HttpOnly**. To właśnie trzyma token
poza JavaScriptem, a URL backendu poza bundlem klienta.

Robi to jeden przekaźnik — `src/lib/platform-proxy.ts` — a nie ręcznie napisany
plik route na każdy endpoint, powtarzający te same dwanaście linijek.

!!! warning "Odpowiedź bez `Cache-Control` to nie odpowiedź, której nikt nie cache'uje"

    Proxy stempluje `no-store` na wszystkim, czego backend nie oznaczył. Każda
    odpowiedź tutaj zależy od ciasteczka, zestawu uprawnień i nagłówka
    organizacji, a lista pobrana ponownie po zapisie musi dotrzeć do serwera.

    Ręcznie napisany plik route jest winien ten sam nagłówek — proxy jest
    jedynym miejscem, które nakłada go za Ciebie.

## Dane i to, gdzie mieszka stan { #data-and-where-state-lives }

**Cały dostęp do API idzie przez klienta w `src/lib/`, konsumowanego przez
hooka.** Żadnego `fetch` w komponencie.

Dane serwerowe mieszkają w warstwie zapytań; **store'y trzymają wyłącznie stan
UI i stan ulotny**. Zarejestruj każdy klucz zapytania w `query-keys.ts`, żeby
unieważnianie po zapisie pozostawało spójne.

## Uprawnienia to decyzja o renderowaniu { #permissions-are-a-rendering-decision }

`use-permissions.ts` daje efektywny zestaw uprawnień dla aktywnej organizacji.
**Kontrolka, której wołający nie może użyć, nie jest renderowana** — nie
renderowana, a nie renderowana i dopiero potem 403.

Dwie pułapki, obie już tutaj wydane:

- **To, które role oferuje picker, jest arytmetyką, a nie listą.**
  `assignableRoles` odzwierciedla regułę serwera na katalogu uprawnień: rola
  jest oferowana tylko wtedy, gdy własna rola wołającego ściśle ją przewyższa.
  Zahardkodowane „każda rola poza owner” to to, co zaoferowało Adminowi opcję
  Admin i zwróciło 403 po wpisaniu adresu e-mail.
- **Strona, która nazywa organizację w swoim URL-u, *jest* tą organizacją.**
  Klient API stempluje `X-Organization-Id` z *aktywnej* organizacji, więc
  strona działająca na organizacji ze swojej ścieżki, a czytająca uprawnienia
  dla aktywnej, rozstrzyga o członkach Acme na podstawie Twojej roli w Globeksie.
  Przyjęcie organizacji mieszka w `ActiveOrgGuard`, raz.

## Każdy widoczny dla użytkownika napis idzie przez `next-intl` { #every-user-facing-string-goes-through-next-intl }

`make lint` egzekwuje to w obie strony: czytelny napis siedzący w komponencie
oblewa i tak samo oblewa klucz, który trzyma katalog, a którego żaden komponent
nie czyta.

Trzy reguły, na których ludzie się przewracają:

- **Liczebnik to ICU `plural`, nigdy operator warunkowy.**
  `{n} file{n === 1 ? "" : "s"}` to zdanie, które tak buduje tylko angielski.
- **Rzeczownik, z którym zdanie się zgadza, nie jest parametrem.** `{matched} of
  {total} {noun}` renderuje po polsku `3 of 40 skills`. Rzeczownik wchodzi do
  środka `plural` albo `select`.
- **Katalog trzyma copy i tylko copy.** Fałszywy alarm bierze `i18n-exempt` z
  uzasadnieniem; nigdy nie bierze klucza. Odpowiedzenie na jeden z nich przez
  przeniesienie listy klas Tailwinda do `en.json` to sposób, w jaki
  przetłumaczenie jednego napisu pozbawiło kiedyś komponent jego stylowania.

Angielski jest językiem źródłowym i jest podkładany pod każdą lokalizację, więc
brakujące tłumaczenie renderuje angielski, a nie klucz.

!!! info "Własne rzeczowniki produktu zostają po angielsku w każdej lokalizacji"

    agent, spec, capability, skill, embed, budget, run, prompt, provider, token,
    vault, workspace, sandbox, MCP. Nazywają rzeczy, które klient spotyka też w
    dokumentacji, w API i w wyeksportowanym YAML-u — tłumaczenie ich w UI i
    nigdzie indziej robi dwa słowniki dla jednego produktu. Odmieniaj je, nie
    zastępuj.

## Cztery rejestry i żadnego drugiego źródła { #four-registries-and-no-second-source }

Każdy z nich to jedna tabela, którą czyta kilka części UI. Dopisanie do tabeli
jest całą zmianą; dodanie drugiego źródła jest błędem.

| | Trzyma | Dodajesz przez |
|---|---|---|
| `lib/tool-catalog.ts` | Ikonę, podpis w trakcie działania, nazwę po zakończeniu i renderer dla każdego narzędzia, które rejestruje backend | Wiersz kluczowany na id narzędzia z capability. Test backendu porównuje jedno z drugim w obie strony |
| `lib/brand-glyphs.generated.ts` | Każdy znak usługi, konektora i providera, jako surowe dane ścieżek | Wiersz w `scripts/gen-brand-icons.ts`, a potem `bun run gen:brand-icons`. Nigdy import z paczki z ikonami |
| `lib/dashboard/registry.ts` | Widgety dashboardu i uprawnienie, którym każdy z nich jest bramkowany | Pięć edycji, wymienionych na stronie poniżej |
| `lib/dialog-sizes.ts` | Jeden token szerokości i jeden token kształtu na dialog | Wybór tokenu, nigdy wysokość szytą na miarę |

## Dwie rzeczy, które nowa powierzchnia jest winna { #two-things-a-new-surface-owes }

Oba są rejestrami o tym samym trybie awarii: strona dodana gdziekolwiek indziej
jest po prostu nieobecna, nic nie oblewa, a funkcja wychodzi niewidoczna.

**Przystanek w przewodniku.** `lib/onboarding/tour.ts` to bierny spacer, który
odtwarza „?” danej strony, a `flows.ts` to prowadzone tworzenie, które spacer
oferuje na końcu. Strona bez przystanku nie renderuje **żadnego „?”** — więc
nowa strona, której nagłówek nie ma przycisku pomocy, nie została
zarejestrowana. Zabramkuj krok uprawnieniem, które niesie jego kontrolka, oznacz
go jako `optional`, gdy kontrolka wymaga istnienia danych, i zakotwicz go na
czymś ograniczonym.

**Widget dashboardu**, jeśli funkcja wytwarza stan, który ktoś chciałby widzieć
na pierwszy rzut oka. Pięć edycji: id i definicja w `dashboard/registry.ts`,
komponent w `components/dashboard/widgets/`, umiejscowienie w `layouts.ts`, id
odzwierciedlone w `backend/app/schemas/dashboard_layout.py` — test oblewa, gdy
te dwa się rozjadą — oraz copy zarówno w `en.json`, jak i w `pl.json`.

## Weryfikacja { #verify }

Z katalogu `frontend/`. W korzeniu repozytorium vitest nie znajduje konfiguracji,
zgłasza około 164 widmowych porażek i zostawia niepotrzebny katalog cache.

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx   # while writing
```

Raz, przed pushem — z korzenia repozytorium:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

!!! danger "`test:coverage`, a nie `test:run`"

    Zadanie, które uruchamia CI, mierzy pokrycie i oblewa poniżej 100% linii,
    instrukcji i funkcji albo 97,5% gałęzi. Zestaw, w którym każdy test
    przechodzi, nadal może być czerwony — i już bywał.

Martwą gałąź łatwiej usunąć niż pokryć: `?? ""` za sprawdzeniem, które już
dowiodło wartości, jest właśnie tym, co bramka słusznie zauważa.

**Spec, który przekracza czas, to zwykle maszyna.** `testTimeout` wynosi 15 s, a
`asyncUtilTimeout` 5 s, oba zmierzone, a nie zgadnięte. Żaden z nich nie jest
powodem, by trzymać spec montujący więcej, niż czytają jego asercje.

## Podsumowanie { #recap }

- Przeglądarka rozmawia z **`/api/*` w tej aplikacji**, nigdy z FastAPI — jeden
  przekaźnik, i to on stempluje `no-store`.
- Dane serwerowe mieszkają w **warstwie zapytań**; store'y trzymają wyłącznie
  stan UI.
- Kontrolka, której wołający nie może użyć, **nie jest renderowana**, a pickery
  ról są **wyliczane, a nie wypisane**.
- Copy idzie przez **`next-intl`**, liczebniki są liczbami mnogimi ICU, a katalog
  trzyma copy i tylko copy.
- Nowa powierzchnia jest winna **przystanek w przewodniku**, a jeśli ma stan
  widoczny na pierwszy rzut oka — także widget; oba rejestry milczą.

[Backend →](architecture.md) · [Dodawanie funkcji →](adding_features.md) ·
[Testowanie →](testing.md)
