"""Tests for the compiled-email-template loader.

This module exists because of a failure that was invisible for as long as it
took someone to read the server log. `_DIST_DIR` was a fixed four `.parent`
hops from this package, which resolves to `backend/emails/compiled` - a
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

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.email import templates
from app.services.email.exceptions import EmailTemplateError
from app.services.email.service import EmailKey
from app.services.email.templates import render_email

_COMPILED_EMAIL_KEYS = (
    "approval_pending",
    "approval_requested",
    "budget_exceeded",
    "email_change_notice",
    "email_change_verification",
    "email_verification",
    "failure_learning_digest",
    "impersonation_notice",
    "invitation",
    "low_credits",
    "magic_link",
    "newsletter_welcome",
    "notification",
    "password_reset",
    "payment_failed",
    "payment_succeeded",
    "subscription_canceled",
    "subscription_changed",
    "trial_ending",
    "trial_expired",
    "usage_report",
    "welcome",
    "workflow_message",
)

_REAL_TEMPLATE_CONTEXT = {
    "accept_url": "https://app.example.test/accept?token=abc&next=%2Fhome",
    "access_until": "2026-12-01",
    "admin_email": "admin@example.test",
    "agent_name": "Research Agent",
    "agents": "3",
    "amount": "$12.34",
    "app_name": "Example Workspace",
    "approvals_url": "https://app.example.test/approvals?token=abc&next=%2Fhome",
    "asked_by": "Asked by Eve",
    "balance": "100",
    "body": "First workflow line\nSecond line <details>& notes",
    "context_url": "https://app.example.test/updates?token=abc&next=%2Fhome",
    "confirm_url": "https://app.example.test/confirm?token=abc&next=%2Fhome",
    "dashboard_url": "https://app.example.test/dashboard?token=abc&next=%2Fhome",
    "days_left": "5",
    "email_font_base_url": "https://attacker.example/fonts",
    "expires_in": "1 hour",
    "invoice_url": "https://app.example.test/invoice?token=abc&next=%2Fhome",
    "inviter_name": "Eve",
    "login_url": "https://app.example.test/login?token=abc&next=%2Fhome",
    "magic_url": "https://app.example.test/magic?token=abc&next=%2Fhome",
    "name": "Ada",
    "new_email": "ada.new@example.test",
    "new_plan": "Pro",
    "old_plan": "Starter",
    "org_name": "Example Org",
    "period": "October 2026",
    "plan_name": "Pro",
    "reason": "Monthly allowance reached",
    "resubscribe_url": "https://app.example.test/resubscribe?token=abc&next=%2Fhome",
    "reset_url": "https://app.example.test/reset?token=abc&next=%2Fhome",
    "runs": "42",
    "run_url": "https://app.example.test/runs/42?token=abc&next=%2Fhome",
    "spent": "$25.00",
    "subject": "Workflow status",
    "summary": "Update one\nUpdate two <safe>& sound",
    "topup_url": "https://app.example.test/topup?token=abc&next=%2Fhome",
    "tools": "search_web(query='A & B')\nsend_email(to='ada@example.test')",
    "total": "$48.00",
    "update_url": "https://app.example.test/update?token=abc&next=%2Fhome",
    "upgrade_url": "https://app.example.test/upgrade?token=abc&next=%2Fhome",
    "verify_url": "https://app.example.test/verify?token=abc&next=%2Fhome",
    "portal_url": "https://app.example.test/portal?token=abc&next=%2Fhome",
}


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


class TestCompiledEmailContract:
    @pytest.mark.parametrize("key", _COMPILED_EMAIL_KEYS)
    def test_every_compiled_template_renders_its_declared_variables(
        self, key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(templates.settings, "FRONTEND_URL", "https://app.example.test/")

        subject, html, text = render_email(key, _REAL_TEMPLATE_CONTEXT)

        unresolved = re.compile(r"\[\[[^\]]+\]\]")
        assert not unresolved.search(subject), key
        assert not unresolved.search(html), key
        assert not unresolved.search(text), key
        assert "Example Workspace" in html, key
        assert "Example Workspace" in text, key
        assert "https://app.example.test/fonts/email/" in html, key
        assert "attacker.example" not in html, key

    def test_action_and_copyable_links_keep_escaped_query_parameters(self) -> None:
        _, html, text = render_email("invitation", _REAL_TEMPLATE_CONTEXT)

        escaped_url = "https://app.example.test/accept?token=abc&amp;next=%2Fhome"
        assert html.count(f'href="{escaped_url}"') == 2
        assert "https://app.example.test/accept?token=abc&next=%2Fhome" in text

    @pytest.mark.security
    def test_live_workflow_and_approval_content_keeps_escaped_multiline_values(self) -> None:
        _, workflow_html, workflow_text = render_email("workflow_message", _REAL_TEMPLATE_CONTEXT)
        _, approval_html, approval_text = render_email("approval_requested", _REAL_TEMPLATE_CONTEXT)

        assert "First workflow line\nSecond line &lt;details&gt;&amp; notes" in workflow_html
        assert "First workflow line\nSecond line <details>& notes" in workflow_text
        assert (
            "search_web(query=&#x27;A &amp; B&#x27;)\nsend_email(to=&#x27;ada@example.test&#x27;)"
            in approval_html
        )
        assert "search_web(query='A & B')\nsend_email(to='ada@example.test')" in approval_text

    def test_compiled_templates_match_the_generator(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "emails/build.py", "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr


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
        header fails here rather than quietly truncating a live email - and so
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

    def test_a_context_value_cannot_inject_markup_into_the_html_body(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A context value is routinely builder-controlled text (an agent's
        name, a tool id) reaching this from a stored notification's
        `render_context`, not something this module already trusts - it must
        not be spliced into the html body as markup. The text part, never
        interpreted as markup by anything that reads it, keeps the raw value."""
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<p>[[agent_name]] says hi</p>",
            text="Subject: [[agent_name]]\n\n[[agent_name]] says hi",
        )

        subject, html, text = render_email(
            "greeting", {"agent_name": "<img src=x onerror=alert(1)>"}
        )

        assert "<img" not in html
        assert html == "<p>&lt;img src=x onerror=alert(1)&gt; says hi</p>"
        assert text == "<img src=x onerror=alert(1)> says hi"
        assert subject == "<img src=x onerror=alert(1)>"

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

    def test_a_value_with_html_metacharacters_is_escaped_in_the_html_part(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every value substituted here is plain text by contract - an agent's
        own name, chosen by whoever created it, being one - never markup this
        template means to embed. Unescaped, a name like this one breaks out
        of the paragraph it was meant to sit inside as text."""
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<p>[[name]]</p>",
            text="Subject: hi\n[[name]]",
        )

        subject, html, text = render_email("greeting", {"name": "<img src=x onerror=alert(1)>&\"'"})

        assert html == "<p>&lt;img src=x onerror=alert(1)&gt;&amp;&quot;&#x27;</p>"
        # The subject and text parts carry no markup to break out of, so the
        # value they ship is the one that was given - unescaped.
        assert subject == "hi"
        assert text == "<img src=x onerror=alert(1)>&\"'"

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

    def test_html_receives_an_absolute_font_url_from_frontend_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<style>@font-face{src:url('[[email_font_base_url]]/Geist-Regular.woff2')}</style>",
            text="Subject: hi\nBody",
        )
        monkeypatch.setattr(templates.settings, "FRONTEND_URL", "https://app.example.test/")

        _, html, _ = render_email("greeting", {})

        assert "https://app.example.test/fonts/email/Geist-Regular.woff2" in html

    def test_caller_cannot_override_the_html_font_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<style>@font-face{src:url('[[email_font_base_url]]/Geist-Regular.woff2')}</style>",
            text="Subject: hi\nBody",
        )
        monkeypatch.setattr(templates.settings, "FRONTEND_URL", "https://app.example.test///")

        _, html, _ = render_email(
            "greeting", {"email_font_base_url": "https://attacker.example/fonts"}
        )

        assert "https://app.example.test/fonts/email/Geist-Regular.woff2" in html
        assert "attacker.example" not in html

    def test_font_url_is_html_escaped_and_does_not_change_plain_text_rendering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_template(
            tmp_path,
            monkeypatch,
            key="greeting",
            html="<style>@font-face{src:url('[[email_font_base_url]]/Geist-Regular.woff2')}</style><p>[[body]]</p>",
            text="Subject: [[body]]\n[[body]]",
        )
        monkeypatch.setattr(templates.settings, "FRONTEND_URL", "https://app.example.test/")
        long_url = "https://example.test/path?token=" + ("x" * 512) + "&next=%2Fhome"
        body = f"Line one\n{long_url}\nLine three"

        subject, html, text = render_email("greeting", {"body": body})

        assert "https://app.example.test/fonts/email/Geist-Regular.woff2" in html
        assert long_url.replace("&", "&amp;") in html
        assert "Line one\n" + long_url.replace("&", "&amp;") + "\nLine three" in html
        assert subject == body
        assert text == body


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


class TestApprovalMailNamesWhoAsked:
    """The asker line is in all four approval parts, and costs no blank line when empty (#2656)."""

    @pytest.mark.parametrize("key", [EmailKey.APPROVAL_REQUESTED, EmailKey.APPROVAL_PENDING])
    def test_the_asker_is_named_in_both_parts(self, key: EmailKey) -> None:
        context = {"agent_name": "Bot", "tools": "send_email", "asked_by": "Asked by Eve"}
        _, html, text = render_email(key.value, context)
        assert "Asked by Eve" in html
        assert "Asked by Eve" in text

    @pytest.mark.parametrize("key", [EmailKey.APPROVAL_REQUESTED, EmailKey.APPROVAL_PENDING])
    def test_an_empty_asker_leaves_no_extra_blank_line_in_the_text(self, key: EmailKey) -> None:
        context = {"agent_name": "Bot", "tools": "send_email", "asked_by": ""}
        _, _, text = render_email(key.value, context)
        assert "\n\n\n" not in text
