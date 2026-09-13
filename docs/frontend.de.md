---
source_sha: d3a6a1847ec0
---

# Der Code der Konsole { #the-consoles-code }

[Architektur](architecture.md) ist das Backend. Dies ist die andere Hälfte: die
Next.js-Anwendung in `frontend/`, für alle, die gleich etwas daran ändern.

**Stack.** Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind ·
`next-intl` · TanStack Query · Zustand · vitest und Testing Library ·
Playwright. Paketmanager und Runner: **bun**.

## Wo was liegt { #where-things-live }

| Pfad | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | Das Produkt. Routen tragen ein **Locale-Präfix** |
| `src/app/api/…` | Route Handler, die zum Backend weiterleiten |
| `src/lib/` | Typisierte API-Clients, `query-keys.ts` und die Registries weiter unten |
| `src/hooks/` | Einer pro Ressource — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, einer pro Anliegen |
| `src/components/<domain>/` | UI nach Domäne; Primitive in `ui/`, Leer- und Fehlerzustände in `states/` |

Server Components sind der Default. `"use client"` ist für State, Effects und
Handler da, nicht für die Gewohnheit.

## Der Browser ruft nie das Backend auf { #the-browser-never-calls-the-backend }

Jede Anfrage geht an `/api/*` dieser App, die sie mit dem Access Token aus einem
**HttpOnly-Cookie** an FastAPI weiterleitet. Genau das hält das Token aus dem
JavaScript und die URL des Backends aus dem Client-Bundle heraus.

Das erledigt ein einziger Weiterleiter — `src/lib/platform-proxy.ts` — statt einer
handgeschriebenen Route-Datei pro Endpunkt, die dieselben zwölf Zeilen
wiederholt.

!!! warning "Eine Antwort ohne `Cache-Control` ist keine Antwort, die niemand cacht"

    Der Proxy stempelt `no-store` auf alles, was das Backend unmarkiert gelassen
    hat. Jede Antwort hier hängt von einem Cookie, einer Permission-Menge und dem
    Organisations-Header ab, und eine Liste, die nach einem Schreibvorgang neu
    geholt wird, muss den Server erreichen.

    Eine handgeschriebene Route-Datei schuldet denselben Header — der Proxy ist
    der einzige Ort, der ihn für Sie setzt.

## Daten, und wo State wohnt { #data-and-where-state-lives }

**Jeder API-Zugriff geht über einen Client in `src/lib/` und wird über einen Hook
konsumiert.** Kein `fetch` in einer Komponente.

Serverdaten wohnen in der Query-Schicht; **Stores halten nur UI- und flüchtigen
State**. Registrieren Sie jeden Query Key in `query-keys.ts`, damit die
Invalidierung nach einem Schreibvorgang konsistent bleibt.

## Permissions sind eine Rendering-Entscheidung { #permissions-are-a-rendering-decision }

`use-permissions.ts` liefert die effektive Permission-Menge für die aktive
Organisation. **Ein Bedienelement, das die aufrufende Person nicht nutzen darf,
wird nicht gerendert** — nicht gerendert und dann 403.

Zwei Fallen, die hier beide schon ausgeliefert wurden:

- **Welche Rollen ein Picker anbietet, ist Rechnerei, keine Liste.**
  `assignableRoles` spiegelt die Regel des Servers über dem Permission-Katalog:
  Eine Rolle wird nur angeboten, wenn die eigene der aufrufenden Person sie
  strikt überragt. Ein fest verdrahtetes "jede Rolle außer owner" ist das, was
  einem Admin die Option Admin anbot und nach dem Eintippen der E-Mail-Adresse
  mit 403 antwortete.
- **Eine Seite, die eine Organisation in ihrer URL nennt, *ist* diese
  Organisation.** Der API-Client stempelt `X-Organization-Id` aus der *aktiven*
  Organisation, also entscheidet eine Seite, die auf der Organisation in ihrem
  Pfad handelt und dabei die Permissions der aktiven liest, über die Mitglieder
  von Acme nach Ihrer Rolle in Globex. Die Übernahme wohnt in `ActiveOrgGuard`,
  einmal.

## Jeder für Menschen sichtbare String geht durch `next-intl` { #every-user-facing-string-goes-through-next-intl }

`make lint` erzwingt das in beide Richtungen: Ein lesbarer String, der in einer
Komponente sitzt, schlägt fehl, und ein Key, den der Katalog hält und den keine
Komponente liest, ebenso.

Drei Regeln, über die man stolpert:

- **Eine Anzahl ist ein ICU-`plural`, nie ein Ternär.**
  `{n} file{n === 1 ? "" : "s"}` ist ein Satz, den nur Englisch so baut.
- **Ein Substantiv, mit dem der Satz kongruiert, ist kein Parameter.**
  `{matched} of {total} {noun}` rendert auf Polnisch `3 of 40 skills`. Das
  Substantiv gehört in das `plural` oder `select`.
- **Der Katalog hält Copy, und nur Copy.** Ein falsch-positiver Treffer bekommt
  ein `i18n-exempt` mit Begründung; er bekommt nie einen Key. Einen solchen
  Treffer zu beantworten, indem man eine Tailwind-Klassenliste nach `en.json`
  verschiebt, ist der Weg, auf dem das einmalige Übersetzen eines Strings einer
  Komponente ihr Styling nahm.

Englisch ist die Ausgangssprache und wird unter jedes Locale gemischt, also
rendert eine fehlende Übersetzung Englisch statt des Keys.

!!! info "Die eigenen Nomen des Produkts bleiben in jedem Locale englisch"

    agent, spec, capability, skill, embed, budget, run, prompt, provider, token,
    vault, workspace, sandbox, MCP. Sie benennen Dinge, die eine Kundin auch in
    den Docs, in der API und im exportierten YAML antrifft — sie in der UI und
    sonst nirgends zu übersetzen, macht zwei Vokabulare für ein Produkt. Flektieren
    Sie sie, ersetzen Sie sie nicht.

## Vier Registries, und keine zweite Quelle { #four-registries-and-no-second-source }

Jede davon ist eine Tabelle, die mehrere Teile der UI lesen. Der Tabelle etwas
hinzuzufügen ist die ganze Änderung; eine zweite Quelle hinzuzufügen ist der Bug.

| | Hält | Hinzufügen über |
|---|---|---|
| `lib/tool-catalog.ts` | Icon, laufende Beschriftung, fertigen Namen und Renderer für jedes Tool, das das Backend registriert | Eine Zeile, die auf der Tool-id der Capability sitzt. Ein Backend-Test vergleicht beide in beide Richtungen |
| `lib/brand-glyphs.generated.ts` | Jedes Dienst-, Connector- und Provider-Zeichen, als rohe Pfaddaten | Eine Zeile in `scripts/gen-brand-icons.ts`, dann `bun run gen:brand-icons`. Nie ein Import aus einem Icon-Paket |
| `lib/dashboard/registry.ts` | Die Dashboard-Widgets und die Permission, an der jedes gemessen wird | Fünf Änderungen, unten auf der Seite aufgeführt |
| `lib/dialog-sizes.ts` | Ein Breiten-Token und ein Form-Token pro Dialog | Ein Token wählen, nie eine maßgeschneiderte Höhe |

## Zwei Dinge, die eine neue Oberfläche schuldet { #two-things-a-new-surface-owes }

Beide sind Registries mit demselben Fehlerbild: Eine Seite, die woanders
hinzugefügt wird, fehlt darin schlicht, nichts schlägt fehl, und das Feature geht
unsichtbar in den Betrieb.

**Eine Station im Rundgang.** `lib/onboarding/tour.ts` ist der passive Rundgang,
den das "?" einer Seite abspielt, und `flows.ts` ist das geführte Anlegen, das er
am Ende anbietet. Eine Seite ohne Station rendert **gar kein "?"** — eine neue
Seite, deren Kopfbereich keine Hilfeschaltfläche trägt, wurde also nicht
registriert. Messen Sie den Schritt an der Permission, die sein Bedienelement
trägt, markieren Sie ihn `optional`, wenn das Bedienelement Daten braucht, um zu
existieren, und verankern Sie ihn an etwas Begrenztem.

**Ein Dashboard-Widget**, wenn das Feature einen Zustand erzeugt, den jemand auf
einen Blick sehen möchte. Fünf Änderungen: die id und die Definition in
`dashboard/registry.ts`, die Komponente in `components/dashboard/widgets/`, eine
Platzierung in `layouts.ts`, die id gespiegelt in
`backend/app/schemas/dashboard_layout.py` — ein Test schlägt fehl, wenn die
beiden auseinanderlaufen — und Copy in `en.json` und `pl.json`.

## Prüfen { #verify }

Aus `frontend/` heraus. Im Wurzelverzeichnis des Repositorys findet vitest keine
Konfiguration, meldet rund 164 Geisterfehler und lässt ein verirrtes
Cache-Verzeichnis zurück.

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx   # while writing
```

Einmal, vor dem Push — aus dem Wurzelverzeichnis des Repositorys:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

!!! danger "`test:coverage`, nicht `test:run`"

    Der Job, den CI ausführt, misst Coverage und schlägt unter 100 % Zeilen,
    Statements und Funktionen oder 97,5 % Branches fehl. Eine Suite, in der jeder
    Test besteht, kann trotzdem rot sein, und war es schon.

Einen toten Zweig zu löschen ist leichter, als ihn abzudecken: ein `?? ""` hinter
einer Prüfung, die den Wert bereits bewiesen hat, ist einer, den das Gate zu
Recht bemerkt.

**Ein Spec, der in einen Timeout läuft, ist meist die Maschine.** `testTimeout`
ist 15 s und `asyncUtilTimeout` 5 s, beide gemessen statt geraten. Keines von
beidem ist ein Grund, einen Spec zu behalten, der mehr mountet, als seine
Assertions lesen.

## Fazit { #recap }

- Der Browser spricht mit **`/api/*` dieser App**, nie mit FastAPI — ein
  Weiterleiter, und der stempelt `no-store`.
- Serverdaten wohnen in der **Query-Schicht**; Stores halten nur UI-State.
- Ein Bedienelement, das die aufrufende Person nicht nutzen darf, wird **nicht
  gerendert**, und Rollen-Picker sind **berechnet, nicht aufgelistet**.
- Copy geht durch **`next-intl`**, Anzahlen sind ICU-Plurale, und der Katalog
  hält Copy und nur Copy.
- Eine neue Oberfläche schuldet eine **Station im Rundgang** und ein Widget, wenn
  sie auf einen Blick lesbaren Zustand hat — beides sind stille Registries.

[Das Backend →](architecture.md) · [Ein Feature hinzufügen →](adding_features.md) ·
[Testen →](testing.md)
