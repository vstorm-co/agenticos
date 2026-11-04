"""The retrieval evaluation's question set and arithmetic (#2482).

The harness in `evals/retrieval/` is not application code and carries no
coverage gate, but the numbers it prints decide a knowledge agent's defaults -
so what turns retrieved chunks into hit@k, MRR and an answer verdict, and what
the question set may contain, is held here with a fake retriever and no model.

Imported by path, the way `test_loadtest_harness.py` reaches `loadtest/`.
"""

import hashlib
import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.models import IngestionStatus, SearchResult

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "evals" / "retrieval"

pytestmark = pytest.mark.anyio


def _load(name: str) -> ModuleType:
    """Import one harness module, with its siblings importable by bare name."""
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dataset = _load("dataset")
scoring = _load("scoring")


def _item(**overrides: object) -> object:
    fields: dict[str, object] = {
        "id": "saml",
        "category": "negative",
        "language": "en",
        "question": "Does AgenticOS support SAML single sign-on?",
        "expected_pages": ["directory.md"],
        "expected_facts": [["no", "not"], ["Keycloak*"]],
    }
    return dataset.Item(**{**fields, **overrides})


def _chunk(page: str) -> object:
    return scoring.Retrieved(page=page, content="", score=0.5)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "questions.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestPageKeys:
    def test_a_translation_is_the_same_page_in_another_locale(self):
        assert dataset.page_key("directory.pl.md") == ("directory.md", "pl")
        assert dataset.page_key("howto/translate.es.md") == ("howto/translate.md", "es")
        assert dataset.page_key("directory.md") == ("directory.md", "en")

    def test_a_dotted_name_is_not_mistaken_for_a_locale(self):
        assert dataset.page_key("reference/spec.v2.md") == ("reference/spec.v2.md", "en")

    def test_a_key_names_its_file_in_each_locale(self):
        assert dataset.localized_path("howto/translate.md", "pl") == "howto/translate.pl.md"
        assert dataset.localized_path("directory.md", "en") == "directory.md"


class TestTheCorpus:
    def test_the_corpus_leaves_out_what_the_site_leaves_out(self):
        """Plans and design notes are never published, so no reader can be answered from them."""
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        block = mkdocs.split("exclude_docs: |\n", 1)[1].split("\n\n", 1)[0]

        assert tuple(line.strip() for line in block.splitlines()) == dataset.UNPUBLISHED

    def test_a_locale_is_its_own_published_pages(self, tmp_path: Path):
        for name in ["a.md", "a.pl.md", "howto/b.md", "howto/b.pl.md", "plans/c.md", "ROADMAP.md"]:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text("x", encoding="utf-8")

        def names(locale: str) -> list[str]:
            return [
                path.relative_to(tmp_path).as_posix()
                for path in dataset.corpus_files(tmp_path, locale)
            ]

        assert names("en") == ["a.md", "howto/b.md"]
        assert names("pl") == ["a.pl.md", "howto/b.pl.md"]


class TestTheQuestionSet:
    def test_the_committed_set_loads_and_every_expected_page_exists(self):
        """A page renamed under docs/ fails here, not as a mysterious miss in a paid run."""
        loaded = dataset.load_dataset(HARNESS / "docs_questions.yaml", docs_root=REPO_ROOT / "docs")

        categories = {item.category for item in loaded.items}
        assert categories == {"factual", "negative", "cross_language"}
        assert len(loaded.items) >= 30
        saml = next(item for item in loaded.items if item.id == "saml-single-sign-on")
        assert saml.expected_pages == ("directory.md",)

    def test_a_missing_page_is_refused_by_name(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "directory.md").write_text("No SAML.", encoding="utf-8")
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: cross_language, language: en, search_locales: [pl],"
            " question: q, expected_pages: [directory.md]}\n",
        )

        with pytest.raises(ValueError, match=r"a: directory\.pl\.md"):
            dataset.load_dataset(path, docs_root=tmp_path / "docs")

    def test_a_repeated_id_is_refused(self, tmp_path: Path):
        row = "  - {id: a, category: factual, language: en, question: q, expected_pages: [x.md]}\n"
        path = _write(tmp_path, "version: 1\nitems:\n" + row + row)

        with pytest.raises(ValueError, match="appears twice"):
            dataset.load_dataset(path)

    def test_another_version_is_refused(self, tmp_path: Path):
        """A set whose fields mean something else is never scored as this one."""
        path = _write(
            tmp_path,
            "version: 2\nitems:\n  - {id: a, category: factual, language: en, question: q, expected_pages: [x.md]}\n",
        )

        with pytest.raises(ValueError, match="version"):
            dataset.load_dataset(path)

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"category": "cross_language"}, "names the locales"),
            (
                {"category": "cross_language", "search_locales": ["en"]},
                "not searched in its own language",
            ),
            ({"search_locales": ["pl"]}, "only a cross_language item"),
            ({"expected_pages": ["directory.pl.md"]}, "not a page key"),
            ({"expected_pages": ["../secrets.md"]}, "not a page key"),
            ({"expected_pages": ["plans/56-shared-contracts.md"]}, "not published"),
            ({"expected_facts": [[]]}, "fact group is empty"),
            ({"expected_facts": [[" "]]}, "fact group is empty"),
        ],
    )
    def test_an_inconsistent_item_is_refused(self, overrides: dict[str, object], message: str):
        with pytest.raises(ValueError, match=message):
            _item(**overrides)


class TestTheCommittedSetCannotBeGamed:
    """What #2482 is about must score as a failure on every committed question."""

    @pytest.fixture(scope="class")
    def committed(self):
        return dataset.load_dataset(HARNESS / "docs_questions.yaml", docs_root=REPO_ROOT / "docs")

    @pytest.mark.parametrize(
        "fallback",
        [
            "The documentation does not state it.",
            "No, the documentation does not say. Not stated.",
            "Dokumentacja tego nie podaje. Nie wiem.",
        ],
    )
    def test_a_dont_know_answer_that_echoes_the_question_fails(self, committed, fallback: str):
        """The answerer is told to say this when nothing answers; it is never a pass."""
        passing = [
            item.id
            for item in committed.items
            if scoring.ItemResult(
                item=item, retrieved=(), answer=f"{fallback} {item.question}"
            ).answer_correct
        ]

        assert passing == []

    @pytest.mark.parametrize(
        ("item_id", "paraphrase"),
        [
            (
                "scim-provisioning",
                "The documentation does not state whether SCIM sync is supported.",
            ),
            (
                "api-client-sdk",
                "The documentation does not state whether an SDK exists for the HTTP API.",
            ),
            (
                "redis-cluster-pl-corpus",
                "The documentation does not say whether a Redis Cluster instance works.",
            ),
        ],
    )
    def test_a_dont_know_answer_in_its_own_words_fails(
        self, committed, item_id: str, paraphrase: str
    ):
        """A paraphrase uses the question's vocabulary; a fact must be what the docs add to it."""
        item = next(item for item in committed.items if item.id == item_id)

        assert (
            scoring.ItemResult(item=item, retrieved=(), answer=paraphrase).answer_correct is False
        )

    def test_no_corpus_page_quotes_a_question(self, committed):
        """A page that repeats a question word for word would outrank the page that answers it."""
        docs = REPO_ROOT / "docs"
        corpus = [
            path
            for locale in ("en", "pl", "de", "es")
            for path in dataset.corpus_files(docs, locale)
        ]
        texts = {path: " ".join(path.read_text(encoding="utf-8").split()) for path in corpus}

        quoting = [
            (item.id, path.relative_to(docs).as_posix())
            for item in committed.items
            for path, text in texts.items()
            if item.question in text
        ]

        assert quoting == []
        assert not any(path.name.startswith("retrieval-eval") for path in corpus)


class TestRetrievalScores:
    def test_a_hit_at_rank_two_scores_half(self):
        result = scoring.ItemResult(
            item=_item(), retrieved=(_chunk("about/dify.md"), _chunk("directory.md"))
        )

        assert result.hit and result.first_hit_rank == 2
        assert result.reciprocal_rank == 0.5

    def test_a_miss_scores_zero(self):
        """The issue's failure: only the Dify comparison came back."""
        result = scoring.ItemResult(item=_item(), retrieved=(_chunk("about/dify.md"),))

        assert not result.hit and result.reciprocal_rank == 0.0 and result.recall == 0.0

    def test_recall_counts_expected_pages_not_chunks(self):
        item = _item(expected_pages=["directory.md", "permissions.md"])
        result = scoring.ItemResult(
            item=item, retrieved=(_chunk("directory.md"), _chunk("directory.md"))
        )

        assert result.recall == 0.5

    def test_the_summary_is_per_category_and_overall(self):
        results = [
            scoring.ItemResult(item=_item(id="a"), retrieved=(_chunk("directory.md"),)),
            scoring.ItemResult(item=_item(id="b"), retrieved=(_chunk("other.md"),)),
            scoring.ItemResult(
                item=_item(id="c", category="factual"),
                retrieved=(_chunk("x.md"), _chunk("directory.md")),
            ),
        ]

        rows = {row.category: row for row in scoring.summarize(results)}

        assert list(rows) == ["factual", "negative", "all"]
        assert rows["negative"].hit_rate == 0.5 and rows["negative"].mrr == 0.5
        assert rows["factual"].mrr == 0.5
        assert rows["all"].questions == 3 and rows["all"].hit_rate == pytest.approx(2 / 3)
        assert rows["all"].answered == 0


class TestAnswerFacts:
    def test_a_plain_no_with_the_alternative_is_correct(self):
        result = scoring.ItemResult(
            item=_item(),
            retrieved=(),
            answer="No. A SAML-only provider can come in through Keycloak.",
        )

        assert result.answer_correct is True

    def test_not_stated_is_not_an_answer(self):
        """What the agent said in #2482: 'not stated' contains no Keycloak."""
        result = scoring.ItemResult(
            item=_item(),
            retrieved=(),
            answer="The documentation does not state that SAML is supported.",
        )

        assert result.answer_correct is False
        assert result.missing_facts == (("Keycloak*",),)

    def test_a_word_is_matched_whole_and_a_star_is_a_prefix(self):
        assert scoring.mentions("Nie, przez Keycloaka.", "Keycloak*")
        assert not scoring.mentions("Nie, przez Keycloaka.", "Keycloak")
        assert not scoring.mentions("It is nothing like that", "no")
        assert scoring.mentions("The file is SKILL.md.", "SKILL.md")
        assert scoring.mentions("Up to 100,000 records", "100,000")

    def test_a_citation_marker_is_not_a_number(self):
        """Cited as [5], a passage number must not answer "how many: five"."""
        item = _item(category="factual", expected_facts=[["five", "5"]])

        wrong = scoring.ItemResult(item=item, retrieved=(), answer="Ten at once [5], or [3, 5].")
        right = scoring.ItemResult(item=item, retrieved=(), answer="Five at once [2].")

        assert wrong.answer_correct is False
        assert right.answer_correct is True

    def test_an_item_without_facts_is_not_judged(self):
        """Without an oracle every answer would count as correct, "not stated" included."""
        result = scoring.ItemResult(
            item=_item(expected_facts=[]), retrieved=(), answer="Not stated."
        )

        assert result.answer_correct is None

    def test_nothing_answered_is_not_judged(self):
        result = scoring.ItemResult(item=_item(), retrieved=())

        assert result.answer_correct is None and result.missing_facts is None


class TestEvaluate:
    async def test_every_item_is_retrieved_and_answered_in_order(self):
        items = (_item(id="a"), _item(id="b", question="Is there SCIM?"))
        questions = dataset.Dataset(version=1, items=items)
        asked: list[str] = []

        async def retrieve(item: object) -> list[object]:
            asked.append(item.id)
            return [_chunk("directory.md")] if item.id == "a" else [_chunk("about/dify.md")]

        async def answer(item: object, retrieved: list[object]) -> str:
            return (
                "No - through Keycloak." if retrieved[0].page == "directory.md" else "Not stated."
            )

        results = await scoring.evaluate(questions, retrieve, answer)

        assert asked == ["a", "b"]
        assert [r.hit for r in results] == [True, False]
        assert [r.answer_correct for r in results] == [True, False]

    async def test_the_report_names_what_was_missed(self):
        questions = dataset.Dataset(version=1, items=(_item(),))

        async def retrieve(item: object) -> list[object]:
            return [_chunk("about/dify.md")]

        async def answer(item: object, retrieved: list[object]) -> str:
            return "The documentation does not state it."

        results = await scoring.evaluate(questions, retrieve, answer)
        report = scoring.render_markdown("top_k=5, query_analysis_mode=off", results)
        exported = scoring.as_json("label", 5, "off", results)

        assert "| negative | 1 | 0% | 0% | 0.00 | 0/1 |" in report
        assert "`saml` wanted directory.md; got about/dify.md" in report
        assert "`saml` lacks Keycloak*" in report
        assert exported["items"][0]["retrieved_pages"] == ["about/dify.md"]
        assert exported["items"][0]["answer_correct"] is False

    async def test_a_report_without_answers_has_no_answer_column(self):
        questions = dataset.Dataset(version=1, items=(_item(),))

        async def retrieve(item: object) -> list[object]:
            return [_chunk("directory.md")]

        report = scoring.render_markdown("x", await scoring.evaluate(questions, retrieve))

        assert "Answers correct" not in report and "Missed" not in report


run = _load("run")


class _Store:
    """Stands in for the vector store: the pages it holds, and how often it was dropped."""

    def __init__(self, held: dict[str, str] | None = None) -> None:
        self.held = dict(held or {})
        self.dropped = 0

    async def get_documents(self, collection: str, scope: object) -> list[object]:
        return [
            SimpleNamespace(additional_info={"source_path": path, "content_hash": digest})
            for path, digest in self.held.items()
        ]

    async def delete_collection(self, collection: str) -> None:
        self.dropped += 1
        self.held = {}


class _Ingestion:
    def __init__(
        self, store: _Store, *, fail: str | None = None, interrupt_at: int | None = None
    ) -> None:
        self.store = store
        self.fail = fail
        self.interrupt_at = interrupt_at
        self.source_paths: list[str] = []

    async def ingest_file(
        self, path: Path, collection: str, *, replace: bool, source_path: str
    ) -> SimpleNamespace:
        assert replace is False, "the replace lookup matches bare file names"
        if len(self.source_paths) == self.interrupt_at:
            raise KeyboardInterrupt
        self.source_paths.append(source_path)
        self.store.held[source_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name == self.fail:
            return SimpleNamespace(status=IngestionStatus.ERROR, error_message="parser refused")
        return SimpleNamespace(status=IngestionStatus.DONE, error_message=None)


def _pages(tmp_path: Path) -> list[Path]:
    paths = [tmp_path / "a.md", tmp_path / "howto" / "b.md"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return paths


def _indexed(paths: list[Path], root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


class TestIndexing:
    async def test_a_collection_holding_exactly_the_pages_is_reused(self, tmp_path: Path):
        pages = _pages(tmp_path)
        store = _Store(_indexed(pages, tmp_path))
        ingestion = _Ingestion(store)

        await run.ingest(store, ingestion, "c", pages, docs_root=tmp_path, reingest=False)

        assert store.dropped == 0 and ingestion.source_paths == []

    async def test_a_partial_collection_is_rebuilt_not_measured(self, tmp_path: Path):
        """What an interrupted run leaves behind holds fewer pages than the corpus."""
        pages = _pages(tmp_path)
        store = _Store(_indexed(pages[:1], tmp_path))
        ingestion = _Ingestion(store)

        await run.ingest(store, ingestion, "c", pages, docs_root=tmp_path, reingest=False)

        assert store.dropped == 1 and store.held == _indexed(pages, tmp_path)

    async def test_an_edited_page_rebuilds_the_collection(self, tmp_path: Path):
        """Same pages, same count: the stored text is still not the docs any more."""
        pages = _pages(tmp_path)
        store = _Store(_indexed(pages, tmp_path))
        pages[1].write_text("edited", encoding="utf-8")

        await run.ingest(store, _Ingestion(store), "c", pages, docs_root=tmp_path, reingest=False)

        assert store.dropped == 1 and store.held == _indexed(pages, tmp_path)

    async def test_a_renamed_page_rebuilds_the_collection(self, tmp_path: Path):
        pages = _pages(tmp_path)
        store = _Store(
            {"old-name.md": hashlib.sha256(b"x").hexdigest(), **_indexed(pages[1:], tmp_path)}
        )

        await run.ingest(store, _Ingestion(store), "c", pages, docs_root=tmp_path, reingest=False)

        assert store.dropped == 1 and "old-name.md" not in store.held

    async def test_pages_are_stored_relative_to_the_docs(self, tmp_path: Path):
        """So a collection indexed from one checkout reads the same from another."""
        store = _Store()
        ingestion = _Ingestion(store)

        await run.ingest(store, ingestion, "c", _pages(tmp_path), docs_root=tmp_path, reingest=True)

        assert ingestion.source_paths == ["a.md", "howto/b.md"]

    async def test_an_interrupted_index_is_dropped(self, tmp_path: Path):
        store = _Store()
        ingestion = _Ingestion(store, interrupt_at=1)

        with pytest.raises(KeyboardInterrupt):
            await run.ingest(
                store, ingestion, "c", _pages(tmp_path), docs_root=tmp_path, reingest=True
            )

        assert store.held == {} and store.dropped == 2

    async def test_a_page_that_fails_drops_the_collection_and_stops(self, tmp_path: Path):
        store = _Store()
        ingestion = _Ingestion(store, fail="b.md")

        with pytest.raises(SystemExit, match=r"howto/b\.md: parser refused"):
            await run.ingest(
                store, ingestion, "c", _pages(tmp_path), docs_root=tmp_path, reingest=True
            )

        assert store.held == {}

    def test_a_chunk_is_scored_by_its_page_key(self):
        result = SearchResult(
            content="No SAML.", score=0.9, metadata={"source_path": "directory.pl.md"}
        )

        assert run._retrieved(result).page == "directory.md"


class TestHeldNames:
    async def test_a_name_a_knowledge_base_holds_is_refused(self, monkeypatch: pytest.MonkeyPatch):
        """Its table is shared: `--reingest` would drop a tenant's vectors (#2560)."""

        @asynccontextmanager
        async def db_context():
            yield None

        async def holders(db: object, name: str) -> list[object]:
            return [object()] if name.endswith("_en") else []

        monkeypatch.setattr(run, "get_db_context", db_context)
        monkeypatch.setattr(run.knowledge_base_repo, "list_by_collection_name", holders)

        with pytest.raises(SystemExit, match="already uses eval_en"):
            await run.refuse_held_names(["eval_en", "eval_pl"])
        await run.refuse_held_names(["eval_pl"])


class TestCollectionNames:
    def _settings(self, model: str = "text-embedding-3-small", **changes: object) -> RAGSettings:
        return RAGSettings(embeddings_config=EmbeddingsConfig(model=model), **changes)

    def _names(self, settings: RAGSettings, prefix: str = "retrieval_eval") -> dict[str, str]:
        return run.collection_names(prefix, settings, "https://api.openai.com/v1", ("en", "pl"))

    def test_a_changed_ingestion_setting_indexes_afresh(self):
        """A chunk-size comparison must not reuse the chunks the old size produced."""
        assert self._names(self._settings()) != self._names(self._settings(chunk_size=1200))

    def test_models_that_shorten_alike_get_their_own_collections(self):
        first = self._names(self._settings("text-embedding-3-small"))
        second = self._names(self._settings("text-embedding-3-small-v2", dim=1536))

        assert first["en"] != second["en"]

    def test_the_same_pipeline_reuses_its_collections(self):
        names = self._names(self._settings())

        assert names == self._names(self._settings())
        assert names["en"].endswith("_en") and names["pl"].endswith("_pl")

    def test_a_prefix_that_overflows_the_name_is_refused(self):
        with pytest.raises(SystemExit, match="too long"):
            self._names(self._settings(), prefix="x" * 40)


class TestQueryPlans:
    async def test_a_plan_is_generated_once_and_shared_across_top_k(self):
        """Otherwise top_k 5 and 10 would compare two different rephrasings."""
        prompts: list[str] = []

        async def generate(prompt: str) -> str:
            prompts.append(prompt)
            return f"rephrasing {len(prompts)}"

        class _Retrieval:
            def __init__(self) -> None:
                self.queries: list[str] = []

            async def retrieve(self, *, query: str, limit: int, **_: object) -> list[SearchResult]:
                self.queries.append(query)
                return [
                    SearchResult(content="x", score=1.0, metadata={"source_path": "directory.md"})
                ]

        retrieval = _Retrieval()
        plans: dict[tuple[str, str], list[str]] = {}
        item = _item(category="cross_language", search_locales=["pl"], language="en")
        for top_k in (5, 10):
            search = run.retriever(
                retrieval,
                collections={"pl": "c_pl"},
                top_k=top_k,
                mode="multi_query",
                max_variants=1,
                generate=generate,
                plans=plans,
            )
            await search(item)

        assert len(prompts) == 1
        assert retrieval.queries == [item.question, "rephrasing 1"] * 2
