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
import hashlib
import json
import os
import re
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, get_args

from dataset import Dataset, DatasetError, Item, Locale, corpus_files, load_dataset, page_key
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.usage import RunUsage
from scoring import Answer, Retrieve, Retrieved, as_json, evaluate, render_markdown
from sqlalchemy import BigInteger, cast, func, select

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.db.session import close_db, get_db_context, get_worker_connection
from app.db.vector_tables import VectorScope, validate_collection_name
from app.repositories import knowledge_base_repo
from app.services.ingestion_config import ChunkingStrategy, IngestionConfig, rag_settings_for
from app.services.rag.config import EMBEDDING_DIMENSIONS, EmbeddingsConfig, RAGSettings
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
LOCALES: dict[str, Locale] = {locale: locale for locale in get_args(Locale)}
MODES: dict[str, QueryAnalysisMode] = {mode: mode for mode in get_args(QueryAnalysisMode)}
CORPUS_FINGERPRINT_ALGORITHM = "sha256-path-content-v1"

ANSWER_INSTRUCTIONS = (
    "You answer questions about AgenticOS using only the numbered passages you are given. "
    "If the passages say something is not supported, say no plainly and give the alternative "
    "they name. If they do not answer the question, say the documentation does not state it. "
    "Answer in the language of the question, in at most four sentences, citing passages as [1], [2]."
)


class CorpusFingerprint(TypedDict):
    """Identity of one locale's source pages, captured before indexing."""

    pages: int
    sha256: str


def corpus_fingerprint(files: list[Path], *, docs_root: Path) -> CorpusFingerprint:
    """Hash sorted [relative POSIX path, SHA-256(source bytes)] pairs as compact UTF-8 JSON."""
    manifest = sorted(
        (path.relative_to(docs_root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in files
    )
    encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"pages": len(manifest), "sha256": hashlib.sha256(encoded).hexdigest()}


async def refuse_held_names(collections: list[str]) -> None:
    """Stop when a knowledge base already uses one of the eval's collection names.

    A collection name is one physical table that every organization shares, and
    the harness drops, rebuilds and reads its collections unscoped. A base
    holding the same name would lose its vectors, and lend its chunks to the
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


@asynccontextmanager
async def collection_locks(collections: list[str]) -> AsyncGenerator[None]:
    """Reserve every collection through indexing and measurement, or refuse a busy run.

    Session locks survive ingestion's independent commits. The dedicated NullPool
    connection releases them on exit, including cancellation or a partial acquisition.
    The namespace uses Postgres's separate bigint advisory-lock key space.
    """
    async with get_worker_connection() as connection:
        for name in sorted(set(collections)):
            digest = hashlib.sha256(f"agenticos:retrieval-eval:{name}".encode()).digest()
            key = int.from_bytes(digest[:8], byteorder="big", signed=True)
            result = await connection.execute(
                select(func.pg_try_advisory_lock(cast(key, BigInteger)))
            )
            acquired = bool(result.scalar_one())
            await connection.commit()
            if not acquired:
                raise SystemExit(
                    f"Another retrieval evaluation is using {name}. Wait for it to finish "
                    "or choose another --collection-prefix."
                )
        yield


async def ingest(
    store: BaseVectorStore,
    ingestion: IngestionService,
    collection: str,
    files: list[Path],
    *,
    docs_root: Path,
    reingest: bool,
) -> None:
    """Fill `collection` with `files`, unless it already holds exactly these pages.

    "Exactly" is each page's path and content hash. A collection that differs -
    an earlier run that was interrupted, or a page added, removed, renamed or
    edited since - is built again rather than measured: a stale corpus measures
    the docs as they were. Each page is stored under its path relative to
    `docs/`, so a collection indexed from one checkout reads the same from
    another.
    """
    stored = await store.get_documents(collection, VectorScope(tenant=None))
    held = {
        (str(info.get("source_path")), str(info.get("content_hash")))
        for info in (document.additional_info or {} for document in stored)
    }
    wanted = {
        (path.relative_to(docs_root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in files
    }
    if not reingest and held == wanted:
        print(
            f"{collection}: reusing what an earlier run indexed (--reingest to rebuild)",
            file=sys.stderr,
        )
        return
    await store.delete_collection(collection)
    print(f"{collection}: indexing {len(files)} pages", file=sys.stderr)
    failure: str | None = None
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
                failure = f"{relative}: {result.error_message}"
                break
    except BaseException:
        # Interrupted part-way: leave nothing a later run would take for a corpus.
        await store.delete_collection(collection)
        raise
    if failure is not None:
        await store.delete_collection(collection)
        raise SystemExit(f"{collection}: failed to ingest {failure}")


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


_CONFIG_FIELD = re.compile(r"\b(?:chunk_size|chunk_overlap)\b")


def _flag(field: str) -> str:
    """The option that sets an `IngestionConfig` field: `chunk_size` is `--chunk-size`."""
    return "--" + field.replace("_", "-")


def rag_settings(arguments: argparse.Namespace) -> RAGSettings:
    """The pipeline a knowledge base configured with the run's chunk flags would get.

    The flags go through `IngestionConfig`, the model a collection's ingestion
    form saves, so a value the product refuses - an overlap as large as the
    chunk, a size outside its bounds - is refused here too, and the rest of the
    settings are that model's defaults.
    """
    try:
        config = IngestionConfig(
            chunk_size=arguments.chunk_size,
            chunk_overlap=arguments.chunk_overlap,
            chunking_strategy=ChunkingStrategy(arguments.chunking_strategy),
        )
    except ValidationError as error:
        problems = [
            f"{_flag(str(e['loc'][0]))}: {e['msg']}"
            if e["loc"]
            else _CONFIG_FIELD.sub(
                lambda match: _flag(match[0]), str(e.get("ctx", {}).get("error", e["msg"]))
            )
            for e in error.errors(include_url=False)
        ]
        raise SystemExit("; ".join(problems)) from None
    catalogued = arguments.embedding_model in EMBEDDING_DIMENSIONS
    if catalogued and arguments.embedding_dim is not None:
        raise SystemExit("--embedding-dim is only accepted for models outside the catalog")
    if not catalogued and arguments.embedding_dim is None:
        raise SystemExit(
            f"--embedding-dim is required for uncatalogued embedding model "
            f"{arguments.embedding_model!r}"
        )
    settings = rag_settings_for(config)
    settings.embeddings_config = EmbeddingsConfig(model=arguments.embedding_model)
    if arguments.embedding_dim:
        settings.embeddings_config.dim = arguments.embedding_dim
    return settings


def collection_digest(settings: RAGSettings, base_url: str) -> str:
    """A short hash of everything that shaped a collection's vectors."""
    identity = json.dumps(
        {"base_url": base_url, "settings": settings.model_dump(mode="json")}, sort_keys=True
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:10]


def collection_names(
    prefix: str, settings: RAGSettings, base_url: str, locales: tuple[Locale, ...]
) -> dict[Locale, str]:
    """One collection per locale, named after everything that shaped its vectors.

    The digest covers the embedding model, its width and endpoint and every
    ingestion setting - chunk size and overlap, chunking strategy, parsers - so
    changing any of them, which is what a comparison run does, indexes afresh
    instead of reusing chunks the old pipeline produced. The readable part of
    the model name is only a label; two models whose names shorten alike still
    get two collections. A change to parser *code* is not in it: pass
    `--reingest` after one.
    """
    digest = collection_digest(settings, base_url)
    label = re.sub(r"[^a-z0-9]+", "_", settings.embeddings_config.model.lower()).strip("_")[:12]
    names: dict[Locale, str] = {locale: f"{prefix}_{label}_{digest}_{locale}" for locale in locales}
    try:
        for name in names.values():
            validate_collection_name(name, metadata=Base.metadata)
    except BadRequestError as error:
        raise SystemExit(f"--collection-prefix: {error.message}") from None
    return names


QueryPlans = dict[tuple[str, str], list[str]]
"""The queries planned for each (item id, mode), shared by every `top_k` in a run."""


def retriever(
    retrieval: RetrievalService,
    *,
    collections: dict[Locale, str],
    top_k: int,
    mode: QueryAnalysisMode,
    max_variants: int,
    generate: GenerateText | None,
    plans: QueryPlans,
) -> Retrieve:
    """One configuration's search: the knowledge tool's plan-retrieve-fuse, per item.

    An item's queries are planned once per mode and reused for every `top_k`:
    `multi_query` and `hyde` generate text, and two generations differ, so
    planning again would compare different rephrasings rather than two `top_k`.
    """

    async def retrieve(item: Item) -> list[Retrieved]:
        names = [collections[locale] for locale in (item.search_locales or tuple(collections))]
        key = (item.id, mode)
        if key not in plans:
            plans[key] = await plan_queries(
                item.question, mode=mode, max_variants=max_variants, generate=generate
            )
        queries = plans[key]

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


async def measure(arguments: argparse.Namespace) -> tuple[str, dict[str, object]]:
    docs_root = Path(arguments.docs).resolve()
    locales = tuple(dict.fromkeys(LOCALES[name] for name in arguments.locale or ("en", "pl")))
    started_at = datetime.now(UTC)
    try:
        dataset = load_dataset(Path(arguments.dataset), docs_root=docs_root, locales=locales)
    except DatasetError as error:
        raise SystemExit(str(error)) from None
    settings = rag_settings(arguments)
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

    collections = collection_names(
        arguments.collection_prefix, settings, arguments.embedding_base_url, locales
    )
    modes = [MODES[name] for name in arguments.mode or ["off"]]
    usage = RunUsage()
    generate = (
        _generate(arguments.llm_model, usage) if any(mode != "off" for mode in modes) else None
    )
    answer = answerer(arguments.llm_model, usage) if arguments.answers else None
    files = {locale: corpus_files(docs_root, locale) for locale in locales}
    corpus = {
        locale: corpus_fingerprint(paths, docs_root=docs_root) for locale, paths in files.items()
    }
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
    async with collection_locks(list(collections.values())):
        await refuse_held_names(list(collections.values()))
        for locale, collection in collections.items():
            await ingest(
                store,
                ingestion,
                collection,
                files[locale],
                docs_root=docs_root,
                reingest=arguments.reingest,
            )

        sections = [
            f"## Retrieval over docs/ ({', '.join(locales)}), question set v{dataset.version}, "
            f"{len(dataset.items)} questions, embeddings {arguments.embedding_model}",
            "",
        ]
        sections.extend(
            f"Corpus `{locale}`: {snapshot['pages']} pages; SHA-256 `{snapshot['sha256']}` "
            f"({CORPUS_FINGERPRINT_ALGORITHM})."
            for locale, snapshot in corpus.items()
        )
        sections.append("")
        reports: list[dict[str, object]] = []
        plans: QueryPlans = {}
        for top_k in arguments.top_k or [5]:
            for mode in modes:
                label = f"top_k={top_k}, query_analysis_mode={mode}"
                print(f"measuring {label}", file=sys.stderr)
                search = retriever(
                    retrieval,
                    collections=collections,
                    top_k=top_k,
                    mode=mode,
                    max_variants=arguments.max_variants,
                    generate=generate,
                    plans=plans,
                )
                results = await evaluate(dataset, search, answer)
                sections.append(render_markdown(label, results))
                planned = (
                    None if mode == "off" else {i.id: plans[(i.id, mode)] for i in dataset.items}
                )
                reports.append(as_json(label, top_k, mode, results, queries=planned))
        if arguments.llm_model is not None:
            sections.append(
                f"Model calls ({arguments.llm_model}): {usage.requests} requests, "
                f"{usage.input_tokens} input and {usage.output_tokens} output tokens.\n"
            )
        exported = provenance(
            arguments,
            dataset=dataset,
            settings=settings,
            locales=locales,
            collections=collections,
            corpus=corpus,
            started_at=started_at,
            reports=reports,
        )
        return "\n".join(sections), exported


def provenance(
    arguments: argparse.Namespace,
    *,
    dataset: Dataset,
    settings: RAGSettings,
    locales: tuple[Locale, ...],
    collections: dict[Locale, str],
    corpus: dict[Locale, CorpusFingerprint],
    started_at: datetime,
    reports: list[dict[str, object]],
) -> dict[str, object]:
    """What `--json` writes: the results, and enough to say what produced them.

    Keys are only ever added, so a file written by an earlier run still reads.
    `dataset_sha256` tells two edits of one `version` apart; `ingestion` and
    `collection_digest` are what the collection names were derived from. `corpus`
    identifies the source pages captured before indexing, without re-reading
    files that may have changed while model calls ran.
    """
    return {
        "dataset": str(arguments.dataset),
        "dataset_version": dataset.version,
        "dataset_sha256": dataset.sha256,
        "started_at": started_at.isoformat(),
        "questions": len(dataset.items),
        "locales": list(locales),
        "embedding_model": arguments.embedding_model,
        "embedding_dim": settings.embeddings_config.dim,
        "embedding_base_url": arguments.embedding_base_url,
        "ingestion": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "chunking_strategy": settings.chunking_strategy,
            "document_parser": settings.document_parser.method,
            "pdf_parser": settings.pdf_parser.method,
        },
        "collection_digest": collection_digest(settings, arguments.embedding_base_url),
        "collections": collections,
        "corpus": corpus,
        "corpus_fingerprint_algorithm": CORPUS_FINGERPRINT_ALGORITHM,
        "llm_model": arguments.llm_model,
        "max_variants": arguments.max_variants,
        "configurations": reports,
    }


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
        choices=list(LOCALES),
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
    defaults = IngestionConfig()
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=defaults.chunk_size,
        help=f"characters per chunk (default {defaults.chunk_size})",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=defaults.chunk_overlap,
        help=f"characters a chunk repeats from the last (default {defaults.chunk_overlap})",
    )
    parser.add_argument(
        "--chunking-strategy",
        choices=[strategy.value for strategy in ChunkingStrategy],
        default=defaults.chunking_strategy.value,
        help=f"default {defaults.chunking_strategy.value}",
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
    parser.add_argument(
        "--llm-model",
        help="a Pydantic AI model name, e.g. openai:gpt-4.1-mini; openai-chat:<model> for "
        "a chat-completions-only or local OpenAI-compatible endpoint",
    )
    parser.add_argument(
        "--answers", action="store_true", help="also answer each question and check its facts"
    )
    parser.add_argument("--json", help="also write the per-item results to this file")
    arguments = parser.parse_args(argv)
    for option, values, maximum in (
        ("--top-k", arguments.top_k or (), 50),
        ("--max-variants", (arguments.max_variants,), 5),
    ):
        if any(value < 1 or value > maximum for value in values):
            parser.error(f"{option} must be between 1 and {maximum}")
    if arguments.embedding_dim is not None and arguments.embedding_dim < 1:
        parser.error("--embedding-dim must be positive")
    return arguments


def _check_json_destination(destination: Path) -> None:
    """Check write access without truncating a previous run's report."""
    with destination.open("a", encoding="utf-8"):
        pass


async def main(argv: list[str] | None = None) -> None:
    arguments = parse(argv)
    if arguments.json is not None:
        try:
            await asyncio.to_thread(_check_json_destination, Path(arguments.json))
        except OSError as error:
            raise SystemExit(f"--json {arguments.json!r}: {error.strerror or error}") from None
    try:
        report, exported = await measure(arguments)
    finally:
        await close_db()
    print(report)
    if arguments.json is not None:
        Path(arguments.json).write_text(
            json.dumps(exported, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
