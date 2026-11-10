---
title: Retrieval evaluation
description: A question set over the AgenticOS docs with known answers, and the harness that measures knowledge retrieval on it, by category, top_k and query expansion.
---

# Retrieval evaluation

A knowledge agent is only as good as what its search hands the model. A change
to chunking, to `top_k` or to query expansion moves that, and an answer that
reads well says nothing about whether the right page was retrieved. So there is
a question set with known answers over these docs, and a harness that measures
retrieval on it, in `evals/retrieval/`. This page is what it measures, how to
run it, and what a run costs.

It started with one question ([#2482](https://github.com/vstorm-co/agenticos/issues/2482)).
Asked *"Does AgenticOS support SAML single sign-on?"*, an agent over the docs
retrieved only the Dify comparison page and answered that the documentation does
not say. [Directory sign-in](directory.md) says plainly that there is no SAML, and
how to reach AgenticOS through Keycloak instead.

## The question set

`evals/retrieval/docs_questions.yaml` holds 34 questions in three categories:

| Category | What it tests | Example |
|---|---|---|
| `factual` | A stated setting, default or name | "If I never set a vault master key, what does the platform encrypt credentials with?" |
| `negative` | A "do you support X" question the docs answer with a plain no | "Does AgenticOS support SAML single sign-on?" |
| `cross_language` | A Polish question answered from the English pages only, or an English question from the Polish pages only | "Czy da się logować do AgenticOS przez SAML?" |

Each question names its expected pages and, for the answer check, the facts a
correct answer contains. An entry looks like this:

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

A page is named without its language: `directory.md` is also `directory.pl.md`,
so a chunk from either translation counts as finding it. A `cross_language`
question adds `search_locales`, the only language its search may read, which is
never the language it is asked in. The file is versioned, and a change to what a
field means increases `version`. The loader refuses an expected page that does
not exist or is not published, so renaming a page fails the unit tests rather
than becoming a miss in a run somebody paid for.

## What a run measures

The corpus is the published site: every Markdown page under `docs/` except what
`mkdocs.yml` leaves out (`plans/`, `design/`, `audits/`, the roadmap), and
except this page, which quotes the questions and their answers. Each language is
indexed into its own collection, named after the embedding model and a digest of
the embedding and ingestion settings, so a run that changes the chunk size or the
model indexes afresh. A later run reuses a collection while it holds every page
as the page is now, and builds it again when a page was added, removed, renamed
or edited. A normal question
searches all of them together, as an agent bound to several collections does.

Each configuration is one pass over all 34 questions. Search is the knowledge
tool's own path: the query is expanded by `query_analysis_mode`, every query is
retrieved, and the results are fused and cut to `top_k`. A question's expanded
queries are generated once per mode and reused for every `top_k`, so two `top_k`
values are compared on the same rephrasings. Per category, the run reports:

| Number | Meaning |
|---|---|
| hit@k | The share of questions with at least one chunk from an expected page in the `top_k` returned |
| recall@k | The share of each question's expected pages that were reached, averaged |
| MRR | The mean of 1/rank of the first chunk from an expected page, 0 when none was returned |
| Answers correct | With `--answers`: how many answers contain every expected fact |

After each table the run lists the questions it missed and the pages it got
instead, which is where the useful information is.

The answer check is deliberately simple. A fact matches as a whole word, case
does not matter, and an alternative ending in `*` matches as a prefix
(`Keycloak*` matches "Keycloaka"). Citation markers such as `[5]` are ignored, so
a passage number never counts as a number in the answer. A plain "no" is not
enough: every negative question also needs the alternative the docs name, so
"the documentation does not say" never passes. The check still cannot tell a
correct answer from a confused one that uses the same words, so treat it as a
rough signal.

`--json` writes every question's retrieved pages and answer for anyone who
wants to read them, and the queries a `multi_query` or `hyde` mode
searched for it. The file also records what produced the run: when it started,
a SHA-256 of the question set, the embedding model and its dimension, the chunk
settings and parsers, and the digest the collection names carry.

## Running it

A run needs a migrated database with pgvector (`make dev` gives you one), an
embedding endpoint and, for `multi_query`, `hyde` and `--answers`, a model. Use a
development database, not a deployment's. The harness drops and rebuilds its own
collections, and it refuses to start when a knowledge base already uses one of
their names.

!!! warning "Every call is a real, billed call"
    The harness embeds the corpus and every query with the endpoint you give it,
    and calls the model you name. Nothing is cached or faked. Read [Cost](#cost)
    before the first run.

```bash
export OPENAI_API_KEY=sk-...
make eval-retrieval EVAL_ARGS="--top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --llm-model openai:gpt-4.1-mini --answers --json /tmp/retrieval.json"
```

The options:

| Option | Default | |
|---|---|---|
| `--top-k` | `5` | Repeatable, 1–50. Chunks per search, the knowledge capability's `default_top_k` |
| `--mode` | `off` | Repeatable. `off`, `multi_query` or `hyde`, the capability's `query_analysis_mode` |
| `--chunk-size` | `2500` | Characters per chunk, as a collection's ingestion settings set it |
| `--chunk-overlap` | `200` | Characters a chunk repeats from the one before. Must be smaller than `--chunk-size` |
| `--chunking-strategy` | `recursive` | `recursive`, `markdown` or `fixed` |
| `--max-variants` | `3` | Rephrasings `multi_query` may add, 1–5 |
| `--locale` | `en`, `pl` | Repeatable. The languages indexed; must include each `cross_language` question's |
| `--embedding-model` | `text-embedding-3-small` | Any model in the embedding catalog, or another with `--embedding-dim` |
| `--embedding-dim` | from the model catalog | Positive dimension for a model outside the catalog |
| `--embedding-base-url` | `https://api.openai.com/v1` | Any OpenAI-compatible `/v1/embeddings` endpoint |
| `--embedding-api-key-env` | `OPENAI_API_KEY` | The variable the key is read from |
| `--keyless` | off | The endpoint takes no key |
| `--llm-model` | none | A Pydantic AI model name. Its provider reads its own key variable. `openai:` uses OpenAI's Responses API; see below for other endpoints |
| `--answers` | off | Also answer each question from what was retrieved, and check the facts |
| `--reingest` | off | Drop the collections and index the corpus again. A run does this by itself when a page or a chunk setting changed; pass it after a change to parser code |
| `--json` | none | Also write the per-question results to this file |

The chunk options are checked as a knowledge base's ingestion settings are, and
every other ingestion setting is that form's default. The corpus is Markdown,
which the built-in reader parses whatever PDF parser is set, so there is no
parser option. The harness reads no environment variables for these settings.

A question set the loader refuses stops the run before anything is indexed,
with one message that names each item and its problem.

The report goes to standard output and progress to standard error, so
`> results.md` keeps the report alone. The harness stops before measuring if a
page fails to index, and an interrupted run drops what it indexed, because a
corpus with gaps measures the gaps.

### Without a paid key

An OpenAI-compatible server on your own machine works for the embeddings. With
[Ollama](https://ollama.com), after `ollama pull bge-m3`:

```bash
make eval-retrieval EVAL_ARGS="--embedding-base-url http://localhost:11434/v1 \
    --embedding-model bge-m3 --keyless"
```

`bge-m3` is multilingual, which matters for the `cross_language` questions. The
numbers describe that model, not the one a deployment's collections use, so
compare runs with the same embedding model only.

A local model for `multi_query`, `hyde` and `--answers` needs the
`openai-chat:` prefix, because `openai:` calls the Responses API, which most
OpenAI-compatible servers do not have. `OPENAI_BASE_URL` points the provider at
the server. Set it for the one command, as below: exported, it would send every
later `openai:` call, and the key that goes with it, to the local server.
Without `OPENAI_API_KEY` the provider sends a placeholder key. After
`ollama pull qwen3:8b`:

```bash
OPENAI_BASE_URL=http://localhost:11434/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url http://localhost:11434/v1 --embedding-model bge-m3 --keyless \
    --mode multi_query --llm-model openai-chat:qwen3:8b"
```

The same applies to any endpoint that offers chat completions only.

## Cost

The published corpus is about 0.6 million tokens in English and 1.0 million in
Polish, measured with the `cl100k_base` tokenizer that OpenAI's embedding models
use. With the 200-character chunk overlap, indexing both languages is about 1.7
million tokens. It is paid once, and again for a language when one of its pages
changes or with `--reingest`.

| Part | Tokens per run | At list price |
|---|---|---|
| Indexing, `text-embedding-3-small` | ~1.7M, once | ~$0.03 |
| Indexing, `text-embedding-3-large` | ~1.7M, once | ~$0.22 |
| Embedding the questions | under 10k per configuration | under $0.01 |
| `multi_query` or `hyde`, `gpt-4.1-mini` | ~34 calls, ~10k tokens per configuration | under $0.01 |
| `--answers` at `top_k` 5, `gpt-4.1-mini` | ~34 calls, ~150k input and ~5k output tokens | ~$0.07 |
| `--answers` at `top_k` 10, `gpt-4.1-mini` | ~300k input and ~5k output tokens | ~$0.13 |

The prices are list prices per million tokens at the time of writing:
`text-embedding-3-small` $0.02, `text-embedding-3-large` $0.13, `gpt-4.1-mini`
$0.40 input and $1.60 output. Check your provider's current prices. With these
prices, the full matrix of two `top_k` values, three modes and answers costs
under a dollar. The run prints the model calls it made and their tokens at the
end.

## What it does not decide

The suite measures; it does not change any defaults. The knowledge capability
keeps `default_top_k` 5 and `query_analysis_mode` `off` until a measured run
supports a change. The suite also does not test permissions. Its collections
belong to no organization and are searched unscoped, as `rag-search` does. The
[file processing](file-processing.md) and
[knowledge capability](reference/capabilities.md#query-analysis-and-expansion)
pages describe scoped search.
