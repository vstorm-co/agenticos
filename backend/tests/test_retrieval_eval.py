"""The retrieval evaluation's question set and arithmetic (#2482).

The harness in `evals/retrieval/` is not application code and carries no
coverage gate, but the numbers it prints decide a knowledge agent's defaults -
so what turns retrieved chunks into hit@k, MRR and an answer verdict, and what
the question set may contain, is held here with a fake retriever and no model.

Imported by path, the way `test_loadtest_harness.py` reaches `loadtest/`.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic_ai.exceptions import UserError

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

        with pytest.raises(ValueError, match=r"a: directory\.md in pl"):
            dataset.load_dataset(path, docs_root=tmp_path / "docs")

    def test_a_page_missing_from_every_searched_locale_is_refused(self, tmp_path: Path):
        """Indexed in German only, an English-only page could never be found."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "directory.md").write_text("No SAML.", encoding="utf-8")
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, question: q, expected_pages: [directory.md]}\n",
        )

        dataset.load_dataset(path, docs_root=tmp_path / "docs", locales=("en", "de"))
        with pytest.raises(ValueError, match=r"a: directory\.md in de"):
            dataset.load_dataset(path, docs_root=tmp_path / "docs", locales=("de",))

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
            ({"expected_pages": ["directory.md", "directory.md"]}, "listed twice"),
            ({"expected_facts": [[" "]]}, "fact group is empty"),
            ({"expected_facts": [["*"]]}, "wildcard has an empty stem"),
            ({"expected_facts": [["**"]]}, "wildcard has an empty stem"),
            ({"expected_facts": [["  *"]]}, "wildcard has an empty stem"),
        ],
    )
    def test_an_inconsistent_item_is_refused(self, overrides: dict[str, object], message: str):
        with pytest.raises(ValueError, match=message):
            _item(**overrides)

    def test_a_refused_item_is_one_message_naming_it(self, tmp_path: Path):
        """Not pydantic's report, and not its second error about an `items` left empty."""
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, question: q,"
            " expected_pages: [directory.md, directory.md]}\n",
        )

        with pytest.raises(dataset.DatasetError) as refused:
            dataset.load_dataset(path)

        assert str(refused.value) == (
            f"{path} is not a valid question set:\n  item a: an expected page is listed twice"
        )

    def test_a_field_error_names_the_item_and_the_field(self, tmp_path: Path):
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, expected_pages: [x.md]}\n"
            "  - {category: factual, language: en, question: q, expected_pages: [x.md]}\n",
        )

        with pytest.raises(dataset.DatasetError) as refused:
            dataset.load_dataset(path)

        assert str(refused.value).splitlines()[1:] == [
            "  item a, question: Field required",
            "  item #2, id: Field required",
        ]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            (None, "cannot be read"),
            (b"version: 1\nitems: \xff\xfe\n", "is not UTF-8 text"),
            ("items: [", "is not YAML"),
            ("- a\n- b\n", "is not a valid question set:\n  Input should be a valid dictionary"),
        ],
    )
    def test_a_file_that_is_no_question_set_is_refused_by_name(
        self, tmp_path: Path, text: str | bytes | None, message: str
    ):
        path = tmp_path / "questions.yaml"
        if isinstance(text, bytes):
            path.write_bytes(text)
        elif text is not None:
            _write(tmp_path, text)

        with pytest.raises(dataset.DatasetError, match=message) as refused:
            dataset.load_dataset(path)

        assert str(refused.value).startswith(str(path))

    def test_a_missing_page_is_a_dataset_error(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, question: q, expected_pages: [x.md]}\n",
        )

        with pytest.raises(dataset.DatasetError, match=r"a: x\.md in en") as refused:
            dataset.load_dataset(path, docs_root=tmp_path / "docs")

        assert str(refused.value).startswith(f"{path}: expected pages missing under docs/")


class TestTheCommittedSetCannotBeGamed:
    """What #2482 is about must score as a failure on every committed question."""

    @pytest.fixture(scope="class")
    def committed(self):
        return dataset.load_dataset(HARNESS / "docs_questions.yaml", docs_root=REPO_ROOT / "docs")

    def test_the_saved_redis_answer_accepts_a_managed_instance(self, committed) -> None:
        item = next(item for item in committed.items if item.id == "redis-cluster-pl-corpus")
        source = json.loads((HARNESS / "results/2026-11-10-openrouter-gpt6-luna.json").read_text())
        configuration = next(
            c
            for c in source["configurations"]
            if c["top_k"] == 10 and c["query_analysis_mode"] == "hyde"
        )
        measured = next(i for i in configuration["items"] if i["id"] == item.id)

        result = scoring.ItemResult(item=item, retrieved=(), answer=measured["answer"])

        assert result.answer_correct is True

    @pytest.mark.parametrize(
        ("item_id", "answer"),
        [
            ("scim-provisioning", "No SCIM. Mappings are refreshed when a user next signs in."),
            ("scim-provisioning", "No SCIM. Mappings are refreshed when signing in."),
            (
                "deployment-wide-embedding-key",
                "No. Embedding credentials are configured per collection.",
            ),
            ("deployment-wide-embedding-key", "No. Use per-collection embedding credentials."),
            (
                "deployment-wide-embedding-key",
                "No. Each personal or organization collection needs its provider's key.",
            ),
            ("per-document-access-in-collection", "No. Permissions apply at the collection level."),
            ("per-document-access-in-collection", "No. Access is collection-level."),
            (
                "per-document-access-in-collection",
                "No. Access applies to the collection as a whole.",
            ),
            (
                "publish-reaches-production-pl",
                "Nie. Nową wersję trzeba osobno promować na produkcję.",
            ),
            ("publish-reaches-production-pl", "Nie. Potrzebna jest osobna promocja wersji."),
            (
                "publish-reaches-production-pl",
                "Nie zawsze. Zależy to od tego, czy środowisko śledzi najnowszą wersję.",
            ),
            ("stdio-mcp-server-pl-corpus", "No. Expose the server over Streamable HTTP instead."),
            ("stdio-mcp-server-pl-corpus", "No. Expose an SSE endpoint instead."),
            ("stdio-mcp-server-pl-corpus", "No. Use server-sent events instead."),
            ("approval-expiry-pl-corpus", "The default approval timeout is three days."),
            ("approval-expiry-pl-corpus", "A pending approval waits 3 days by default."),
            ("approval-expiry-pl-corpus", "Approvals have a three-day timeout."),
            ("approval-expiry-pl-corpus", "Domyślny limit zatwierdzenia to trzy dni."),
        ],
    )
    def test_documented_alternatives_accept_normal_wording(
        self, committed, item_id: str, answer: str
    ) -> None:
        item = next(item for item in committed.items if item.id == item_id)

        assert scoring.ItemResult(item=item, retrieved=(), answer=answer).answer_correct is True

    @pytest.mark.parametrize(
        "item_id",
        [
            "scim-provisioning",
            "deployment-wide-embedding-key",
            "per-document-access-in-collection",
            "publish-reaches-production-pl",
            "stdio-mcp-server-pl-corpus",
        ],
    )
    def test_a_plain_no_still_needs_the_documented_alternative(
        self, committed, item_id: str
    ) -> None:
        item = next(item for item in committed.items if item.id == item_id)
        answer = "Nie." if item.language == "pl" else "No."

        assert scoring.ItemResult(item=item, retrieved=(), answer=answer).answer_correct is False

    @pytest.mark.parametrize("answer", ["Three minutes.", "3 seconds.", "Three weeks."])
    def test_the_timeout_alternative_needs_the_correct_unit(self, committed, answer: str) -> None:
        item = next(item for item in committed.items if item.id == "approval-expiry-pl-corpus")

        assert scoring.ItemResult(item=item, retrieved=(), answer=answer).answer_correct is False

    @pytest.mark.parametrize(
        ("item_id", "page"),
        [
            ("approval-expiry-pl-corpus", "governance.md"),
            ("unanswered-question-expiry", "reference/capabilities.md"),
            ("context-always-loaded", "howto/customize-agent-prompt.md"),
            ("default-pdf-parser-pl", "file-processing.md"),
            ("environment-without-version-pl", "concepts.md"),
            ("publish-reaches-production-pl", "howto/competitor-monitoring.md"),
        ],
    )
    def test_a_documented_answer_page_is_a_retrieval_hit(
        self, committed, item_id: str, page: str
    ) -> None:
        item = next(item for item in committed.items if item.id == item_id)
        result = scoring.ItemResult(item=item, retrieved=(_chunk(page),))

        assert result.hit and result.first_hit_rank == 1 and result.reciprocal_rank == 1.0

    @pytest.mark.parametrize(
        ("item_id", "answer"),
        [
            (
                "environment-without-version-pl",
                "Tak. Produkcja domyślnie podąża za publikacjami, dopóki ktoś nie przypnie "
                "jej do konkretnej opublikowanej wersji.",
            ),
            (
                "deployment-wide-embedding-key",
                "Yes. A server key is supported; it is not configured per collection.",
            ),
            (
                "stdio-mcp-server-pl-corpus",
                "Yes. Connect a stdio process; it is not a Streamable HTTP server.",
            ),
            (
                "saml-single-sign-on-pl",
                "Tak. SAML działa bezpośrednio, nie potrzebujesz Keycloak.",
            ),
        ],
    )
    def test_an_affirmative_answer_to_a_negative_case_does_not_pass_on_incidental_negation(
        self, committed, item_id: str, answer: str
    ) -> None:
        item = next(item for item in committed.items if item.id == item_id)

        assert scoring.ItemResult(item=item, retrieved=(), answer=answer).answer_correct is False

    def test_each_answer_still_has_its_evidence_on_an_expected_page(self) -> None:
        """A feature becoming supported must invalidate a stale negative-answer oracle."""
        committed = dataset.load_dataset(
            HARNESS / "docs_questions.yaml", docs_root=REPO_ROOT / "docs"
        )
        for item in committed.items:
            page, quote = item.evidence.split(": ", 1)
            assert page in item.expected_pages, item.id
            text = (REPO_ROOT / "docs" / page).read_text(encoding="utf-8")
            assert " ".join(quote.split()) in " ".join(text.split()), item.id

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
            (
                "deployment-wide-embedding-key",
                "The documentation does not state whether one key can be configured "
                "for the whole server instead of per collection",
            ),
            (
                "deployment-wide-embedding-key",
                "The docs don\u2019t specify whether credentials are per collection.",
            ),
            (
                "per-document-access-in-collection",
                "I do not know whether permissions apply at the collection level.",
            ),
            (
                "publish-reaches-production-pl",
                "Dokumentacja nie podaje, czy trzeba promować nową wersję na produkcję.",
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
    @pytest.mark.parametrize(
        "echo",
        [
            "Can one key replace per collection credentials?",
            "CAN ONE KEY REPLACE PER COLLECTION CREDENTIALS?",
            "Can one key replace per collection credentials",
            "Can  one key replace per-collection credentials.",
        ],
    )
    def test_echoed_question_text_cannot_supply_an_answer_fact(self, echo: str) -> None:
        question = "Can one key replace per collection credentials?"
        item = _item(question=question, expected_facts=[["no", "not"], ["per collection"]])
        result = scoring.ItemResult(
            item=item, retrieved=(), answer=f"No. The documentation does not state it. {echo}"
        )

        assert result.answer_correct is False
        assert result.missing_facts == (("per collection",),)

    def test_an_abstention_does_not_supply_the_negative_fact(self) -> None:
        item = _item(expected_facts=[["no", "not"], ["HTTP"]])
        result = scoring.ItemResult(
            item=item,
            retrieved=(),
            answer="The documentation does not state whether stdio works. It describes HTTP.",
        )

        assert result.answer_correct is False
        assert result.missing_facts == (("no", "not"),)

    def test_a_separate_clear_answer_still_counts_after_an_uncertain_sentence(self) -> None:
        item = _item(expected_facts=[["no", "not"], ["per collection"]])
        result = scoring.ItemResult(
            item=item,
            retrieved=(),
            answer="The documentation does not state the provider's price. "
            "No server-wide key is supported. Configure credentials per collection.",
        )

        assert result.answer_correct is True

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
        assert result.missing_facts == (("no", "not"), ("Keycloak*",))

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

    def test_the_report_names_what_was_missed(self) -> None:
        results = [
            scoring.ItemResult(
                item=_item(),
                retrieved=(_chunk("about/dify.md"),),
                answer="The documentation does not state it.",
            )
        ]
        report = scoring.render_markdown("top_k=5, query_analysis_mode=off", results)
        exported = scoring.as_json("label", 5, "off", results)

        assert "| negative | 1 | 0% | 0% | 0.00 | 0/1 |" in report
        assert "`saml` wanted directory.md; got about/dify.md" in report
        assert "`saml` lacks no / not; Keycloak*" in report
        assert exported["items"][0]["retrieved_pages"] == ["about/dify.md"]
        assert exported["items"][0]["answer_correct"] is False
        assert exported["items"][0]["queries"] is None

    def test_the_export_carries_each_item_s_planned_queries(self) -> None:
        results = [scoring.ItemResult(item=_item(), retrieved=(_chunk("directory.md"),))]
        exported = scoring.as_json(
            "label", 5, "hyde", results, queries={"saml": ["A passage about SAML."]}
        )

        assert exported["items"][0]["queries"] == ["A passage about SAML."]

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

    async def test_the_first_failed_page_stops_further_indexing(self, tmp_path: Path) -> None:
        store = _Store()
        ingestion = _Ingestion(store, fail="a.md")

        with pytest.raises(SystemExit, match=r"a\.md: parser refused"):
            await run.ingest(
                store, ingestion, "c", _pages(tmp_path), docs_root=tmp_path, reingest=True
            )

        assert ingestion.source_paths == ["a.md"]
        assert store.held == {} and store.dropped == 2

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
        with pytest.raises(
            SystemExit, match="--collection-prefix: A collection name may be at most"
        ):
            self._names(self._settings(), prefix="x" * 40)

    @pytest.mark.parametrize("prefix", ["my-eval", "My_eval", "1_eval", "", "my eval"])
    def test_a_prefix_outside_the_stores_identifier_contract_is_refused(self, prefix: str) -> None:
        with pytest.raises(SystemExit, match="--collection-prefix: A collection name must start"):
            self._names(self._settings(), prefix=prefix)

    def test_a_custom_prefix_keeps_its_valid_identifier(self) -> None:
        names = self._names(self._settings(), prefix="my_eval2")

        assert all(name.startswith("my_eval2_") for name in names.values())


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


class TestRefusals:
    """A refused input ends the run before indexing, with a message and no traceback."""

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["--embedding-model", "my-model"], "--embedding-dim is required"),
            (["--embedding-dim", "3072"], "--embedding-dim is only accepted"),
            (["--embedding-dim", "1536"], "--embedding-dim is only accepted"),
            (["--collection-prefix", "my-eval"], "--collection-prefix:"),
        ],
    )
    async def test_invalid_model_or_collection_settings_stop_before_provider_setup(
        self, arguments: list[str], message: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_provider(*_: object, **__: object) -> None:
            pytest.fail("invalid settings must be refused before provider setup or database access")

        monkeypatch.setattr(run, "EmbeddingService", no_provider)

        with pytest.raises(SystemExit, match=message):
            await run.measure(run.parse([*arguments, "--keyless"]))

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["--top-k", "0"], "--top-k must be between 1 and 50"),
            (["--top-k", "51"], "--top-k must be between 1 and 50"),
            (["--top-k", "5", "--top-k", "-1"], "--top-k must be between 1 and 50"),
            (["--max-variants", "0"], "--max-variants must be between 1 and 5"),
            (["--max-variants", "6"], "--max-variants must be between 1 and 5"),
            (["--embedding-dim", "0"], "--embedding-dim must be positive"),
        ],
    )
    def test_invalid_counts_are_refused_before_any_indexing(
        self, arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as stopped:
            run.parse(arguments)

        assert stopped.value.code == 2
        assert message in capsys.readouterr().err

    def _bad_set(self, tmp_path: Path) -> Path:
        return _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, question: q,"
            " expected_pages: [directory.md, directory.md]}\n",
        )

    async def test_a_refused_question_set_stops_the_run_with_its_message(self, tmp_path: Path):
        path = self._bad_set(tmp_path)

        with pytest.raises(SystemExit) as stopped:
            await run.measure(run.parse(["--dataset", str(path)]))

        assert stopped.value.code == (
            f"{path} is not a valid question set:\n  item a: an expected page is listed twice"
        )

    def test_the_command_prints_the_refusal_without_a_traceback(self, tmp_path: Path):
        path = self._bad_set(tmp_path)

        finished = subprocess.run(
            [sys.executable, str(HARNESS / "run.py"), "--dataset", str(path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT / "backend",
            timeout=120,
        )

        assert finished.returncode == 1
        assert "Traceback" not in finished.stderr
        assert "item a: an expected page is listed twice" in finished.stderr


class TestModelPreparation:
    @pytest.fixture
    def isolated_measure(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        events: list[str] = []
        active = False

        @asynccontextmanager
        async def locks(_collections: list[str]) -> AsyncGenerator[None]:
            nonlocal active
            active = True
            events.append("locked")
            try:
                yield
            finally:
                active = False
                events.append("unlocked")

        async def ownership(_collections: list[str]) -> None:
            assert active

        async def ingest(*_args: object, **_kwargs: object) -> None:
            assert active
            events.append("index")

        async def evaluate(*_args: object) -> list[object]:
            assert active
            events.append("measure")
            raise RuntimeError("measurement reached")

        monkeypatch.setattr(run, "collection_locks", locks)
        monkeypatch.setattr(run, "refuse_held_names", ownership)
        monkeypatch.setattr(run, "ingest", ingest)
        monkeypatch.setattr(run, "evaluate", evaluate)
        monkeypatch.setattr(run, "EmbeddingService", lambda *_args, **_kwargs: object())
        monkeypatch.setattr(run, "process_vector_store", lambda *_args: _Store())
        monkeypatch.setattr(run, "RetrievalService", lambda **_kwargs: object())
        monkeypatch.setattr(run, "IngestionService", lambda **_kwargs: object())
        monkeypatch.setattr(run, "DocumentProcessor", lambda *_args: object())
        return events

    @pytest.mark.parametrize(
        ("flags", "agents"),
        [
            ([], 0),
            (["--mode", "off"], 0),
            (["--answers"], 1),
            (["--mode", "hyde"], 1),
            (["--mode", "hyde", "--answers"], 2),
        ],
    )
    async def test_only_needed_agents_are_prepared_before_indexing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_measure: list[str],
        flags: list[str],
        agents: int,
    ) -> None:
        def agent(*_args: object, **_kwargs: object) -> object:
            isolated_measure.append("agent")
            return object()

        monkeypatch.setattr(run, "Agent", agent)

        with pytest.raises(RuntimeError, match="measurement reached"):
            await run.measure(run.parse(["--keyless", "--llm-model", "unused:invalid", *flags]))

        assert isolated_measure.count("agent") == agents
        assert isolated_measure[:agents] == ["agent"] * agents
        assert "index" in isolated_measure and "measure" in isolated_measure
        assert isolated_measure[agents] == "locked" and isolated_measure[-1] == "unlocked"

    @pytest.mark.parametrize("flags", [["--mode", "hyde"], ["--answers"]])
    async def test_an_invalid_required_model_stops_before_embedding_setup(
        self, monkeypatch: pytest.MonkeyPatch, flags: list[str]
    ) -> None:
        def no_embeddings(*_args: object, **_kwargs: object) -> None:
            pytest.fail("an invalid required LLM must stop before any embedding setup")

        monkeypatch.setattr(run, "EmbeddingService", no_embeddings)

        with pytest.raises(UserError):
            await run.measure(run.parse(["--keyless", "--llm-model", "invalid:model", *flags]))


class TestIngestionFlags:
    def test_the_chunk_flags_reach_the_pipeline_and_its_collections(self):
        default = run.rag_settings(run.parse([]))
        changed = run.rag_settings(
            run.parse(
                [
                    "--chunk-size",
                    "1200",
                    "--chunk-overlap",
                    "100",
                    "--chunking-strategy",
                    "markdown",
                ]
            )
        )

        assert (default.chunk_size, default.chunk_overlap, default.chunking_strategy) == (
            2500,
            200,
            "recursive",
        )
        assert (changed.chunk_size, changed.chunk_overlap, changed.chunking_strategy) == (
            1200,
            100,
            "markdown",
        )
        assert changed.embeddings_config.model == "text-embedding-3-small"
        assert run.collection_digest(default, "u") != run.collection_digest(changed, "u")

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            (
                ["--chunk-overlap", "3000"],
                "--chunk-overlap (3000) must be smaller than --chunk-size (2500)",
            ),
            (["--chunk-size", "10"], "--chunk-size: Input should be greater than or equal to 64"),
        ],
    )
    def test_a_chunk_setting_a_collection_would_refuse_is_refused(
        self, argv: list[str], message: str
    ):
        with pytest.raises(SystemExit) as stopped:
            run.rag_settings(run.parse(argv))

        assert message in str(stopped.value.code)

    def test_an_unknown_dimension_is_taken_from_the_flag(self):
        settings = run.rag_settings(
            run.parse(["--embedding-model", "my-model", "--embedding-dim", "384"])
        )

        assert settings.embeddings_config.dim == 384


class TestCorpusFingerprints:
    def test_the_fingerprint_is_independent_of_checkout_and_file_order(
        self, tmp_path: Path
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        pages = _pages(first)
        copy = list(reversed(_pages(second)))

        assert run.corpus_fingerprint(pages, docs_root=first) == run.corpus_fingerprint(
            copy, docs_root=second
        )

    @pytest.mark.parametrize("change", ["edit", "add", "remove", "rename"])
    def test_the_fingerprint_identifies_a_changed_corpus(self, tmp_path: Path, change: str) -> None:
        pages = _pages(tmp_path)
        before = run.corpus_fingerprint(pages, docs_root=tmp_path)
        if change == "edit":
            pages[0].write_text("new contents", encoding="utf-8")
        elif change == "add":
            added = tmp_path / "new.md"
            added.write_text("new page", encoding="utf-8")
            pages.append(added)
        elif change == "remove":
            pages.pop().unlink()
        else:
            pages[0] = pages[0].rename(tmp_path / "renamed.md")

        after = run.corpus_fingerprint(pages, docs_root=tmp_path)

        assert after["sha256"] != before["sha256"]
        assert after["pages"] == len(pages)


class TestJsonDestination:
    @pytest.mark.parametrize("kind", ["missing_parent", "directory", "empty", "file_parent"])
    async def test_an_invalid_destination_stops_before_evaluation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
    ) -> None:
        parent_file = tmp_path / "parent"
        parent_file.write_text("keep", encoding="utf-8")
        destination = {
            "missing_parent": str(tmp_path / "missing" / "report.json"),
            "directory": str(tmp_path),
            "empty": "",
            "file_parent": str(parent_file / "report.json"),
        }[kind]

        async def no_evaluation(_arguments: object) -> tuple[str, dict[str, object]]:
            pytest.fail("an unusable JSON destination must stop before any billed evaluation")

        monkeypatch.setattr(run, "measure", no_evaluation)

        with pytest.raises(SystemExit, match="--json"):
            await run.main(["--json", destination])

        assert parent_file.read_text(encoding="utf-8") == "keep"

    async def test_a_failed_evaluation_preserves_the_previous_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        destination = tmp_path / "report.json"
        previous = '{"previous": true}\n'
        destination.write_text(previous, encoding="utf-8")

        async def failed(_arguments: object) -> tuple[str, dict[str, object]]:
            raise RuntimeError("index failed")

        async def close() -> None:
            pass

        monkeypatch.setattr(run, "measure", failed)
        monkeypatch.setattr(run, "close_db", close)

        with pytest.raises(RuntimeError, match="index failed"):
            await run.main(["--json", str(destination)])

        assert destination.read_text(encoding="utf-8") == previous

    async def test_a_successful_evaluation_replaces_the_previous_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        destination = tmp_path / "report.json"
        destination.write_text(json.dumps({"old": "x" * 1000}), encoding="utf-8")
        exported: dict[str, object] = {"answer": "Nie, przez Keycloaka."}

        async def measured(_arguments: object) -> tuple[str, dict[str, object]]:
            return "report", exported

        async def close() -> None:
            pass

        monkeypatch.setattr(run, "measure", measured)
        monkeypatch.setattr(run, "close_db", close)

        await run.main(["--json", str(destination)])

        assert json.loads(destination.read_text(encoding="utf-8")) == exported
        assert capsys.readouterr().out == "report\n"


class TestProvenance:
    def test_the_export_records_what_shaped_the_run(self, tmp_path: Path):
        path = _write(
            tmp_path,
            "version: 1\nitems:\n"
            "  - {id: a, category: factual, language: en, question: q, expected_pages: [x.md]}\n",
        )
        arguments = run.parse(["--dataset", str(path), "--chunk-size", "1200"])
        settings = run.rag_settings(arguments)
        started = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        docs = tmp_path / "docs"
        docs.mkdir()
        page = docs / "x.md"
        page.write_text("captured corpus", encoding="utf-8")
        corpus = {"en": run.corpus_fingerprint([page], docs_root=docs)}

        loaded = dataset.load_dataset(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.unlink()
        page.write_text("edited after capture", encoding="utf-8")

        exported = run.provenance(
            arguments,
            dataset=loaded,
            settings=settings,
            locales=("en",),
            collections={"en": "c_en"},
            corpus=corpus,
            started_at=started,
            reports=[],
        )

        assert exported["dataset_sha256"] == digest, "the bytes that were loaded, read once"
        assert exported["started_at"] == "2026-11-05T12:00:00+00:00"
        assert exported["embedding_dim"] == 1536
        assert exported["ingestion"] == {
            "chunk_size": 1200,
            "chunk_overlap": 200,
            "chunking_strategy": "recursive",
            "document_parser": "python_native",
            "pdf_parser": "pymupdf",
        }
        assert exported["collection_digest"] == run.collection_digest(
            settings, arguments.embedding_base_url
        )
        assert (exported["dataset"], exported["dataset_version"], exported["questions"]) == (
            str(path),
            1,
            1,
        )
        assert exported["collections"] == {"en": "c_en"}
        assert exported["corpus"] == corpus
        assert corpus["en"] != run.corpus_fingerprint([page], docs_root=docs)
        assert exported["corpus_fingerprint_algorithm"] == "sha256-path-content-v1"
        assert exported["configurations"] == []
