"""`text.compare`'s handler, its settings and its registration."""

import threading

import pytest
from pydantic import ValidationError

from app.services import text_similarity
from app.services.text_similarity import Method, Normalization
from app.workflows import _registry
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.text_compare import TextCompareConfig, TextCompareInput, TextCompareOutput
from app.workflows.nodes.text_compare._handler import handle

pytestmark = pytest.mark.anyio


async def _output(config: TextCompareConfig, a: str, b: str) -> TextCompareOutput:
    result = await handle(config, TextCompareInput(a=a, b=b))
    assert isinstance(result, Completed)
    assert isinstance(result.output, TextCompareOutput)
    return result.output


@pytest.mark.parametrize(
    ("method", "a", "b", "score", "unit", "units"),
    [
        ("char_ratio", "the quick fox", "the slow fox", 1 - 5 / 13, "characters", (13, 12)),
        ("token_f1", "the quick fox", "the slow fox", 2 / 3, "tokens", (3, 3)),
        ("line_diff", "a\nb\nc", "a\nx\nc", 2 / 3, "lines", (3, 3)),
    ],
)
async def test_it_scores_two_texts_with_the_chosen_method(
    method: Method, a: str, b: str, score: float, unit: str, units: tuple[int, int]
):
    output = await _output(TextCompareConfig(method=method), a, b)

    assert output.method == method
    assert output.unit == unit
    assert output.score == pytest.approx(score, abs=1e-6)
    assert output.changed_ratio == pytest.approx(1 - score, abs=1e-6)
    assert (output.a_units, output.b_units) == units


async def test_the_comparison_runs_off_the_event_loop_thread(monkeypatch: pytest.MonkeyPatch):
    real = text_similarity.compare
    threads: list[int] = []

    def spy(a: str, b: str, **kwargs):
        threads.append(threading.get_ident())
        return real(a, b, **kwargs)

    monkeypatch.setattr(text_similarity, "compare", spy)

    await _output(TextCompareConfig(), "a", "b")

    assert threads and threads[0] != threading.get_ident()


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"ignore_case": True}, Normalization(case=True, whitespace=True)),
        ({"ignore_whitespace": False}, Normalization()),
        ({"ignore_punctuation": True}, Normalization(punctuation=True, whitespace=True)),
        ({"strip_quoted": True}, Normalization(strip_quoted=True, whitespace=True)),
    ],
)
async def test_the_settings_become_the_normalisation(
    monkeypatch: pytest.MonkeyPatch, settings: dict[str, bool], expected: Normalization
):
    real = text_similarity.compare
    seen: list[Normalization] = []

    def spy(a: str, b: str, **kwargs):
        seen.append(kwargs["normalization"])
        return real(a, b, **kwargs)

    monkeypatch.setattr(text_similarity, "compare", spy)

    await _output(TextCompareConfig(**settings), "a", "b")

    assert seen == [expected]


async def test_by_default_whitespace_is_ignored_and_nothing_else():
    config = TextCompareConfig()

    same = await _output(config, "Hello   world\n", "Hello world")
    different = await _output(config, "Hello world", "hello, world")

    assert same.score == 1.0
    assert different.score < 1.0


async def test_two_empty_texts_are_the_same():
    output = await _output(TextCompareConfig(), "", "")

    assert (output.score, output.changed_ratio, output.a_units, output.b_units) == (1.0, 0.0, 0, 0)


@pytest.mark.parametrize("field", ["a", "b"])
def test_an_input_over_the_limit_is_refused_by_its_schema(field: str):
    texts = {"a": "", "b": "", field: "x" * 100_001}

    with pytest.raises(ValidationError) as caught:
        TextCompareInput(**texts)

    assert caught.value.errors()[0]["loc"] == (field,)


def test_an_input_of_exactly_the_limit_is_accepted():
    assert len(TextCompareInput(a="x" * 100_000, b="x" * 100_000).a) == 100_000


@pytest.mark.parametrize("config", [None, TextCompareConfig()])
async def test_without_its_settings_it_says_so(config: TextCompareConfig | None):
    result = await handle(config, None)

    assert isinstance(result, Failed)
    assert result.error.code == "TEXT_COMPARE_NOT_CONFIGURED"
    assert result.error.message == "This step needs two texts"


def test_the_step_is_registered_in_the_data_group():
    _registry.load_builtins()

    definition = _registry.get("text.compare", 1)

    assert definition.category == "data"
    assert definition.effect_kind == "pure"
    assert definition.retry_guarantee == "idempotent"
    assert definition.kind == "action"
    assert definition.name == "Compare texts"
    assert [(port.id, port.kind) for port in definition.ports] == [
        ("in", "input"),
        ("out", "output"),
    ]
