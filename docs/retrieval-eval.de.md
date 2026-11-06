---
title: Retrieval-Evaluierung
description: Ein Fragenkatalog mit bekannten Antworten über die AgenticOS-Doku und ein Harness, der das Retrieval darauf misst, nach Kategorie, top_k und Abfrageerweiterung.
source_sha: "8d2d762abe12"
---

# Retrieval-Evaluierung { #retrieval-evaluation }

Ein Wissens-Agent ist nur so gut wie das, was seine Suche dem Modell übergibt.
Eine Änderung am Chunking, an `top_k` oder an der Abfrageerweiterung verschiebt
das, und eine Antwort, die sich gut liest, sagt nichts darüber, ob die richtige
Seite abgerufen wurde. Also gibt es einen Fragenkatalog mit bekannten Antworten
über diese Dokumentation und einen Harness, der das Retrieval darauf misst, in
`evals/retrieval/`. Diese Seite sagt, was er misst, wie man ihn ausführt und was
ein Lauf kostet.

Angefangen hat es mit einer Frage ([#2482](https://github.com/vstorm-co/agenticos/issues/2482)).
Auf die Frage *"Does AgenticOS support SAML single sign-on?"* rief ein Agent über
der Dokumentation nur die Vergleichsseite zu Dify ab und antwortete, die
Dokumentation sage dazu nichts. [Anmeldung über das Verzeichnis](directory.md)
sagt klar, dass es kein SAML gibt, und wie man AgenticOS stattdessen über
Keycloak erreicht.

## Der Fragenkatalog { #the-question-set }

`evals/retrieval/docs_questions.yaml` enthält 34 Fragen in drei Kategorien:

| Kategorie | Was sie prüft | Beispiel |
|---|---|---|
| `factual` | Eine angegebene Einstellung, einen Standardwert oder einen Namen | "If I never set a vault master key, what does the platform encrypt credentials with?" |
| `negative` | Eine Frage der Art „Unterstützt ihr X“, die die Dokumentation mit einem klaren Nein beantwortet | "Does AgenticOS support SAML single sign-on?" |
| `cross_language` | Eine polnische Frage, die nur aus den englischen Seiten beantwortet wird, oder eine englische Frage nur aus den polnischen Seiten | "Czy da się logować do AgenticOS przez SAML?" |

Jede Frage nennt ihre erwarteten Seiten und, für die Antwortprüfung, die Fakten,
die eine richtige Antwort enthält. Ein Eintrag sieht so aus:

```yaml
- id: saml-single-sign-on
  category: negative
  language: en
  question: Does AgenticOS support SAML single sign-on?
  expected_pages: [directory.md]
  expected_facts:
    - ["no", "not", "nie"]
    - [Keycloak*]
  evidence: "directory.md: **No SAML.** A SAML-only identity provider can reach AgenticOS through Keycloak"
```

Eine Seite wird ohne ihre Sprache genannt: `directory.md` ist auch
`directory.pl.md`, ein Chunk aus einer der beiden Übersetzungen zählt also als
Treffer. Eine `cross_language`-Frage fügt `search_locales` hinzu, die einzige
Sprache, die ihre Suche lesen darf, und das ist nie die Sprache, in der sie
gestellt wird. Die Datei ist versioniert, und eine Änderung an der Bedeutung
eines Feldes erhöht `version`. Der Loader lehnt eine erwartete Seite ab, die
nicht existiert oder nicht veröffentlicht ist, sodass das Umbenennen einer Seite
die Unit-Tests scheitern lässt, statt zu einem Fehltreffer in einem Lauf zu
werden, den jemand bezahlt hat.

## Was ein Lauf misst { #what-a-run-measures }

Der Korpus ist die veröffentlichte Website: jede Markdown-Seite unter `docs/`
außer dem, was `mkdocs.yml` auslässt (`plans/`, `design/`, `audits/`, die
Roadmap), und außer dieser Seite, die die Fragen und ihre Antworten zitiert. Jede
Sprache wird in eine eigene Collection indexiert, benannt nach dem
Embedding-Modell und einem Digest der Embedding- und Ingestion-Einstellungen,
sodass ein Lauf, der die Chunk-Größe oder das Modell ändert, neu indexiert. Ein
späterer Lauf verwendet eine Collection wieder, solange sie jede Seite in ihrer
aktuellen Fassung enthält, und baut sie neu auf, wenn eine Seite hinzugefügt,
entfernt, umbenannt oder bearbeitet wurde. Eine normale Frage durchsucht alle
zusammen, wie es ein Agent tut, der an mehrere Collections gebunden ist.

Jede Konfiguration ist ein Durchgang über alle 34 Fragen. Die Suche ist der
eigene Pfad des Wissens-Tools: Die Abfrage wird nach `query_analysis_mode`
erweitert, jede Abfrage wird abgerufen, und die Ergebnisse werden zusammengeführt
und auf `top_k` gekürzt. Die erweiterten Abfragen einer Frage werden einmal je
Modus erzeugt und für jedes `top_k` wiederverwendet, sodass zwei `top_k`-Werte
auf denselben Umformulierungen verglichen werden. Je Kategorie meldet der Lauf:

| Zahl | Bedeutung |
|---|---|
| hit@k | Der Anteil der Fragen mit mindestens einem Chunk von einer erwarteten Seite unter den zurückgegebenen `top_k` |
| recall@k | Der Anteil der erwarteten Seiten jeder Frage, die erreicht wurden, gemittelt |
| MRR | Der Mittelwert von 1/Rang des ersten Chunks von einer erwarteten Seite, 0, wenn keiner zurückgegeben wurde |
| Richtige Antworten | Mit `--answers`: wie viele Antworten jeden erwarteten Fakt enthalten |

Nach jeder Tabelle listet der Lauf die Fragen auf, die er verfehlt hat, und die
Seiten, die er stattdessen bekam, und dort steht die nützliche Information.

Die Antwortprüfung ist absichtlich einfach. Ein Fakt passt als ganzes Wort,
Groß- und Kleinschreibung spielt keine Rolle, und eine Alternative, die auf `*`
endet, passt als Präfix (`Keycloak*` passt auf "Keycloaka"). Zitatmarker wie
`[5]` werden ignoriert, sodass eine Passagennummer nie als Zahl in der Antwort
zählt. Ein bloßes „Nein“ reicht nicht: Jede verneinende Frage braucht auch die
Alternative, die die Dokumentation nennt, sodass „die Dokumentation sagt dazu
nichts“ nie besteht. Die Prüfung kann trotzdem eine richtige Antwort nicht von
einer verwirrten unterscheiden, die dieselben Wörter verwendet, also behandle sie
als grobes Signal.

`--json` schreibt die abgerufenen Seiten und die Antwort jeder Frage für jeden,
der sie lesen will, und die Abfragen, nach denen ein `multi_query`- oder
`hyde`-Modus für sie gesucht hat. Die Datei hält auch fest, wodurch der Lauf
zustande kam: wann er begann, einen SHA-256 des Fragensatzes, das
Embedding-Modell und seine Dimension, die Chunk-Einstellungen und Parser sowie
den Digest, den die Collection-Namen tragen.

## Ausführen { #running-it }

Ein Lauf braucht eine migrierte Datenbank mit pgvector (`make dev` liefert eine),
einen Embedding-Endpunkt und, für `multi_query`, `hyde` und `--answers`, ein
Modell. Verwende eine Entwicklungsdatenbank, nicht die eines Deployments. Der
Harness verwirft seine eigenen Collections und baut sie neu auf, und er startet
nicht, wenn eine Wissensdatenbank bereits einen ihrer Namen verwendet.

!!! warning "Jeder Aufruf ist ein echter, abgerechneter Aufruf"
    Der Harness bettet den Korpus und jede Abfrage mit dem Endpunkt ein, den du
    ihm gibst, und ruft das Modell auf, das du nennst. Nichts wird gecacht oder
    vorgetäuscht. Lies [Kosten](#cost) vor dem ersten Lauf.

```bash
export OPENAI_API_KEY=sk-...
make eval-retrieval EVAL_ARGS="--top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --llm-model openai:gpt-4.1-mini --answers --json /tmp/retrieval.json"
```

Die Optionen:

| Option | Standard | |
|---|---|---|
| `--top-k` | `5` | Wiederholbar. Chunks je Suche, das `default_top_k` der Wissens-Capability |
| `--mode` | `off` | Wiederholbar. `off`, `multi_query` oder `hyde`, das `query_analysis_mode` der Capability |
| `--chunk-size` | `2500` | Zeichen je Chunk, wie die Ingestion-Einstellungen einer Collection sie setzen |
| `--chunk-overlap` | `200` | Zeichen, die ein Chunk vom vorigen wiederholt. Muss kleiner als `--chunk-size` sein |
| `--chunking-strategy` | `recursive` | `recursive`, `markdown` oder `fixed` |
| `--max-variants` | `3` | Umformulierungen, die `multi_query` hinzufügen darf |
| `--locale` | `en`, `pl` | Wiederholbar. Die indexierten Sprachen; muss die jeder `cross_language`-Frage enthalten |
| `--embedding-model` | `text-embedding-3-small` | Jedes Modell aus dem Embedding-Katalog, oder ein anderes mit `--embedding-dim` |
| `--embedding-base-url` | `https://api.openai.com/v1` | Jeder OpenAI-kompatible `/v1/embeddings`-Endpunkt |
| `--embedding-api-key-env` | `OPENAI_API_KEY` | Die Variable, aus der der Schlüssel gelesen wird |
| `--keyless` | aus | Der Endpunkt nimmt keinen Schlüssel |
| `--llm-model` | keiner | Ein Pydantic-AI-Modellname. Sein Provider liest seine eigene Schlüsselvariable. `openai:` verwendet die Responses API von OpenAI; andere Endpunkte siehe unten |
| `--answers` | aus | Beantwortet außerdem jede Frage aus dem Abgerufenen und prüft die Fakten |
| `--reingest` | aus | Verwirft die Collections und indexiert den Korpus neu. Ein Lauf tut das von selbst, wenn sich eine Seite oder eine Chunk-Einstellung geändert hat; nach einer Änderung am Parser-Code angeben |
| `--json` | keiner | Schreibt außerdem die Ergebnisse je Frage in diese Datei |

Die Chunk-Optionen werden geprüft wie die Ingestion-Einstellungen einer
Wissensdatenbank, und jede andere Ingestion-Einstellung hat den Standardwert
dieses Formulars. Der Korpus ist Markdown, das der eingebaute Leser unabhängig
vom eingestellten PDF-Parser parst, daher gibt es keine Parser-Option. Der
Harness liest diese Einstellungen aus keinen Umgebungsvariablen.

Ein Fragensatz, den der Loader ablehnt, beendet den Lauf, bevor etwas indexiert
wird, mit einer Meldung, die jede Frage und ihr Problem nennt.

Der Bericht geht auf die Standardausgabe und der Fortschritt auf die
Standardfehlerausgabe, sodass `> results.md` nur den Bericht behält. Der Harness
bricht vor dem Messen ab, wenn eine Seite nicht indexiert werden kann, und ein
abgebrochener Lauf verwirft, was er indexiert hat, weil ein Korpus mit Lücken die
Lücken misst.

### Ohne bezahlten Schlüssel { #without-a-paid-key }

Für die Embeddings funktioniert ein OpenAI-kompatibler Server auf dem eigenen
Rechner. Mit [Ollama](https://ollama.com), nach `ollama pull bge-m3`:

```bash
make eval-retrieval EVAL_ARGS="--embedding-base-url http://localhost:11434/v1 \
    --embedding-model bge-m3 --keyless"
```

`bge-m3` ist mehrsprachig, was für die `cross_language`-Fragen wichtig ist. Die
Zahlen beschreiben dieses Modell, nicht das, das die Collections eines
Deployments verwenden, also vergleiche nur Läufe mit demselben Embedding-Modell.

Ein lokales Modell für `multi_query`, `hyde` und `--answers` braucht das Präfix
`openai-chat:`, weil `openai:` die Responses API aufruft, die die meisten
OpenAI-kompatiblen Server nicht haben. `OPENAI_BASE_URL` richtet den Provider
auf den Server. Setze sie nur für den einen Befehl, wie unten: exportiert würde
sie jeden späteren `openai:`-Aufruf samt seinem Schlüssel an den lokalen Server
schicken. Ohne `OPENAI_API_KEY` sendet der Provider einen Platzhalterschlüssel.
Nach `ollama pull qwen3:8b`:

```bash
OPENAI_BASE_URL=http://localhost:11434/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url http://localhost:11434/v1 --embedding-model bge-m3 --keyless \
    --mode multi_query --llm-model openai-chat:qwen3:8b"
```

Dasselbe gilt für jeden Endpunkt, der nur Chat Completions anbietet.

## Kosten { #cost }

Der veröffentlichte Korpus umfasst etwa 0,6 Millionen Tokens auf Englisch und
1,0 Millionen auf Polnisch, gemessen mit dem Tokenizer `cl100k_base`, den die
Embedding-Modelle von OpenAI verwenden. Mit der Chunk-Überlappung von 200 Zeichen
sind es für das Indexieren beider Sprachen etwa 1,7 Millionen Tokens. Das wird
einmal bezahlt, und für eine Sprache erneut, wenn sich eine ihrer Seiten ändert
oder mit `--reingest`.

| Teil | Tokens je Lauf | Zum Listenpreis |
|---|---|---|
| Indexieren, `text-embedding-3-small` | ~1,7M, einmalig | ~$0.03 |
| Indexieren, `text-embedding-3-large` | ~1,7M, einmalig | ~$0.22 |
| Einbetten der Fragen | unter 10k je Konfiguration | unter $0.01 |
| `multi_query` oder `hyde`, `gpt-4.1-mini` | ~34 Aufrufe, ~10k Tokens je Konfiguration | unter $0.01 |
| `--answers` bei `top_k` 5, `gpt-4.1-mini` | ~34 Aufrufe, ~150k Eingabe- und ~5k Ausgabe-Tokens | ~$0.07 |
| `--answers` bei `top_k` 10, `gpt-4.1-mini` | ~300k Eingabe- und ~5k Ausgabe-Tokens | ~$0.13 |

Die Preise sind Listenpreise je Million Tokens zum Zeitpunkt des Schreibens:
`text-embedding-3-small` $0.02, `text-embedding-3-large` $0.13, `gpt-4.1-mini`
$0.40 Eingabe und $1.60 Ausgabe. Prüfe die aktuellen Preise deines Providers. Mit
diesen Preisen kostet die volle Matrix aus zwei `top_k`-Werten, drei Modi und
Antworten unter einem Dollar. Am Ende gibt der Lauf die Modellaufrufe aus, die er
gemacht hat, und ihre Tokens.

## Was sie nicht entscheidet { #what-it-does-not-decide }

Die Suite misst; sie ändert keine Standardwerte. Die Wissens-Capability behält
`default_top_k` 5 und `query_analysis_mode` `off`, bis ein gemessener Lauf eine
Änderung stützt. Die Suite testet auch keine Berechtigungen. Ihre Collections
gehören zu keiner Organisation und werden ohne Einschränkung durchsucht, wie es
`rag-search` tut. Die Seiten zur [Dateiverarbeitung](file-processing.md) und zur
[Wissens-Capability](reference/capabilities.md#query-analysis-and-expansion)
beschreiben die eingeschränkte Suche.
