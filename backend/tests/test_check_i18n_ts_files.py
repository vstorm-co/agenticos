"""The i18n guard reads a `.ts` file, and reads it by different rules than a `.tsx` one.

`scripts/check_i18n.py` walked `frontend/src/**/*.tsx` and nothing else, so every
`.ts` file under `src/` - the hooks, the API clients, the module tables of labels -
had never been read by the offence sweep at all. 381 offences across 90 files sat
there, including nineteen `toast.success("…")` in `src/hooks/**` (#446).

Widening the glob is *not* the fix, and that is what these tests are mostly about.
A `.ts` file holds no JSX, so the four rules that anchor on a bracket are not merely
useless there but actively wrong: `; return` is a text node to `JSX_TEXT` and `a > b`
is a count to `COUNT`. Both halves are specification - what a `.ts` file must be
refused for, and what it must *not* be, because a guard that cries wolf gets switched
off.

Two adjacent decisions are pinned here too. `src/app/api/**` is skipped, because a
route handler sits outside the `[locale]` segment and has no translator to reach
(#603). And the line-skip that used to key on the `import`/`export` *keyword* now
keys on the module specifier, because in a `.ts` file every
`export const LABEL = "Provider default"` and every default parameter on an
`export function` was invisible - `getErrorMessage`'s fallback among them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_ts_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str, suffix: str = ".ts") -> list[str]:
    sample = tmp_path / f"sample{suffix}"
    sample.write_text(source)
    return [what for _, what in check_i18n.offences(sample)]


class TestWhatATsFileIsRefusedFor:
    """The rules that read a string literal wherever it sits."""

    def test_a_hook_toast_is_refused(self, tmp_path: Path) -> None:
        """The shape that sat unread the longest: nineteen of these in `src/hooks/**`."""
        source = 'toast.success("Ingestion settings saved");\n'

        # Twice, by two rules: `TOASTS` names the call and `SENTENCE` the literal. One
        # line to fix either way, and reporting it under both names says why it is copy.
        assert _offences(tmp_path, source) == [
            "string 'Ingestion settings saved'",
            "toast 'Ingestion settings saved'",
        ]

    def test_a_module_table_of_labels_is_refused(self, tmp_path: Path) -> None:
        source = 'const MCP_AUTH_LABEL = { none: "No credentials", token: "API token" };\n'

        assert _offences(tmp_path, source) == ["string 'No credentials'"]

    def test_a_sentence_built_by_interpolation_is_refused(self, tmp_path: Path) -> None:
        source = "toast.success(`Rotated ${secret.name}. The old value is gone.`);\n"

        assert any(what.startswith("template ") for what in _offences(tmp_path, source))

    def test_a_hand_rolled_plural_is_refused(self, tmp_path: Path) -> None:
        source = 'toast.success(`${count} file${count === 1 ? "" : "s"} uploaded`);\n'

        assert any(what.startswith("plural ") for what in _offences(tmp_path, source))

    def test_a_label_on_an_export_const_is_refused(self, tmp_path: Path) -> None:
        """The keyword skip hid this whole shape, which is what a `.ts` table looks like."""
        source = 'export const PROVIDER_DEFAULT = "Provider default";\n'

        assert _offences(tmp_path, source) == ["string 'Provider default'"]

    def test_a_default_parameter_on_an_export_function_is_refused(self, tmp_path: Path) -> None:
        """`getErrorMessage`'s fallback: the sentence behind most failed requests here."""
        source = (
            "export function getErrorMessage(err: unknown, "
            'fallback = "An unexpected error occurred"): string {\n  return fallback;\n}\n'
        )

        assert _offences(tmp_path, source) == ["string 'An unexpected error occurred'"]


class TestWhatATsFileIsNotRefusedFor:
    """The JSX-anchored rules, which read the syntax rather than the copy.

    Half the specification, and the half that decides whether the widening was worth
    doing: each of these is a line the guard would have reported by the thousand had the
    glob simply grown a suffix.
    """

    def test_a_statement_between_two_brackets_is_not_a_text_node(self, tmp_path: Path) -> None:
        source = "function pick(a: number, b: number) {\n  if (a > b) return a;\n  return b;\n}\n"

        assert _offences(tmp_path, source) == []

    def test_a_comparison_is_not_a_count(self, tmp_path: Path) -> None:
        """`COUNT` reads `>[^A-Za-z<>{}]*{…} word<` - which `a > b` and an object satisfy."""
        source = "const bigger = size > limit;\nconst shape = { rows } as Rows;\n"

        assert _offences(tmp_path, source) == []

    def test_a_generic_and_an_arrow_are_not_copy(self, tmp_path: Path) -> None:
        source = (
            "const load = async (): Promise<Record<string, string>> => ({});\n"
            "export type Translate = (key: string, values?: Record<string, string>) => string;\n"
        )

        assert _offences(tmp_path, source) == []

    def test_a_module_specifier_holding_two_words_is_not_copy(self, tmp_path: Path) -> None:
        """What the tightened line-skip must still skip: a path, not a sentence."""
        source = 'import { Tool } from "@/lib/tool catalog";\nexport * from "./Some Thing";\n'

        assert _offences(tmp_path, source) == []

    def test_the_same_source_in_a_tsx_file_reads_the_jsx_rules(self, tmp_path: Path) -> None:
        """The gate is the suffix, so a text node is still refused where one can exist."""
        source = "<p>Nothing here yet.</p>\n"

        assert _offences(tmp_path, source, suffix=".tsx") == ["text 'Nothing here yet.'"]
        assert _offences(tmp_path, source) == []


class TestTheFilesTheSweepSkips:
    """`UNTRANSLATABLE`, and that it is applied where the sweep is chosen rather than
    inside `offences` - a route handler's payload is still a string a rule can read."""

    def test_a_bff_route_is_named_as_untranslatable(self) -> None:
        assert check_i18n.UNTRANSLATABLE == ("app/api/",)

    def test_a_route_payload_is_the_shape_that_would_otherwise_be_reported(
        self, tmp_path: Path
    ) -> None:
        """Not exempt in itself: what excuses it is where it lives, which `main()` decides.

        Worth pinning, because a rule change that stopped reading this shape would make
        the skip look unnecessary and invite somebody to remove it.
        """
        source = 'return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });\n'

        assert _offences(tmp_path, source) == ["string 'Not authenticated'"]

    def test_the_skip_matches_on_the_path_below_src(self) -> None:
        """`app/api/` and not `/app/api/`: the test is `startswith` on an `SRC`-relative
        path, so a directory called `app/api` somewhere deeper is not covered by it."""
        under_src = "app/api/orgs/[id]/route.ts"
        deeper = "components/app/api/thing.ts"

        assert under_src.startswith(check_i18n.UNTRANSLATABLE)
        assert not deeper.startswith(check_i18n.UNTRANSLATABLE)


def test_an_exemption_still_takes_a_reason(tmp_path: Path) -> None:
    """The bargain the whole guard rests on, now that a `.ts` file can claim it."""
    source = (
        "// i18n-exempt: a wire payload from a route with no locale in scope.\n"
        'const detail = "Not authenticated";\n'
        "// i18n-exempt\n"
        'const other = "Internal server error";\n'
    )

    assert _offences(tmp_path, source) == ["string 'Internal server error'"]
