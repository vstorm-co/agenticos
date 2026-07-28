"""Tests for the compiled-email-template loader.

This module exists because of a failure that was invisible for as long as it
took someone to read the server log. `_DIST_DIR` was a fixed four `.parent`
hops from this package, which resolves to `backend/emails/compiled` — a
directory that has never existed. The templates live at the repository root, and
in the container at `/app/emails`, so *every* email raised
`EmailTemplateError`. Every call site wraps the send in
`except Exception: logger.exception(...)`, so registration still returned 201
and the password-reset endpoint still returned 200. The product sent no mail at
all and reported success for all of it.

Two things are therefore asserted here that the loader cannot assert about
itself: that the directory is found from wherever the package is installed, and
that every template the email service can ask for is actually on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.email import templates
from app.services.email.exceptions import EmailTemplateError
from app.services.email.service import EmailKey
from app.services.email.templates import render_email


class TestFindingTheCompiledDirectory:
    def test_it_is_found_from_the_real_package_location(self) -> None:
        """The bug in one line: this returned a path that did not exist."""
        assert templates._compiled_dir().is_dir()

    @pytest.mark.parametrize(
        "package_depth",
        [
            # The repository layout: emails/ is a sibling of backend/, and the
            # package sits below that. The depth that used to be hardcoded.
            pytest.param(4, id="repository_root"),
            # The container layout: /app/emails beside the app package, one
            # level shallower. The same hardcoded depth resolved to /emails.
            pytest.param(3, id="container_root"),
        ],
    )
    def test_it_is_found_at_either_layout_depth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package_depth: int
    ) -> None:
        """Neither layout may depend on the other's nesting depth.

        A fix that added a `.parent` would pass the repository case and break
        the container, which is how this got shipped in the first place.
        """
        compiled = tmp_path / "emails" / "compiled"
        compiled.mkdir(parents=True)
        module = tmp_path.joinpath(*(f"level{n}" for n in range(package_depth))) / "templates.py"
        monkeypatch.setattr(templates, "_SEARCH_ORIGIN", module)

        assert templates._compiled_dir() == compiled

    def test_a_missing_directory_is_refused_loudly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure that was silent must at least name what it looked for."""
        monkeypatch.setattr(templates, "_SEARCH_ORIGIN", tmp_path / "nowhere" / "templates.py")

        with pytest.raises(EmailTemplateError) as caught:
            templates._compiled_dir()

        assert "emails" in str(caught.value)


class TestEveryTemplateTheServiceCanAskFor:
    @pytest.mark.parametrize("key", list(EmailKey), ids=lambda key: key.value)
    def test_both_parts_are_on_disk(self, key: EmailKey) -> None:
        """An email service key with no template is an email that cannot send.

        Parametrized over the enum rather than a hand-written list so adding a
        key without compiling its template fails here instead of in production,
        where the exception is swallowed by the caller.
        """
        compiled = templates._compiled_dir()

        assert (compiled / f"{key.value}.html").is_file()
        assert (compiled / f"{key.value}.txt").is_file()

    @pytest.mark.parametrize("key", list(EmailKey), ids=lambda key: key.value)
    def test_it_renders_without_a_template_error(self, key: EmailKey) -> None:
        subject, html, text = render_email(key.value, {"app_name": "agenticos"})

        assert subject
        assert html
        assert text

    def test_a_key_with_no_template_is_refused(self) -> None:
        with pytest.raises(EmailTemplateError) as caught:
            render_email("no_such_email", {})

        assert "no_such_email.html" in str(caught.value)


class TestRendering:
    def test_the_subject_comes_off_the_first_text_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled = _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<p>Hello [[name]]</p>",
            text="Subject: Hello [[name]]\n\nHello [[name]], welcome.",
        )
        assert compiled.is_dir()

        subject, html, text = render_email("greeting", {"name": "Ada"})

        assert subject == "Hello Ada"
        assert html == "<p>Hello Ada</p>"
        assert text == "Hello Ada, welcome."

    def test_a_text_part_without_a_subject_line_loses_its_first_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wart, pinned rather than fixed: the first line is always consumed.

        `render_email` drops line one whether or not it was a `Subject:` header,
        so a text part missing the header falls back to the key for a subject
        *and* silently ships a body with its opening line removed. Every
        template in `emails/compiled/` carries the header, so nothing sent today
        hits this. It is asserted so that authoring a template without the
        header fails here rather than quietly truncating a live email — and so
        that tightening the parser is a deliberate change to this test.
        """
        _fake_template(tmp_path, monkeypatch, key="greeting", html="<p>hi</p>", text="Hello there.")

        subject, _, text = render_email("greeting", {})

        assert subject == "greeting"
        assert text == ""

    def test_an_empty_text_part_still_renders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_template(tmp_path, monkeypatch, key="greeting", html="<p>hi</p>", text="")

        subject, html, text = render_email("greeting", {})

        assert subject == "greeting"
        assert html == "<p>hi</p>"
        assert text == ""

    def test_a_none_value_renders_as_nothing_rather_than_the_word_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`unsubscribe_url` defaults to empty; "None" in a live email is worse."""
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<a href='[[unsubscribe_url]]'>x</a>",
            text="Subject: hi\n[[unsubscribe_url]]",
        )

        _, html, text = render_email("greeting", {"unsubscribe_url": None})

        assert html == "<a href=''>x</a>"
        assert text == ""

    def test_an_unsupplied_placeholder_is_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Documents the current behaviour: substitution is driven by the context.

        A template referring to a variable nobody passed ships the raw
        `[[placeholder]]` to the recipient. Worth knowing when adding a
        template, and worth failing this test if that is ever tightened.
        """
        _fake_template(
            tmp_path, monkeypatch, key="greeting", html="<p>[[missing]]</p>", text="Subject: hi"
        )

        _, html, _ = render_email("greeting", {})

        assert html == "<p>[[missing]]</p>"


def _fake_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str,
    html: str,
    text: str,
) -> Path:
    """Point the loader at a throwaway `emails/compiled/` holding one template."""
    compiled = tmp_path / "emails" / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / f"{key}.html").write_text(html, encoding="utf-8")
    (compiled / f"{key}.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(templates, "_SEARCH_ORIGIN", tmp_path / "pkg" / "templates.py")
    return compiled
