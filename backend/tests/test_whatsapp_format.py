"""Markdown into what WhatsApp draws, and the answer cut to its message limit (#2076)."""

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
