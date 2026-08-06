"""The i18n guard reads a text node beside an inline handler.

`scripts/check_i18n.py` used to skip a whole line holding `=>`, because
`onTest: (() => Promise<void>) | null` reads as a text node to a regex. An inline
handler is the most common thing on a JSX line, so that exemption was far wider than
the problem: `<DropdownMenuItem onSelect={() => onTools(c)}>Check connection</…>` was
invisible, sitting between two siblings that read from the catalog (#314).

The line-level guess is gone. What tells the two apart is the `>` itself - an arrow's
or a comparison's, or a tag's - so the rule is a lookbehind rather than a decision
about the line. Measured over the whole tree, that reports the two strings above and
nothing else.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_arrow_lines_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    sample = tmp_path / "sample.tsx"
    sample.write_text(source)
    return check_i18n.offences(sample)


def test_copy_beside_an_inline_handler_is_refused(tmp_path: Path) -> None:
    source = "<DropdownMenuItem onSelect={() => onTools(c)}>Check connection</DropdownMenuItem>\n"

    assert [what for _, what in _offences(tmp_path, source) if what.startswith("text ")]


def test_a_promise_returning_signature_is_not_a_text_node(tmp_path: Path) -> None:
    """The shape the line-level skip existed for, and the reason it cannot come back.

    `=> Promise<void>` puts a `>` and a `<` on one line with a word between them. It is
    a type, and the `>` belongs to the arrow.
    """
    assert _offences(tmp_path, "  onTest: (() => Promise<void>) | null;\n") == []


def test_a_generic_call_inside_an_arrow_is_not_a_text_node(tmp_path: Path) -> None:
    """`apiClient.get<KnowledgeBaseList>("/kb")` - a `>` closing a type argument."""
    source = '    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,\n'

    assert _offences(tmp_path, source) == []


def test_a_comparison_is_not_a_text_node(tmp_path: Path) -> None:
    """`percent >= 80 && "amber"` was the other thing the skip was covering for."""
    assert _offences(tmp_path, '  const tone = percent >= 80 && "text-amber-600";\n') == []


def test_the_message_that_replaces_it_still_passes(tmp_path: Path) -> None:
    source = '<DropdownMenuItem onSelect={() => onEdit(c)}>{t("settings")}</DropdownMenuItem>\n'

    assert _offences(tmp_path, source) == []
