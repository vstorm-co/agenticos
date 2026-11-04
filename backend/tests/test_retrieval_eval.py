"""The retrieval evaluation's question set and arithmetic (#2482).

The harness in `evals/retrieval/` is not application code and carries no
coverage gate, but the numbers it prints decide a knowledge agent's defaults -
so what turns retrieved chunks into hit@k, MRR and an answer verdict, and what
the question set may contain, is held here with a fake retriever and no model.

Imported by path, the way `test_loadtest_harness.py` reaches `loadtest/`.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

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
