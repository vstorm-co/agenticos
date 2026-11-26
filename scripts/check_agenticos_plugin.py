#!/usr/bin/env python3
"""Check the shipped plugin against registered tools without importing the app."""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = Path("plugins/agenticos")
MAP = PLUGIN / "skills/operating-agenticos/reference/tool-map.md"


def registered_tools(root: Path) -> set[str]:
    """Read the explicit operation tables; do not execute plugin or app code."""
    names: set[str] = set()
    for filename, factory in (
        ("_tools.py", "platform_tools"),
        ("_lifecycle.py", "lifecycle_operations"),
        ("_details.py", "detail_operations"),
        ("_administration.py", "administration_operations"),
        ("_disclosure.py", "disclosure_operations"),
    ):
        tree = ast.parse((root / "backend/app/services/platform_mcp" / filename).read_text())
        function = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == factory
        )
        for node in function.body:
            value = node.value if isinstance(node, (ast.Assign, ast.Return)) else None
            if not isinstance(value, ast.Tuple):
                continue
            for entry in value.elts:
                if isinstance(entry, ast.Tuple) and len(entry.elts) in (2, 3):
                    name, writes = entry.elts[:2]
                    if (
                        isinstance(name, ast.Name)
                        and isinstance(writes, ast.Constant)
                        and isinstance(writes.value, bool)
                    ):
                        if name.id in names:
                            raise ValueError(f"Duplicate platform tool: {name.id}")
                        names.add(name.id)
    return names


def documented_tools(content: str) -> set[str]:
    """Only the first column names tools; other columns contain permission IDs."""
    names: set[str] = set()
    for row in content.splitlines():
        cells = row.split("|")
        if row.startswith("|") and len(cells) > 2:
            names.update(re.findall(r"`([a-z][a-z_]+)`", cells[1]))
    return names


def check(root: Path = ROOT) -> list[str]:
    """Return actionable package/contract errors; an empty list means agreement."""
    errors: list[str] = []
    registered = registered_tools(root)
    documented = documented_tools((root / MAP).read_text())
    for name in sorted(registered - documented):
        errors.append(f"Tool missing from {MAP}: {name}")
    for name in sorted(documented - registered):
        errors.append(f"Unregistered tool in {MAP}: {name}")
    for relative in (
        Path(".claude-plugin/marketplace.json"),
        PLUGIN / ".claude-plugin/plugin.json",
        PLUGIN / "compatibility.json",
        PLUGIN / "evaluations/evaluations.json",
    ):
        try:
            json.loads((root / relative).read_text())
        except (OSError, ValueError) as error:
            errors.append(f"{relative}: {error}")
    for skill in (root / PLUGIN / "skills").glob("*/SKILL.md"):
        content = skill.read_text()
        if (
            not content.startswith("---\n")
            or "\nname: " not in content
            or "\ndescription: " not in content
        ):
            errors.append(f"Invalid skill frontmatter: {skill.relative_to(root)}")
    for page in (root / PLUGIN).rglob("*.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", page.read_text()):
            if "://" not in target and not target.startswith("#"):
                path = target.split("#", 1)[0]
                if not (page.parent / path).exists():
                    errors.append(f"Broken local link in {page.relative_to(root)}: {target}")
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(
            f"AgenticOS plugin: {len(registered_tools(ROOT))} tools documented; package links and JSON checked."
        )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
