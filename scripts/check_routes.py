#!/usr/bin/env python3
"""Keep `app/api/routes/**` to routers, not helpers.

A route module is the HTTP layer: request in, delegate to a service, response
out. A plain helper that lands here - a parser, a loader, a formatter - is
business logic in the one place the architecture says holds none, and it gets
there quietly because nothing complains. This is that complaint.

A module-level function in a route file is allowed only when it is one of:

- a **route handler** - decorated `@router.get(...)`, `@router.post(...)` and so
  on (any `<router>.<http-method>` decorator);
- a **router factory** - annotated `-> APIRouter`, the pattern that builds a set
  of endpoints from one definition (e.g. `build_sharing_router`);
- **declared on purpose** with `# routes-helper: <reason>` on the `def` line or
  the line above it. The reason is required, the same bargain as `i18n-exempt`
  and `ty: ignore`: a helper may live here, but only as a conscious choice with
  a note saying why - not by accident.

Everything else is reported. The fix is almost always to move it: a loader or a
validator belongs in a service, a dependency in `api/deps.py`. If it genuinely
belongs at the HTTP layer, mark it and say so.

Usage::

    python scripts/check_routes.py            # report, exit 1 if any found

Exits 1 when an undeclared helper is found, 0 when clean.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# `websocket` and `api_route` are FastAPI route decorators too; a handler wears
# one of these as `<router>.<name>(...)`.
HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace", "websocket", "api_route"}
)

MARKER = "# routes-helper:"

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "backend" / "app" / "api" / "routes"


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(call, ast.Attribute) and call.attr in HTTP_METHODS:
            return True
    return False


def _is_router_factory(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    ret = node.returns
    if isinstance(ret, ast.Name):
        return ret.id == "APIRouter"
    if isinstance(ret, ast.Attribute):
        return ret.attr == "APIRouter"
    return False


def _reason_after(line: str) -> bool:
    idx = line.find(MARKER)
    return idx != -1 and bool(line[idx + len(MARKER) :].strip())


def _has_marker(lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # The `def` line itself (a trailing marker), or anywhere in the contiguous
    # block of comment lines directly above it - so a multi-line note carries.
    if 1 <= node.lineno <= len(lines) and _reason_after(lines[node.lineno - 1]):
        return True
    i = node.lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#"):
        if _reason_after(lines[i]):
            return True
        i -= 1
    return False


def _findings(path: Path) -> list[tuple[int, str]]:
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source, str(path))
    out: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _is_route_handler(node) or _is_router_factory(node) or _has_marker(lines, node):
            continue
        out.append((node.lineno, node.name))
    return out


def main() -> int:
    if not ROUTES_DIR.is_dir():
        print(f"routes directory not found: {ROUTES_DIR}", file=sys.stderr)
        return 1
    found = False
    for path in sorted(ROUTES_DIR.rglob("*.py")):
        for lineno, name in _findings(path):
            found = True
            rel = path.relative_to(REPO_ROOT)
            print(
                f"{rel}:{lineno}: helper '{name}' in a route module. Move it to a "
                f"service or api/deps.py, or mark it `{MARKER} <reason>`."
            )
    if found:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
