"""The text-similarity scorer: definitions, normalisation, quoting, limits."""

import random
import time
import tracemalloc
import unicodedata

import pytest

from app.core.exceptions import ValidationError
from app.services import text_similarity
from app.services.text_similarity import (
    MAX_TEXT_CHARS,
    Method,
    Normalization,
    Similarity,
    compare,
    levenshtein,
    normalize,
    strip_quoted,
    tokens,
)

METHODS: tuple[Method, ...] = ("char_ratio", "token_f1", "line_diff")


def _reference_distance(a: list[str], b: list[str]) -> int:
    """The textbook dynamic-programming edit distance."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("text", ["", "same text\nacross lines", "zażółć gęślą jaźń"])
def test_identical_texts_score_one_under_every_method(method: Method, text: str) -> None:
    result = compare(text, text, method=method)
    assert result.score == 1.0
    assert result.changed_ratio == 0.0


@pytest.mark.parametrize(
    ("method", "a", "b"),
    [
        ("char_ratio", "abc", "xyz"),
        ("token_f1", "red green", "blue"),
        ("token_f1", "", "blue"),
        ("line_diff", "one\ntwo", "three\nfour"),
    ],
)
def test_texts_with_nothing_in_common_score_zero(method: Method, a: str, b: str) -> None:
    result = compare(a, b, method=method)
    assert result.score == 0.0
    assert result.changed_ratio == 1.0


@pytest.mark.parametrize(
    ("method", "a", "b", "expected"),
    [
        ("char_ratio", "kitten", "sitting", round(1 - 3 / 7, 6)),
        ("char_ratio", "abc", "", 0.0),
        ("token_f1", "the cat sat", "the cat ran", round(2 * 2 / 6, 6)),
        ("token_f1", "a a b", "a b b", round(2 * 2 / 6, 6)),
        ("token_f1", "zażółć gęślą", "zażółć jaźń", round(2 * 1 / 4, 6)),
        ("token_f1", "Grüße aus Köln", "Grüße aus Bonn", round(2 * 2 / 6, 6)),
        ("line_diff", "a\nb\nc", "a\nx\nc", round(1 - 1 / 3, 6)),
        ("line_diff", "a\nb", "a", 0.5),
    ],
)
def test_fixed_pairs_score_as_defined(method: Method, a: str, b: str, expected: float) -> None:
    assert compare(a, b, method=method).score == expected


def test_units_are_counted_after_normalisation_in_the_methods_own_unit() -> None:
    how = Normalization(whitespace=True)
    assert compare("a  b\n\nc", "a b c", method="char_ratio", normalization=how) == Similarity(
        "char_ratio", round(1 - 1 / 5, 6), round(1 / 5, 6), "characters", 5, 5
    )
    tokens_result = compare("one two three", "one", method="token_f1")
    assert (tokens_result.unit, tokens_result.a_units, tokens_result.b_units) == ("tokens", 3, 1)
    lines_result = compare("a\nb", "", method="line_diff")
    assert (lines_result.unit, lines_result.a_units, lines_result.b_units) == ("lines", 2, 0)


def test_the_changed_ratio_is_one_minus_the_score() -> None:
    result = compare("kitten", "sitting")
    assert result.changed_ratio == round(1 - result.score, 6)


def test_scores_are_rounded_to_six_places() -> None:
    result = compare("abcdefg", "abcdefgh" + "x" * 5, method="char_ratio")
    assert result.score == round(result.score, 6)
    assert result.score == round(1 - 6 / 13, 6)
    assert len(repr(result.score).split(".")[1]) <= 6


def test_a_composed_and_a_decomposed_accent_are_the_same() -> None:
    composed = "café"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert compare(composed, decomposed).score == 1.0


@pytest.mark.parametrize(
    ("how", "a", "b", "same"),
    [
        (Normalization(), "Hello", "hello", False),
        (Normalization(case=True), "Hello STRASSE", "hello strasse", True),
        (Normalization(case=True), "Straße", "STRASSE", True),
        (Normalization(), "a  b", "a b", False),
        (Normalization(whitespace=True), "a \t b\r\n\r\n c ", "a b\nc", True),
        (Normalization(whitespace=True), "a\nb", "a b", False),
        (Normalization(), "¿Qué? «hola»", "Qué hola", False),
        (Normalization(punctuation=True), "¿Qué? «hola», dijo.", "Qué hola dijo", True),
        (Normalization(punctuation=True), "a+b", "a+b!", True),
        (Normalization(punctuation=True), "a+b", "ab", False),
    ],
)
def test_each_normalisation_does_only_what_it_says(
    how: Normalization, a: str, b: str, same: bool
) -> None:
    assert (compare(a, b, normalization=how).score == 1.0) is same


def test_line_endings_are_always_the_same() -> None:
    assert normalize("a\r\nb\rc", Normalization()) == "a\nb\nc"


def test_normalisation_runs_in_the_documented_order() -> None:
    how = Normalization(case=True, whitespace=True, punctuation=True, strip_quoted=True)
    assert normalize("> Quoted\nHello,  WORLD!\n-- \nSig", how) == "hello world"
    # punctuation goes before whitespace collapses: no double space is left behind
    assert normalize("a , b", Normalization(punctuation=True, whitespace=True)) == "a b"


@pytest.mark.parametrize(
    "text",
    [
        "Thanks.\n\nOn Mon, 3 Mar 2025, Ann <a@x.org> wrote:\n> the question\n> more\n",
        "Dziękuję.\n\nW dniu pon., 3 mar 2025 Ann napisał(a):\n> pytanie\n",
        "Danke.\n\nAm 03.03.2025 schrieb Ann:\n\n> Frage\n",
    ],
)
def test_quoted_lines_and_their_attribution_are_left_out(text: str) -> None:
    assert strip_quoted(text) == text.split("\n")[0]


def test_a_signature_after_the_separator_is_left_out() -> None:
    assert strip_quoted("Hi\n-- \nAnn\nCEO") == "Hi"
    assert strip_quoted("Hi\n--\nAnn") == "Hi"
    assert strip_quoted("Hi\r\n-- \r\nAnn") == "Hi"
    assert strip_quoted("Hi\n--- not a separator") == "Hi\n--- not a separator"


def test_an_outlook_original_message_block_is_left_out() -> None:
    text = "Sure.\n\n-----Original Message-----\nFrom: Ann\nSent: Monday\n\nthe question"
    assert strip_quoted(text) == "Sure."


def test_a_line_ending_in_a_colon_that_quotes_nothing_stays() -> None:
    assert strip_quoted("Please bring:\n- a pen\n- paper") == "Please bring:\n- a pen\n- paper"
    assert strip_quoted("Items:\n> quoted") == ""
    assert strip_quoted("Bring:\nhello\n> quoted") == "Bring:\nhello"


def test_a_reply_with_nothing_quoted_is_unchanged() -> None:
    assert strip_quoted("Line one\n\nLine two") == "Line one\n\nLine two"


def test_indented_quote_markers_and_trailing_blank_lines() -> None:
    assert strip_quoted("Keep\n   > indented quote\n\n\n") == "Keep"


def test_tokens_are_unicode_words() -> None:
    assert tokens("Zażółć gęślą, jaźń! don't 42_x") == [
        "Zażółć",
        "gęślą",
        "jaźń",
        "don",
        "t",
        "42_x",
    ]


@pytest.mark.parametrize("field", ["a", "b"])
def test_a_text_over_the_limit_is_refused_naming_it(field: str) -> None:
    long, short = "x" * (MAX_TEXT_CHARS + 1), "x"
    args = (long, short) if field == "a" else (short, long)
    with pytest.raises(ValidationError) as caught:
        compare(*args)
    assert caught.value.details["fields"][0]["field"] == field
    assert caught.value.details["limit"] == MAX_TEXT_CHARS


def test_a_is_checked_before_b() -> None:
    long = "x" * (MAX_TEXT_CHARS + 1)
    with pytest.raises(ValidationError) as caught:
        compare(long, long)
    assert caught.value.details["fields"][0]["field"] == "a"


def test_a_text_of_exactly_the_limit_passes() -> None:
    assert compare("x" * MAX_TEXT_CHARS, "x" * MAX_TEXT_CHARS, method="token_f1").score == 1.0


def test_the_limit_counts_before_normalisation() -> None:
    padded = " " * MAX_TEXT_CHARS + "x"
    with pytest.raises(ValidationError):
        compare(padded, "x", normalization=Normalization(whitespace=True))


def test_levenshtein_agrees_with_the_textbook_algorithm() -> None:
    rng = random.Random(3)
    for _ in range(300):
        a = [rng.choice("abc") for _ in range(rng.randint(0, 30))]
        b = [rng.choice("abc") for _ in range(rng.randint(0, 30))]
        expected = _reference_distance(a, b)
        assert levenshtein("".join(a), "".join(b)) == expected, (a, b)
        assert levenshtein(a, b) == expected


def test_levenshtein_takes_any_hashable_items() -> None:
    assert levenshtein(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert levenshtein([(1, 2), (3,)], [(3,)]) == 1
    assert levenshtein([], ["a"]) == 1
    assert levenshtein("", "") == 0


def test_levenshtein_beyond_one_machine_word() -> None:
    rng = random.Random(5)
    a = [rng.choice("abcd") for _ in range(150)]
    b = [rng.choice("abcd") for _ in range(170)]
    assert levenshtein(a, b) == _reference_distance(a, b)


def test_the_worst_case_at_the_limit_stays_fast() -> None:
    # There is no `slow` marker in this repository, so the size is kept where
    # CI is never slow (about 0.1 s here). It guards against `difflib`, which
    # needs seconds for a text of this size over a tiny vocabulary.
    rng = random.Random(1)
    a = "".join(rng.choice("ab") for _ in range(20_000))
    b = "".join(rng.choice("ab") for _ in range(20_000))
    started = time.perf_counter()
    result = compare(a, b)
    assert time.perf_counter() - started < 2
    assert 0 < result.score < 1
    words_a = "\n".join(rng.choice(["w", "x", "y", "z"]) for _ in range(20_000))
    words_b = "\n".join(rng.choice(["w", "x", "y", "z"]) for _ in range(20_000))
    started = time.perf_counter()
    compare(words_a, words_b, method="token_f1")
    compare(words_a, words_b, method="line_diff")
    assert time.perf_counter() - started < 2


def test_the_same_inputs_give_the_same_result() -> None:
    how = Normalization(case=True, whitespace=True)
    first = compare("Some  text here", "some text there", method="token_f1", normalization=how)
    assert (
        compare("Some  text here", "some text there", method="token_f1", normalization=how) == first
    )


def test_a_large_alphabet_does_not_cost_quadratic_memory() -> None:
    n = 20_000
    a = [chr(0x4E00 + i) for i in range(n)]
    tracemalloc.start()
    try:
        assert levenshtein(a, a[::-1]) == n
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # one mask per distinct item would take n * n / 8 = 50 MB
    assert peak < 200 * n


def test_masks_built_on_the_fly_and_cached_give_the_same_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(text_similarity, "_CACHE_ALL_UP_TO", 0)
    rng = random.Random(7)
    for alphabet in ("abc", "abcdefghijklmnopqrstuvwxyz0123456789" * 3):
        # 300 over "abc": every item has 64 or more places and is cached;
        # over a wide alphabet every item is rare and built when reached
        a = [rng.choice(alphabet) for _ in range(300)]
        b = [rng.choice(alphabet) for _ in range(280)]
        assert levenshtein(a, b) == _reference_distance(a, b)


def test_a_bad_method_is_refused() -> None:
    with pytest.raises(AssertionError):
        compare("a", "b", method="nope")  # type: ignore[arg-type]  # the point of the test


def test_strip_quoted_is_linear_in_colon_lines() -> None:
    text = "Bring:\n" * 50_000
    started = time.perf_counter()
    assert strip_quoted(text) == text.rstrip("\n")
    assert time.perf_counter() - started < 2
