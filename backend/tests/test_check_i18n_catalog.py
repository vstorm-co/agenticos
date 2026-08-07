"""The guard reads the catalog as well as the source, and both ways round.

`scripts/check_i18n.py` used to ask one question of the catalog - does the key a
component reads exist. The reverse question was never asked, and the extraction
pass that produced `messages/en.json` had left 141 keys nobody reads, 82 of them
with a Polish translation somebody had written for nobody. Where the component had
kept the literal beside the key, the English was still on screen under every locale
and both halves of the guard reported clean (#425).

Two rules, and they are cheap because they are anchored on the catalog rather than
on the source: the sentence is already known, so neither has to decide what a text
node is. That is also what lets them reach a `.ts` file, which `offences` never has -
nineteen toasts in `src/hooks/**` were found this way.

**Which of these prove the fix.** All of them, in the sense that both functions are
new; nothing here passes on `main`. What the shape tests are really guarding is the
*reading model* - the ways a key is read that are not a literal `t("…")` call, each
of which would otherwise make the rule report a live key and fail a build that
should be green. Those are the assertions worth keeping: a rule that cannot be
trusted to be quiet is a rule somebody deletes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_catalog_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _sources(tmp_path: Path, **files: str) -> list[Path]:
    written: list[Path] = []
    for name, source in files.items():
        path = tmp_path / name.replace("__", ".")
        path.write_text(source)
        written.append(path)
    return written


def test_a_key_no_component_reads_is_reported(tmp_path: Path) -> None:
    catalog = {"agents": {"used": "Used", "orphan": "Continue"}}
    sources = _sources(
        tmp_path,
        panel__tsx='const t = useTranslations("agents");\n<p>{t("used")}</p>\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == ["agents.orphan"]


def test_a_key_built_by_interpolation_is_read(tmp_path: Path) -> None:
    """`` t(`${option.words}Label`) `` names a family, and every member of it is live.

    Seven call sites in this frontend build a key from a module-level table, so a
    rule that only saw literal calls would report about 150 keys that render fine.
    """
    catalog = {"agents": {"scopeRunLabel": "This run", "scopeAgentLabel": "This agent"}}
    sources = _sources(
        tmp_path,
        section__tsx='const t = useTranslations("agents");\n{t(`${option.words}Label`)}\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == []


def test_a_key_held_in_a_table_is_read(tmp_path: Path) -> None:
    """The table names the key; the component translating it names nothing.

    `SETTINGS_TABS` and `NAV_GROUPS` are both this shape, and the file holding them
    calls no translator at all - so the key has to count as read from the string
    itself, wherever it is.
    """
    catalog = {"nav": {"profile": "Profile"}}
    sources = _sources(
        tmp_path,
        tabs__ts='export const TABS = [{ labelKey: "profile", href: "/settings/profile" }];\n',
        row__tsx='const t = useTranslations("nav");\n{t(tab.labelKey)}\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == []


def test_a_key_a_table_holds_relative_to_its_namespace_is_read(tmp_path: Path) -> None:
    """The table writes down what the component's translator will resolve, not the key.

    A dashboard layout entry is `{ titleKey: "widgets.my-agents.sharedTitle" }` beside a
    `useTranslations("dashboard")`, so neither the whole key nor its last segment is
    spelled anywhere. Two separate things had to hold for this to count as read, and
    each was false: a segment may be kebab-case - 101 keys here are filed under an id
    like `my-agents` - and any dot-suffix counts, not only the last segment. The other
    hundred kebab keys were passing on the accident that `title` is spelled somewhere.
    """
    catalog = {"dashboard": {"widgets": {"my-agents": {"sharedTitle": "Shared with you"}}}}
    sources = _sources(
        tmp_path,
        layouts__ts='export const L = [{ titleKey: "widgets.my-agents.sharedTitle" }];\n',
        grid__tsx='const t = useTranslations("dashboard");\n{t(card.titleKey)}\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == []


def test_a_kebab_case_key_nothing_holds_is_still_reported(tmp_path: Path) -> None:
    """The companion to the rule above: reading kebab-case is not waving it through."""
    catalog = {"dashboard": {"widgets": {"top-orgs": {"gone": "Gone"}}}}
    sources = _sources(tmp_path, grid__tsx='const t = useTranslations("dashboard");\n')

    assert check_i18n.unread_keys(catalog, sources) == ["dashboard.widgets.top-orgs.gone"]


def test_a_translator_bound_to_another_name_still_reads_its_keys(tmp_path: Path) -> None:
    """`tc`, `ts` and `tAgents` are all in this tree, and `t(` alone would miss them."""
    catalog = {"common": {"cancel": "Cancel"}}
    sources = _sources(
        tmp_path,
        dialog__tsx='const tc = useTranslations("common");\n{tc("cancel")}\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == []


def test_a_key_read_with_rich_is_read(tmp_path: Path) -> None:
    """A message with a tag in it is read through `t.rich`, never through `t`."""
    catalog = {"auth": {"signInHeading": "Sign in to <em>your workspace.</em>"}}
    sources = _sources(
        tmp_path,
        form__tsx='const t = useTranslations("auth");\n{t.rich("signInHeading", { em })}\n',
    )

    assert check_i18n.unread_keys(catalog, sources) == []


def test_a_message_written_out_in_a_component_is_reported(tmp_path: Path) -> None:
    catalog = {"members": {"memberRemoved": "Member removed"}}
    sources = _sources(tmp_path, hook__ts='toast.success("Member removed");\n')

    found = check_i18n.duplicated_in_source(catalog, sources)

    assert [(key, words) for _, _, key, words in found] == [
        ("members.memberRemoved", "Member removed")
    ]


def test_a_message_written_out_as_a_text_node_is_reported(tmp_path: Path) -> None:
    """The shape the offence sweep cannot see, and the reason this rule is worth having.

    `Sign in to <em>{t("yourWorkspace")}</em>` is a text node whose `>` is on the line
    above, so `JSX_TEXT` reads past it (#141) - and `MIXED` wants an interpolation
    inside the node. Five headings shipped in English that way while `auth.sign` sat
    in the catalog holding the same three words.
    """
    catalog = {"auth": {"sign": "Sign in to"}}
    sources = _sources(
        tmp_path,
        heading__tsx='<h1>\n  Sign in to <em>{t("yourWorkspace")}</em>\n</h1>\n',
    )

    found = check_i18n.duplicated_in_source(catalog, sources)

    assert [(number, key, words) for _, number, key, words in found] == [
        (2, "auth.sign", "Sign in to")
    ]


def test_a_message_that_is_only_part_of_a_longer_one_is_not_reported(tmp_path: Path) -> None:
    """Runs are compared whole.

    A substring search was the first shape of this rule and it reported
    `chat.preview.failedToLoad` inside `Failed to load conversations` eleven times -
    a different sentence that happens to open the same way.
    """
    catalog = {"chat": {"preview": {"failedToLoad": "Failed to load"}}}
    sources = _sources(tmp_path, hook__ts='toast.error("Failed to load conversations");\n')

    assert check_i18n.duplicated_in_source(catalog, sources) == []


def test_a_message_with_an_argument_is_not_compared(tmp_path: Path) -> None:
    """No run of source can equal an ICU message, so a match would say nothing."""
    catalog = {"members": {"inviteSent": "Invitation sent to {email}"}}
    sources = _sources(tmp_path, hook__ts="toast.success(t('inviteSent', { email }));\n")

    assert check_i18n.duplicated_in_source(catalog, sources) == []


def test_a_literal_marked_exempt_is_not_reported(tmp_path: Path) -> None:
    """The escape hatch is the one the rest of this script already uses.

    Two route handlers need it: a handler has no locale to resolve a message in, and
    the `detail` it falls back to is the words the client ends up showing.
    """
    catalog = {"pages": {"settings": {"uploadFailed": "Upload failed"}}}
    sources = _sources(
        tmp_path,
        route__ts="// i18n-exempt: a route handler has no locale\nconst e = { detail: 'Upload failed' };\n",
    )

    assert check_i18n.duplicated_in_source(catalog, sources) == []
