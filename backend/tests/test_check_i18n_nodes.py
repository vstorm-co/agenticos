"""The i18n guard reads a text node whole, arrows and line breaks included.

`scripts/check_i18n.py` used to read a `.tsx` file one line at a time and decide per
line whether it was TypeScript. Both shortcuts hid copy that was sitting in the tree
in English on a page a Polish user opens (#314):

* **any line holding `=>` was skipped**, because `onTest: (() => Promise<void>) | null`
  reads as a text node to a regex - and an inline handler is the single most common
  thing on a JSX line, so `<DropdownMenuItem onSelect={() => onEdit(c)}>Settings</…>`
  was invisible. Ungating the sweep on its own reported eleven false positives, ten of
  them `Promise`: the discriminator had to get better, not looser, which is what
  `mask_generics` is for;
* **a node the formatter broke across lines matched nothing**, because every rule
  anchors on a `>` and a `<` and neither is on the line holding the words.

These are the regression tests both halves need, and half of each is the near-miss:
a guard that cries wolf gets switched off, so what must *not* be reported is as much
of the specification as what must.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_nodes_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    sample = tmp_path / "sample.tsx"
    sample.write_text(source)
    return check_i18n.offences(sample)


def test_copy_beside_an_inline_handler_is_refused(tmp_path: Path) -> None:
    """The shape that hid the most: two menu items between two that read `t(…)`.

    `mcp-server-list.tsx` rendered `Check connection` and `Settings` verbatim in
    between `t("finishSign")` and `t("disconnect")`, which is what makes them a slip
    rather than a decision - and the guard read past both because the line holds `=>`.
    """
    source = "<DropdownMenuItem onSelect={() => onEdit(connection)}>Settings</DropdownMenuItem>\n"
    assert [what for _, what in _offences(tmp_path, source) if what.startswith("text ")]


def test_a_generic_return_type_beside_an_arrow_is_not_a_text_node(tmp_path: Path) -> None:
    """`(() => Promise<void>)` is the shape that made skipping the line look necessary.

    The arrow's `>` opens what a regex reads as a node and the generic's `<` closes it,
    so the type name lands in the middle. Removing the type rather than the line is
    what lets the sweep run where an inline handler lives.
    """
    assert _offences(tmp_path, "  onTest: (() => Promise<void>) | null;\n") == []


def test_a_generic_call_inside_an_arrow_is_not_a_text_node(tmp_path: Path) -> None:
    """The eleventh false positive: `(await apiClient.get` between two type arguments."""
    source = "  const load = async () => (await apiClient.get<AgentRead[]>(url)).items;\n"
    assert _offences(tmp_path, source) == []


def test_a_generic_spanning_lines_is_not_a_text_node(tmp_path: Path) -> None:
    """`React.forwardRef<A, B>` is broken over four lines all over `components/ui`.

    Reading the file as one string is what makes this reachable at all: the type
    argument list opens on one line and closes on another, so masking it has to
    happen on the joined source rather than line by line.
    """
    source = (
        "const Item = React.forwardRef<\n"
        "  React.ComponentRef<typeof Primitive.Item>,\n"
        "  React.ComponentPropsWithoutRef<typeof Primitive.Item>\n"
        ">(({ className, ...props }, ref) => <Primitive.Item ref={ref} {...props} />);\n"
    )
    assert _offences(tmp_path, source) == []


def test_a_node_the_formatter_broke_across_lines_is_refused(tmp_path: Path) -> None:
    """`{used} of {max} used` on the members page, with neither bracket on its line.

    The opening `>` belongs to the fragment above it and the closing `<` to the guard
    below it, so every rule read past a string that is two words and two
    interpolations - exactly what `MIXED` exists for.
    """
    source = (
        "<>\n"
        '  {inv.used_count ?? 0} of {inv.max_uses ?? "∞"} used\n'
        "  {inv.email_domain && <> · @{inv.email_domain} only</>}\n"
        "</>\n"
    )
    assert [what for _, what in _offences(tmp_path, source) if what.startswith("text ")]


def test_a_sentence_wrapped_onto_a_second_line_is_refused(tmp_path: Path) -> None:
    """A paragraph long enough for prettier to wrap it is still one message (#332)."""
    source = (
        '<p className="text-xs">\n'
        "  No {provider.label} key in the vault yet. Add one here and it is stored for every\n"
        "  agent in this organization.\n"
        "</p>\n"
    )
    assert [what for _, what in _offences(tmp_path, source) if what.startswith("text ")]


def test_a_count_behind_a_separator_is_refused(tmp_path: Path) -> None:
    """`· @{domain} only` is the count shape with punctuation in front of it.

    `LEAD` already steps over a separator to reach a leading word; `COUNT` did not,
    so a fragment inside a row of them was exempt by virtue of the row.
    """
    source = "<> · @{inv.email_domain} only</>\n"
    assert [what for _, what in _offences(tmp_path, source) if what.startswith("count ")]


def test_a_ternary_between_two_elements_is_not_a_text_node(tmp_path: Path) -> None:
    """`) : rows.length === 0 ? (` sits between a `/>` and a `<`, one line each way.

    Reading the file as one string puts a lot of code between two angle brackets. What
    says this is not copy is the code punctuation left once the interpolations are
    taken out - here an `=`, and a `;` or a bracket in the rest of the class.
    """
    source = (
        "{isLoading ? (\n"
        "  <LoadingState />\n"
        ") : rows.length === 0 ? (\n"
        "  <EmptyState title={t('nothingYet')} />\n"
        ") : (\n"
        "  <Table rows={rows} />\n"
        ")}\n"
    )
    assert _offences(tmp_path, source) == []


def test_a_jsx_spacer_is_not_the_interpolation_a_count_needs(tmp_path: Path) -> None:
    """`{" "}` is the space prettier could not leave in the source, not a value.

    Without that, joining the lines reads `{" "} to <span>` as the count shape `{n}
    word`, and the guard reports the word `to` on a line nobody wrote copy on.
    """
    source = '<>\n  {" "}\n  to <span className="font-medium">{email}</span>\n</>\n'
    assert [what for _, what in _offences(tmp_path, source) if what.startswith("count ")] == []


def test_a_message_call_broken_across_lines_is_not_read_as_copy(tmp_path: Path) -> None:
    """The remedy has to pass once the lines are joined, or the rule forbids its own fix."""
    source = '<p>\n  {t("savedModelCount", {\n    count: profiles.length,\n  })}\n</p>\n'
    assert _offences(tmp_path, source) == []
def test_masking_a_generic_is_what_keeps_a_whole_file_quiet(tmp_path: Path) -> None:
    """The one case that fails when `mask_generics` stops working.

    Reading the file as one string is what makes a multi-line generic reachable
    at all, and it is also what makes it dangerous: `SVGProps<SVGSVGElement>`
    closes with a `>`, the next `<` is a tag several lines below, and everything
    between them reads as one long text node of ordinary words.

    Worth having because the ten cases above do not test this. Every one of them
    passes with `mask_generics` stubbed to `return text` - they are kept quiet by
    the two-word threshold or by holding no `<` at all, not by the masking - so
    the function could be broken by a refactor and only a tree-wide `make lint`
    would notice. This snippet is `components/icons/brand-icon.tsx` trimmed to
    the shape that regressed, and it reports one offence without the mask.
    """
    source = (
        "interface BrandIconProps extends SVGProps<SVGSVGElement> {\n"
        "  name: BrandName;\n"
        "}\n"
        "\n"
        'export function BrandIcon({ name, "aria-label": ariaLabel, ...props }: BrandIconProps) {\n'
        "  const Icon = ICONS[name];\n"
        '  const a11y = ariaLabel ? { role: "img" } : { "aria-hidden": true };\n'
        "  return <Icon {...a11y} {...props} />;\n"
        "}\n"
    )
    assert _offences(tmp_path, source) == []
