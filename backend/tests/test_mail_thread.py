"""The thread headers of a mail, read the same way for Gmail and Outlook."""

from app.services.portals.mail_thread import (
    MAX_ID_CHARS,
    MAX_REFERENCES,
    clean_text,
    thread_headers,
)


def test_a_folded_message_id_with_a_comment_is_read() -> None:
    found = thread_headers([("Message-ID", "\r\n <a@x.example> (comment)")])

    assert found["rfc_message_id"] == "<a@x.example>"


def test_in_reply_to_keeps_the_first_of_two_ids() -> None:
    found = thread_headers([("In-Reply-To", "<a@x.example> <b@x.example>")])

    assert found["in_reply_to"] == "<a@x.example>"


def test_references_are_deduplicated_in_order() -> None:
    found = thread_headers(
        [("References", "<a@x.example>\r\n <b@x.example> <a@x.example> <c@x.example>")]
    )

    assert found["references"] == ["<a@x.example>", "<b@x.example>", "<c@x.example>"]


def test_over_twenty_references_keep_the_root_and_the_last_nineteen() -> None:
    ids = [f"<{n}@x.example>" for n in range(25)]

    found = thread_headers([("References", " ".join(ids))])

    assert len(found["references"]) == MAX_REFERENCES
    assert found["references"] == [ids[0], *ids[6:]]


def test_an_id_over_998_characters_is_dropped() -> None:
    long_id = "<" + "a" * MAX_ID_CHARS + "@x.example>"

    found = thread_headers(
        [
            ("Message-ID", long_id),
            ("References", f"{long_id} <b@x.example>"),
        ]
    )

    assert found["rfc_message_id"] == ""
    assert found["references"] == ["<b@x.example>"]


def test_a_missing_header_gives_empty_values() -> None:
    assert thread_headers([("Subject", "hello")]) == {
        "rfc_message_id": "",
        "in_reply_to": "",
        "references": [],
    }


def test_the_topmost_of_duplicate_headers_wins() -> None:
    found = thread_headers(
        [
            ("Message-ID", "<top@x.example>"),
            ("Message-ID", "<second@x.example>"),
            ("References", "<top@x.example>"),
            ("References", "<second@x.example>"),
        ]
    )

    assert found["rfc_message_id"] == "<top@x.example>"
    assert found["references"] == ["<top@x.example>"]


def test_header_names_match_ignoring_case() -> None:
    found = thread_headers([("message-id", "<a@x.example>"), ("IN-REPLY-TO", "<b@x.example>")])

    assert found["rfc_message_id"] == "<a@x.example>"
    assert found["in_reply_to"] == "<b@x.example>"


def test_a_value_without_angle_brackets_gives_nothing() -> None:
    found = thread_headers([("Message-ID", "a@x.example"), ("References", "a@x.example")])

    assert found["rfc_message_id"] == ""
    assert found["references"] == []


def test_an_id_of_998_characters_is_kept_and_one_of_999_is_dropped() -> None:
    kept = "<" + "a" * (MAX_ID_CHARS - 2) + ">"
    dropped = "<" + "a" * (MAX_ID_CHARS - 1) + ">"

    found = thread_headers([("References", f"{kept} {dropped}")])

    assert len(kept) == MAX_ID_CHARS
    assert found["references"] == [kept]


def test_clean_text_drops_nul_and_replaces_a_lone_surrogate():
    assert clean_text("a\x00b\ud800c") == "ab\ufffdc"
    assert clean_text(None) == ""
    assert clean_text(7) == "7"
