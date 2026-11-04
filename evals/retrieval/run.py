"""Measure retrieval over the repository's own docs, and print the report.

    uv run --directory backend python ../evals/retrieval/run.py \
        --top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
        --llm-model openai:gpt-4.1-mini --answers

What it needs is in `docs/retrieval-eval.md`: a migrated database with pgvector,
an embedding key (or a local OpenAI-compatible endpoint), and, for `multi_query`,
`hyde` and `--answers`, a model. Every call it makes is a real, billed one.

The docs are ingested once per locale into collections of their own
(`retrieval_eval_<embedding model>_en`, `..._pl`), which later runs reuse. Retrieval is
the knowledge tool's own path - `plan_queries`, then `fuse_over_queries` over
`RetrievalService` - read under the operator's unscoped marker as `rag-search`
does, since these collections belong to no organization. Each configuration in
`--top-k` x `--mode` is one pass over the whole question set.

Nothing under `app/` imports this directory. `dataset.py` and `scoring.py` are
pure and tested in `backend/tests/test_retrieval_eval.py`; this file is wiring.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import get_args

from dataset import Dataset, Item, Locale, corpus_files, load_dataset, page_key
from pydantic_ai import Agent
from pydantic_ai.usage import RunUsage
from scoring import Answer, Retrieve, Retrieved, as_json, evaluate, render_markdown

from app.db.session import close_db, get_db_context
from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo
from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.documents import DocumentProcessor
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.filters import UnscopedScope
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus, SearchResult
from app.services.rag.query_analysis import GenerateText, QueryAnalysisMode, plan_queries
from app.services.rag.retrieval import RetrievalService, fuse_over_queries
from app.services.rag.vectorstore import BaseVectorStore, process_vector_store

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
MODES: dict[str, QueryAnalysisMode] = {mode: mode for mode in get_args(QueryAnalysisMode)}

ANSWER_INSTRUCTIONS = (
    "You answer questions about AgenticOS using only the numbered passages you are given. "
    "If the passages say something is not supported, say no plainly and give the alternative "
    "they name. If they do not answer the question, say the documentation does not state it. "
    "Answer in the language of the question, in at most four sentences, citing passages as [1], [2]."
)


async def refuse_held_names(collections: list[str]) -> None:
    """Stop when a knowledge base already uses one of the eval's collection names.

    A collection name is one physical table that every organization shares, and
    the harness drops and reads its collections unscoped. A base holding the
    same name would lose its vectors to `--reingest`, and lend its chunks to the
    report, so the run refuses instead - as `rag-drop` refuses a held name
    (#2560). Run it against a development database, not a deployment's.
    """
    async with get_db_context() as db:
        held = [
            name
            for name in collections
            if await knowledge_base_repo.list_by_collection_name(db, name)
        ]
    if held:
        raise SystemExit(
            f"A knowledge base already uses {', '.join(held)}. Pass another --collection-prefix, "
            "and run this against a development database rather than a deployment's."
        )


async def ingest(
    store: BaseVectorStore,
    ingestion: IngestionService,
    collection: str,
    files: list[Path],
    *,
    docs_root: Path,
    reingest: bool,
) -> None:
    """Fill `collection` with `files`, unless an earlier run already indexed all of them.

    A collection holding a different number of documents - an earlier run that
    was interrupted, or a docs tree that gained or lost pages since - is built
    again rather than measured: a corpus with holes measures the holes. Each
    document is stored under its path relative to `docs/`, so a collection
    indexed from one checkout reads the same from another.
    """
    stored = await store.get_documents(collection, VectorScope(tenant=None))
    if stored and not reingest and len(stored) == len(files):
        print(
            f"{collection}: reusing what an earlier run indexed (--reingest to rebuild)",
            file=sys.stderr,
        )
        return
    await store.delete_collection(collection)
    print(f"{collection}: indexing {len(files)} pages", file=sys.stderr)
    failed: list[str] = []
    try:
        for path in files:
            relative = path.relative_to(docs_root).as_posix()
            # `replace=False`: the collection was just emptied, and the replace
            # lookup falls back to a bare file name, which would let
            # `howto/code-review.md` replace `code-review.md`.
            result = await ingestion.ingest_file(
                path, collection, replace=False, source_path=relative
            )
            if result.status != IngestionStatus.DONE:
                failed.append(f"{relative}: {result.error_message}")
    except BaseException:
        # Interrupted part-way: leave nothing a later run would take for a corpus.
        await store.delete_collection(collection)
        raise
    if failed:
        await store.delete_collection(collection)
        raise SystemExit(
            f"{collection}: {len(failed)} file(s) failed to ingest:\n  " + "\n  ".join(failed)
        )


def _retrieved(result: SearchResult) -> Retrieved:
    source = result.metadata.get("source_path")
    if not isinstance(source, str) or not source:
        raise SystemExit(f"A chunk carries no source_path: {result.metadata}")
    key, _locale = page_key(source)
    return Retrieved(page=key, content=result.content, score=result.score)


def _generate(model: str | None, usage: RunUsage) -> GenerateText | None:
    if model is None:
        return None
    agent = Agent(model)

    async def generate(prompt: str) -> str:
        result = await agent.run(prompt)
        usage.incr(result.usage)
        return result.output

    return generate


def retriever(
    retrieval: RetrievalService,
    *,
    collections: dict[Locale, str],
    top_k: int,
    mode: QueryAnalysisMode,
    max_variants: int,
    generate: GenerateText | None,
) -> Retrieve:
    """One configuration's search: the knowledge tool's plan-retrieve-fuse, per item."""

    async def retrieve(item: Item) -> list[Retrieved]:
        names = [collections[locale] for locale in (item.search_locales or tuple(collections))]
        queries = await plan_queries(
            item.question, mode=mode, max_variants=max_variants, generate=generate
        )

        async def retrieve_one(query: str) -> list[SearchResult]:
            if len(names) == 1:
                return await retrieval.retrieve(
                    query=query, collection_name=names[0], scope=UnscopedScope(), limit=top_k
                )
            return await retrieval.retrieve_multi(
                query=query,
                collection_names=names,
                scopes={name: UnscopedScope() for name in names},
                limit=top_k,
            )

        results = await fuse_over_queries(queries, retrieve_one, limit=top_k)
        return [_retrieved(result) for result in results]

    return retrieve


def answerer(model: str, usage: RunUsage) -> Answer:
    agent = Agent(model, instructions=ANSWER_INSTRUCTIONS)

    async def answer(item: Item, retrieved: list[Retrieved]) -> str:
        passages = "\n\n".join(
            f"[{index}] Source: {chunk.page}\n{chunk.content}"
            for index, chunk in enumerate(retrieved, start=1)
        )
        result = await agent.run(f"Passages:\n\n{passages}\n\nQuestion: {item.question}")
        usage.incr(result.usage)
        return result.output

    return answer


async def measure(arguments: argparse.Namespace) -> tuple[str, list[dict[str, object]]]:
    docs_root = Path(arguments.docs).resolve()
    dataset: Dataset = load_dataset(Path(arguments.dataset), docs_root=docs_root)
    locales: tuple[Locale, ...] = tuple(arguments.locale or ("en", "pl"))
    needed = {locale for item in dataset.items for locale in (item.search_locales or ())}
    if not needed <= set(locales):
        raise SystemExit(
            f"--locale must include {sorted(needed)}: cross_language items search them"
        )

    api_key = os.environ.get(arguments.embedding_api_key_env, "")
    if not api_key and not arguments.keyless:
        raise SystemExit(
            f"Set {arguments.embedding_api_key_env}, or pass --keyless for a local endpoint"
        )
    if arguments.llm_model is None and (arguments.answers or set(arguments.mode or ()) - {"off"}):
        raise SystemExit("multi_query, hyde and --answers need --llm-model")

    settings = RAGSettings(embeddings_config=EmbeddingsConfig(model=arguments.embedding_model))
    if arguments.embedding_dim:
        settings.embeddings_config.dim = arguments.embedding_dim
    embedder = EmbeddingService(
        settings,
        api_key=api_key,
        base_url=arguments.embedding_base_url,
        keyless=arguments.keyless,
        key_origin=f"the {arguments.embedding_api_key_env} variable",
    )
    store = process_vector_store(settings, embedder)
    retrieval = RetrievalService(vector_store=store, settings=settings)
    ingestion = IngestionService(processor=DocumentProcessor(settings), vector_store=store)
    # The model is in the name, so a run with another embedding model builds its
    # own collections rather than searching vectors it cannot compare with.
    model_slug = re.sub(r"[^a-z0-9]+", "_", arguments.embedding_model.lower()).strip("_")[:32]
    collections: dict[Locale, str] = {
        locale: f"{arguments.collection_prefix}_{model_slug}_{locale}" for locale in locales
    }
    await refuse_held_names(list(collections.values()))
    for locale, collection in collections.items():
        await ingest(
            store,
            ingestion,
            collection,
            corpus_files(docs_root, locale),
            docs_root=docs_root,
            reingest=arguments.reingest,
        )

    usage = RunUsage()
    generate = _generate(arguments.llm_model, usage)
    answer = answerer(arguments.llm_model, usage) if arguments.answers else None
    sections = [
        f"## Retrieval over docs/ ({', '.join(locales)}), question set v{dataset.version}, "
        f"{len(dataset.items)} questions, embeddings {arguments.embedding_model}",
        "",
    ]
    reports: list[dict[str, object]] = []
    for top_k in arguments.top_k or [5]:
        for mode in (MODES[name] for name in arguments.mode or ["off"]):
            label = f"top_k={top_k}, query_analysis_mode={mode}"
            print(f"measuring {label}", file=sys.stderr)
            search = retriever(
                retrieval,
                collections=collections,
                top_k=top_k,
                mode=mode,
                max_variants=arguments.max_variants,
                generate=generate,
            )
            results = await evaluate(dataset, search, answer)
            sections.append(render_markdown(label, results))
            reports.append(as_json(label, top_k, mode, results))
    if arguments.llm_model is not None:
        sections.append(
            f"Model calls ({arguments.llm_model}): {usage.requests} requests, "
            f"{usage.input_tokens} input and {usage.output_tokens} output tokens.\n"
        )
    return "\n".join(sections), reports


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset", default=str(HERE / "docs_questions.yaml"))
    parser.add_argument(
        "--docs", default=str(REPO_ROOT / "docs"), help="the corpus root (default: docs/)"
    )
    parser.add_argument(
        "--locale",
        action="append",
        choices=["en", "pl", "de", "es"],
        help="repeatable; default en and pl",
    )
    parser.add_argument("--collection-prefix", default="retrieval_eval")
    parser.add_argument("--reingest", action="store_true", help="drop and rebuild the collections")
    parser.add_argument("--top-k", action="append", type=int, help="repeatable; default 5")
    parser.add_argument(
        "--mode", action="append", choices=list(MODES), help="repeatable; default off"
    )
    parser.add_argument(
        "--max-variants", type=int, default=3, help="multi_query's rephrasings (default 3)"
    )
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--embedding-dim", type=int, help="only for a model the catalog does not know"
    )
    parser.add_argument("--embedding-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--embedding-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--keyless", action="store_true", help="the endpoint takes no key (a local Ollama)"
    )
    parser.add_argument("--llm-model", help="a Pydantic AI model name, e.g. openai:gpt-4.1-mini")
    parser.add_argument(
        "--answers", action="store_true", help="also answer each question and check its facts"
    )
    parser.add_argument("--json", help="also write the per-item results to this file")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    arguments = parse(argv)
    try:
        report, reports = await measure(arguments)
    finally:
        await close_db()
    print(report)
    if arguments.json:
        Path(arguments.json).write_text(
            json.dumps(reports, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
