"""Markdown into what WhatsApp draws, and the answer cut to its message limit (#2076)."""

import random
import re
import threading

import pytest

from app.services.channels.whatsapp_format import (
    MAX_TEXT_UNITS,
    split_message,
    to_whatsapp,
    utf16_units,
)

URL = "https://app.example.com/link/a__b_c*d*e"
FAMILY = "👨‍👩‍👧‍👦"
FLAG = "🇵🇱"


def test_bold_italic_and_strike_convert():
    assert to_whatsapp("**a** *b* ~~c~~") == "*a* _b_ ~c~"
    assert to_whatsapp("__a__") == "*a*"
    assert to_whatsapp("_kept_ and snake_case_word") == "_kept_ and snake_case_word"


def test_headings_become_bold_lines():
    assert to_whatsapp("# Title\n## **Sub**\ntext") == "*Title*\n*Sub*\ntext"


def test_star_bullets_become_dash_bullets():
    assert to_whatsapp("* one\n+ two\n- three") == "- one\n- two\n- three"


def test_links_keep_their_address():
    assert to_whatsapp("[docs](https://x.y/z)") == "docs (https://x.y/z)"
    assert to_whatsapp("[https://x.y/z](https://x.y/z)") == "https://x.y/z"


def test_tables_become_monospace_and_code_and_urls_are_left_alone():
    table = "| a | b |\n|---|---|\n| **1** | 2 |"
    assert to_whatsapp(f"before\n{table}\nafter") == f"before\n```\n{table}\n```\nafter"

    fenced = "```python\nx = **y**\n```"
    assert to_whatsapp(fenced) == "```\nx = **y**\n```"
    assert to_whatsapp("run `**x**` now") == "run `**x**` now"

    assert to_whatsapp(f"open {URL} now") == f"open {URL} now"
    assert to_whatsapp(f"[see {URL}]({URL})") == f"see {URL} ({URL})"
    assert to_whatsapp(f"**go** {URL}") == f"*go* {URL}"


def test_a_url_is_lifted_without_the_markup_or_punctuation_around_it():
    assert to_whatsapp("**https://x.y/a**") == "*https://x.y/a*"
    assert to_whatsapp("see https://x.y/a_b_. Next") == "see https://x.y/a_b_. Next"
    assert to_whatsapp("go to _https://x.y/a_, then **https://x.y/b**!") == (
        "go to _https://x.y/a_, then *https://x.y/b*!"
    )
    assert to_whatsapp("(https://x.y/a)") == "(https://x.y/a)"


def test_a_hash_alone_on_a_line_is_not_a_heading():
    assert to_whatsapp("#\nnot a heading") == "#\nnot a heading"
    assert to_whatsapp("#  spaced") == "*spaced*"


def test_literals_in_prose_are_not_mistaken_for_markup():
    assert to_whatsapp("call my__init__method") == "call my__init__method"
    assert to_whatsapp("call a__b__c") == "call a__b__c"
    assert to_whatsapp("## Using C#") == "*Using C#*"
    assert to_whatsapp("# Title ##") == "*Title*"
    assert to_whatsapp("## F# and C# #") == "*F# and C#*"


def test_a_lone_pipe_line_is_not_a_table():
    assert to_whatsapp("| just one line |") == "| just one line |"


def test_a_stray_control_character_cannot_forge_a_placeholder():
    assert to_whatsapp("a\x000\x00b") == "a0b"


def test_short_text_is_one_message():
    assert split_message("hello") == ["hello"]
    assert split_message("") == []
    assert split_message(" \n ") == []


def test_long_text_splits_on_paragraphs_then_sentences():
    paragraphs = ["word " * 40 + "end." for _ in range(4)]
    text = "\n\n".join(paragraphs)
    chunks = split_message(text, limit=450)
    assert chunks == ["\n\n".join(paragraphs[:2]), "\n\n".join(paragraphs[2:])]

    sentences = "One two three. Four five six. Seven eight nine."
    assert split_message(sentences, limit=30) == [
        "One two three. Four five six.",
        "Seven eight nine.",
    ]
    lines = "alpha beta\ngamma delta epsilon"
    assert split_message(lines, limit=20) == ["alpha beta", "gamma delta epsilon"]
    assert split_message("aaa bbb ccc", limit=8) == ["aaa bbb", "ccc"]


def test_split_counts_utf16_units_and_never_splits_a_grapheme():
    unit = FAMILY + FLAG
    assert utf16_units(unit) == 15
    # The prefix misaligns the cuts, so a splitter that cuts between code points
    # lands inside a family or a flag instead of on the same boundary by luck.
    text = "xx" + unit * 400
    assert utf16_units(text) == 6002
    chunks = split_message(text)
    assert len(chunks) == 2
    assert "".join(chunks) == text
    for chunk in chunks:
        assert utf16_units(chunk) <= MAX_TEXT_UNITS
        assert chunk.removeprefix("xx").replace(FAMILY, "").replace(FLAG, "") == ""


@pytest.mark.parametrize(
    "cluster",
    ["e\u0301", "👍🏽", "1\ufe0f\u20e3", "🏴\U000e0067\U000e0062\U000e007f", FLAG, FAMILY],
)
@pytest.mark.parametrize("offset", [0, 1, 2])
def test_marks_modifiers_keycaps_tags_and_flags_stay_whole(cluster, offset):
    text = "x" * offset + cluster * 30
    for chunk in split_message(text, limit=utf16_units(cluster) * 4 + 1):
        assert chunk.removeprefix("x" * offset).replace(cluster, "") == ""


def test_no_chunk_is_empty_or_starts_with_the_whitespace_it_was_cut_at():
    assert split_message("a" * 4096 + " ") == ["a" * 4096]
    assert split_message("aaaa bbbb\n\ncccc", limit=9) == ["aaaa bbbb", "cccc"]
    assert split_message("aaaa bbbb   cccc", limit=9) == ["aaaa bbbb", "cccc"]
    assert split_message("a" * 9 + "  ", limit=9) == ["a" * 9]


def test_a_whitespace_only_chunk_is_dropped_not_sent_as_the_answer():
    chunks = split_message(" \n" + "a" * 5000)
    assert chunks and all(chunk.strip() for chunk in chunks)
    assert "".join(chunks).count("a") == 5000


def test_a_limit_too_small_to_hold_a_character_is_refused():
    with pytest.raises(ValueError, match="limit"):
        split_message("😀😀", limit=1)


def test_a_word_longer_than_the_limit_is_cut_hard():
    chunks = split_message("x" * 25, limit=10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]


def test_a_character_longer_than_the_limit_is_still_cut():
    text = "e" + "\u0301" * 30
    chunks = split_message(text, limit=10)
    assert "".join(chunks) == text
    assert all(utf16_units(chunk) <= 10 for chunk in chunks)


def test_a_split_inside_a_code_block_keeps_both_halves_fenced():
    code = "\n".join(f"line_{n} = {n}" for n in range(60))
    text = f"Intro\n\n```\n{code}\n```\n\nOutro"
    chunks = split_message(text, limit=200)
    assert len(chunks) > 2
    for chunk in chunks:
        assert utf16_units(chunk) <= 200
        assert chunk.count("```") % 2 == 0
    assert chunks[0].startswith("Intro") and chunks[-1].endswith("Outro")
    assert chunks[1].startswith("```\n")
    assert "".join(chunks).replace("```", "").replace("\n", "").replace(" ", "") == (
        text.replace("```", "").replace("\n", "").replace(" ", "")
    )


def test_a_split_keeps_the_next_lines_indentation():
    assert split_message("line one\n    indented two", limit=16) == [
        "line one",
        "    indented two",
    ]


def test_whitespace_only_text_gives_no_chunks():
    assert split_message("") == []
    assert split_message("  ") == []
    assert split_message(" \n\t ", limit=3) == []


def test_a_heading_ending_in_a_hash_keeps_it():
    assert to_whatsapp("## Using C#") == "*Using C#*"
    assert to_whatsapp("## Title ##") == "*Title*"


def _split_within(text: str, limit: int, seconds: float = 5.0) -> list[str]:
    """`split_message` on a thread, so a splitter that never returns fails the test."""
    outcome: list[list[str]] = []
    worker = threading.Thread(
        target=lambda: outcome.append(split_message(text, limit)), daemon=True
    )
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"split_message did not return for limit={limit}"
    return outcome[0]


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        ("```\n" + "😀" * 20 + "\n```", 9),
        ("```\n" + "e" + "́" * 30 + "\n```", 9),
        ("```\nabcdefghij klmnop\n```", 8),
        ("```\nabcdefghij klmnop\n```", 2),
    ],
)
def test_a_fence_in_a_tiny_limit_still_terminates_and_fits(text, limit):
    chunks = _split_within(text, limit)

    assert chunks
    assert all(chunk.strip() and utf16_units(chunk) <= limit for chunk in chunks)


def test_at_the_smallest_fenced_limit_the_chunks_still_terminate_and_fit():
    chunks = _split_within("```\n" + "😀" * 20 + "\n```", 10)

    assert chunks
    assert all(chunk.strip() and utf16_units(chunk) <= 10 for chunk in chunks)


def test_a_cut_right_after_an_opening_fence_leaves_no_empty_fenced_pair():
    chunks = split_message("```\nabcdefghijklmnop qrstuvwxyz\n```", limit=16 + 8)

    assert all(utf16_units(chunk) <= 24 for chunk in chunks)
    for chunk in chunks:
        assert "```\n```" not in chunk
        assert chunk.strip() not in {"```", ""}
    assert _words("".join(chunks)) == _words("```\nabcdefghijklmnop qrstuvwxyz\n```")


def test_a_cut_right_before_a_closing_fence_leaves_no_empty_fenced_pair():
    chunks = split_message("```\nabcdefghijklmn\n```\nafter the code", limit=22)

    for chunk in chunks:
        assert "```\n```" not in chunk
        assert chunk.count("```") % 2 == 0
    assert chunks[-1].endswith("after the code")


def test_a_literal_triple_backtick_in_prose_does_not_fence_the_chunks_after_it():
    text = "type ``` on its own line. " * 3 + "plain prose here. " * 20
    chunks = split_message(text, limit=120)

    assert len(chunks) > 3
    assert not any(chunk.endswith("\n```") for chunk in chunks)


def test_a_cut_through_trailing_blanks_keeps_the_next_lines_indentation():
    assert split_message("    aaaa      \n    bbbb\n    cccc", limit=8) == [
        "    aaaa",
        "    bbbb",
        "    cccc",
    ]


def _words(text: str) -> str:
    """The text with every backtick and all whitespace removed: what a reader keeps."""
    return re.sub(r"[`\s]", "", text)


def test_a_fence_opened_after_a_list_marker_does_not_wrap_the_later_chunks():
    text = "Steps:\n\n1. ```bash\n   pip install agenticos\n   ```\n2. Run it.\n\n" + "\n\n".join(
        f"Paragraph {n}. " + "word " * 120 for n in range(40)
    )

    chunks = split_message(text)

    assert len(chunks) > 3
    assert not any(chunk.startswith("```") or chunk.endswith("```") for chunk in chunks[1:])
    assert _words("".join(chunks)) == _words(text)


def test_a_one_line_fenced_command_that_ends_a_chunk_is_kept():
    text = "lorem " * 600 + "\n\n```pip install agenticos```\n\n" + "tail " * 400

    chunks = split_message(text)

    assert len(chunks) == 2
    assert chunks[0].endswith("```pip install agenticos```")
    assert "```" not in chunks[1]
    assert _words("".join(chunks)) == _words(text)


def test_text_after_a_closing_fence_on_its_line_is_kept():
    chunks = split_message("```\nabcdefghijklmn\n``` trailing words\nafter the code", limit=22)

    assert "trailing" in "".join(chunks)
    assert _words("".join(chunks)) == _words(
        "```\nabcdefghijklmn\n``` trailing words\nafter the code"
    )
    assert all(utf16_units(chunk) <= 22 for chunk in chunks)


_PIECES = (
    "Plain prose that goes on for a little while. " * 6,
    "```\n" + "\n".join(f"line_{n} = {n}" for n in range(30)) + "\n```",
    "```bash\npip install agenticos\npip install other\n```",
    "1. ```bash\n   pip install agenticos\n   ```\n2. Run it.",
    "```pip install agenticos```",
    "```\nshort\n``` and words after the closing fence",
    "- item one\n- item two\n    indented under it",
    "  indented line\n    deeper line",
    "a literal ``` in prose",
    "😀 emoji 👨‍👩‍👧‍👦 and 🇵🇱 flags " * 5,
)


@pytest.mark.parametrize("limit", [4096, 400, 120, 60, 30])
@pytest.mark.parametrize("seed", range(40))
def test_splitting_never_loses_text_keeps_fences_balanced_and_every_chunk_fits(seed, limit):
    rng = random.Random(seed)
    pieces = [rng.choice(_PIECES) for _ in range(rng.randint(2 + limit // 200, 5 + limit // 100))]
    literal = any("a literal ```" in piece for piece in pieces)
    text = to_whatsapp("\n\n".join(pieces))

    chunks = _split_within(text, limit)

    assert all(chunk.strip() and utf16_units(chunk) <= limit for chunk in chunks)
    assert _words("".join(chunks)) == _words(text)
    cut_in_half = limit < 60 and any(piece == "```pip install agenticos```" for piece in pieces)
    if not literal and not cut_in_half:
        # Every chunk that opens a fence closes it, and none is an empty pair.
        assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
        assert not any("```\n```" in chunk for chunk in chunks)
    assert (len(chunks) > 1) == (utf16_units(text) > limit)


def test_a_cut_right_after_an_opener_moves_the_opener_to_the_next_chunk():
    chunks = split_message("Intro words here\n```\nabcdefghijklmnop qrstuvwxyz\n```", limit=16)

    assert all("```\n```" not in chunk for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert all(utf16_units(chunk) <= 16 for chunk in chunks)
    assert any(chunk.startswith("```\n") for chunk in chunks)


def test_a_chunk_starting_at_a_closer_and_cut_inside_the_next_fence_is_closed():
    text = "```\nx = 1\nx = 1\nx = 1\n```\nok\n```\n" + "y = 2\n" * 6 + "```"

    chunks = split_message(text, 30)

    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert _words("".join(chunks)) == _words(text)


def test_a_one_line_fenced_command_survives_a_later_fence():
    text = (
        "Install with ```pip install agenticos``` first.\n\nThen run:\n\n"
        "```bash\nagenticos start\n```"
    )

    out = to_whatsapp(text)

    assert "```pip install agenticos``` first." in out
    assert "Then run:\n\n```\nagenticos start\n```" in out


def test_two_one_line_fences_on_one_line_are_kept():
    out = to_whatsapp("Run ```a_b``` then ```c_d``` and stop.\n\n```\nx\n```")

    assert "```a_b``` then ```c_d``` and stop." in out
    assert out.endswith("```\nx\n```")


def test_a_one_line_fence_then_a_block_and_a_block_then_a_one_line_fence():
    first = to_whatsapp("```cmd_1```\n```\nblock\n```")
    second = to_whatsapp("```\nblock\n```\nthen ```cmd_2``` end")

    assert first == "```cmd_1```\n```\nblock\n```"
    assert second == "```\nblock\n```\nthen ```cmd_2``` end"


@pytest.mark.parametrize("seed", range(60))
def test_to_whatsapp_never_drops_a_word(seed):
    rng = random.Random(seed)
    source = "\n\n".join(rng.choice(_PIECES) for _ in range(rng.randint(2, 8)))

    def kept(text: str) -> str:
        # The language after an opening fence is dropped by design.
        return re.sub(r"[`\s*_~#>-]", "", re.sub(r"```[a-z]+\n", "```\n", text))

    assert kept(to_whatsapp(source)) == kept(source)


# Fences as models really write them, well formed or not: whatever the shape, every
# word the model wrote reaches the customer. Only the markers and a language tag go.


def test_a_fence_opened_mid_line_keeps_the_words_after_its_closer():
    source = "Here is the fix: ```python\nx_y = 1\n``` and that is all for now.\n\nNext:\n\n```\ny = 2\n```"

    out = to_whatsapp(source)

    assert "and that is all for now." in out
    assert "```\nx_y = 1\n```" in out
    assert out.endswith("```\ny = 2\n```")


def test_text_after_a_closing_fence_stays_prose():
    assert to_whatsapp("```\nx = 1\n``` done.") == "```\nx = 1\n``` done."


def test_an_unclosed_fence_is_left_as_written():
    source = "start ```sh\nkeep these words\n\nand **these**"

    assert to_whatsapp(source) == "start ```sh\nkeep these words\n\nand *these*"


def test_an_unclosed_fence_does_not_pair_with_a_later_one_line_fence():
    source = "start ```sh\nunclosed words\n\nRun ```pip install thing``` please."

    out = to_whatsapp(source)

    assert "```pip install thing``` please." in out
    assert "unclosed words" in out


def test_a_fence_quoted_mid_line_inside_code_does_not_close_it():
    source = "```md\nUse ```bash to open a block\nthen more\n```"

    assert to_whatsapp(source) == "```\nUse ```bash to open a block\nthen more\n```"


def test_a_fence_inside_a_quote_keeps_every_word():
    out = to_whatsapp("> ```\n> quoted code_here\n> ```\nafter the quote")

    assert "quoted code_here" in out
    assert out.endswith("after the quote")


def test_bold_after_a_one_line_fence_is_still_bold():
    assert to_whatsapp("```a``` and **b** then `c`") == "```a``` and *b* then `c`"


def test_a_four_backtick_fence_keeps_its_body_unconverted():
    out = to_whatsapp("````md\n```\ninner __init__ and # comment\n```\n````\nafter words")

    assert "inner __init__ and # comment" in out
    assert out.endswith("after words")


_SHAPES = (
    *_PIECES,
    "Here is the fix: ```python\nx_y = 1\n``` and that is all for now.",
    "```\nshort\n``` done.",
    "start ```sh\nunclosed words stay",
    "Run ```pip install thing``` please.",
    "``` is the marker word in this sentence",
    "type ``` on its own line, then words.",
    "````md\n```\nnested __init__ words\n```\n````",
    "> ```\n> quoted words here\n> ```",
    "```md\nUse ```bash to open a block\n```",
    "**bold text** and _italic text_ and `inline_code`",
)


def _kept(text: str) -> str:
    """The words a reader sees: no markup, no whitespace, no fence language tag."""
    return re.sub(r"[`\s*_~#>-]", "", re.sub(r"```[a-z]+\n", "```\n", text))


@pytest.mark.parametrize("seed", range(300))
def test_no_fence_shape_ever_loses_a_word(seed):
    rng = random.Random(seed)
    source = "\n\n".join(rng.choice(_SHAPES) for _ in range(rng.randint(1, 30)))

    out = to_whatsapp(source)

    assert _kept(out) == _kept(source)
    for limit in (4096, 400, 60):
        chunks = _split_within(out, limit)
        assert all(chunk.strip() and utf16_units(chunk) <= limit for chunk in chunks)
        assert _words("".join(chunks)) == _words(out)
