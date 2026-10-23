"""Formula columns: a small expression over the other columns of the same record.

`{Price} * {Quantity}`, `IF({Total} > 100, "large", "small")`,
`ROUND({Total} / {Count}, 2)`, `DAYS({Due}, TODAY())`. A column is named by its
label in braces; renaming it rewrites the formulas that name it
(:func:`rename_references`), so a formula never silently stops reading one.

The expression is parsed by Python's own parser and then *interpreted*, node by
node, against a closed list of what may appear - numbers, text, `true`/`false`,
the column references, `+ - * / %`, comparisons, `and`/`or`/`not` and the
functions in :data:`FUNCTIONS`. Nothing is evaluated by Python: no names, no
attributes, no subscripts, no lambdas, no power operator (`9 ** 9 ** 9` is not a
question a cell gets to ask). Text is joined only by `CONCAT`, never by `*`, so
no formula builds a string larger than its inputs allow.

A value that cannot be worked out - a division by zero, a number added to text,
a reference to an empty cell in arithmetic - is no value rather than an error:
one record's odd data leaves its cell empty and the rest of the table reads.
"""

from __future__ import annotations

import ast
import io
import math
import re
import tokenize
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from app.schemas.virtual_table import CellValue, ColumnDef

MAX_FORMULA = 1_000
MAX_DEPTH = 30
MAX_TEXT = 10_000

_REFERENCE = re.compile(r"\{([^{}]+)\}")
_PLACEHOLDER = "__column_{}"

Value = CellValue | list[CellValue]


class FormulaProblem(ValueError):
    """A formula that cannot be one. The message is written for its author."""


def _number(value: object) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("not a number")
    return value


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value)
    return str(value)


def _day(value: object) -> date:
    if not isinstance(value, str):
        raise TypeError("not a date")
    return date.fromisoformat(value[:10])


def _round(*args: Value) -> Value:
    places = int(_number(args[1])) if len(args) > 1 else 0
    return round(_number(args[0]), max(0, min(places, 10)))


def _concat(*args: Value) -> Value:
    joined = "".join(_text(arg) for arg in args)
    if len(joined) > MAX_TEXT:
        raise ArithmeticError("text too long")
    return joined


def _days(*args: Value) -> Value:
    if len(args) != 2:
        raise ArithmeticError("DAYS takes two dates")
    return (_day(args[0]) - _day(args[1])).days


FUNCTIONS: dict[str, Callable[..., Value]] = {
    # Named here so the formula checker knows it; `_evaluate` works it out itself, so
    # that only the chosen branch is evaluated.
    "IF": lambda *_: None,
    "ROUND": _round,
    "ABS": lambda value: abs(_number(value)),
    "MIN": lambda *values: min(_number(value) for value in values),
    "MAX": lambda *values: max(_number(value) for value in values),
    "CONCAT": _concat,
    "LEN": lambda value: len(_text(value)),
    "UPPER": lambda value: _text(value).upper(),
    "LOWER": lambda value: _text(value).lower(),
    "DAYS": _days,
    "TODAY": lambda: datetime.now(UTC).date().isoformat(),
}
"""Every function a formula may call, by its name in capitals."""

_ARITHMETIC: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}


def _less(a: object, b: object) -> bool:
    """`a < b` for two texts or two numbers - and no other pair, which has no order."""
    if isinstance(a, str) and isinstance(b, str):
        return a < b
    return _number(a) < _number(b)


_COMPARISONS: dict[type[ast.cmpop], Callable[[object, object], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: _less,
    ast.LtE: lambda a, b: not _less(b, a),
    ast.Gt: lambda a, b: _less(b, a),
    ast.GtE: lambda a, b: not _less(a, b),
}
_WORDS = {"TRUE": "True", "FALSE": "False", "AND": "and", "OR": "or", "NOT": "not"}
"""A spreadsheet's spelling of what Python spells otherwise, matched ignoring case."""


def references(formula: str) -> list[str]:
    """The labels a formula names, in the order it names them, each once."""
    return list(dict.fromkeys(match.strip() for match in _REFERENCE.findall(formula)))


def rename_references(formula: str, renamed: Mapping[str, str]) -> str:
    """`formula` with each `{old label}` it names written `{new label}`."""

    def replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        return "{" + renamed.get(label, label) + "}"

    return _REFERENCE.sub(replace, formula)


def resolve_references(formula: str, ids: Mapping[str, UUID]) -> tuple[str | UUID, ...]:
    """`formula` split into its text and its references, alternately, starting with text.

    Each reference is the id `ids` gives its label, or the label itself where it names
    none. Two formulas that resolve alike read the same columns the same way, whatever
    the columns are called.
    """
    parts = _REFERENCE.split(formula)
    return tuple(
        part if index % 2 == 0 else ids.get(part.strip(), part.strip())
        for index, part in enumerate(parts)
    )


def _parse(formula: str, labels: Sequence[str]) -> ast.Expression:
    """The expression's tree, with each reference a placeholder name in `labels` order."""
    index = {label: position for position, label in enumerate(labels)}

    def placeholder(match: re.Match[str]) -> str:
        return _PLACEHOLDER.format(index[match.group(1).strip()])

    source = _REFERENCE.sub(placeholder, formula).strip()
    try:
        return ast.parse(_spreadsheet_words(source), mode="eval")
    except (SyntaxError, tokenize.TokenError):
        raise FormulaProblem("The formula is not written correctly") from None


def _spreadsheet_words(source: str) -> str:
    """`source` with TRUE, AND, `=`, `<>` and the like in Python's spelling - outside text
    only, so `"R AND D"` stays as it was written."""
    tokens: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        word = token.string.upper()
        if token.type == tokenize.NAME and word in _WORDS:
            tokens.append((token.type, _WORDS[word]))
        elif token.type == tokenize.NAME and word in FUNCTIONS:
            # Named as a person types it: `if(` is Python's keyword, `IF(` a call.
            tokens.append((token.type, word))
        elif token.type == tokenize.OP and token.string in ("<>", "="):
            tokens.append((token.type, "!=" if token.string == "<>" else "=="))
        else:
            tokens.append((token.type, token.string))
    return tokenize.untokenize(tokens)


def _check(node: ast.AST, depth: int = 0) -> None:
    """Refuse anything a formula may not contain."""
    if depth > MAX_DEPTH:
        raise FormulaProblem("The formula nests too deeply")
    if isinstance(node, ast.Expression):
        _check(node.body, depth + 1)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, int | float | str | bool):
            raise FormulaProblem("A formula holds numbers, text and true or false")
    elif isinstance(node, ast.Name):
        if not node.id.startswith("__column_"):
            raise FormulaProblem(
                f"{node.id} means nothing here: name a column in braces, as {{{node.id}}}"
            )
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _ARITHMETIC:
            raise FormulaProblem("A formula calculates with + - * / and % only")
        _check(node.left, depth + 1)
        _check(node.right, depth + 1)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub | ast.UAdd | ast.Not):
            raise FormulaProblem("That operator is not one a formula uses")
        _check(node.operand, depth + 1)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            _check(value, depth + 1)
    elif isinstance(node, ast.Compare):
        if any(type(op) not in _COMPARISONS for op in node.ops):
            raise FormulaProblem("A formula compares with = <> < <= > >= only")
        for part in (node.left, *node.comparators):
            _check(part, depth + 1)
    elif isinstance(node, ast.Call):
        name = node.func.id.upper() if isinstance(node.func, ast.Name) else None
        if name is None or name not in FUNCTIONS or node.keywords:
            known = ", ".join(sorted(FUNCTIONS))
            raise FormulaProblem(f"A formula calls only these functions: {known}")
        for arg in node.args:
            _check(arg, depth + 1)
    else:
        raise FormulaProblem("That is not something a formula can contain")


def check_formula(formula: str, column: ColumnDef, columns: Sequence[ColumnDef]) -> None:
    """Whether `formula` is one `column` may hold: it parses, contains nothing it
    may not, and names live columns of the table other than formulas.

    Raises:
        FormulaProblem: Saying what is wrong, for the person writing it.
    """
    if not formula.strip():
        raise FormulaProblem("A formula column needs a formula")
    if len(formula) > MAX_FORMULA:
        raise FormulaProblem(f"A formula is at most {MAX_FORMULA} characters")
    live = {c.label: c for c in columns if not c.archived and c.id != column.id}
    named = references(formula)
    for label in named:
        target = live.get(label)
        if target is None:
            raise FormulaProblem(f"{{{label}}} is not a live column of this table")
        if target.type in ("formula", "link"):
            raise FormulaProblem(
                f"{{{label}}} is a {target.type} column; a formula reads columns holding values"
            )
    _check(_parse(formula, named))


def _evaluate(node: ast.AST, values: Sequence[Value]) -> Value:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Constant):
        constant = node.value
        if isinstance(constant, int | float | str | bool):  # what `_check` let through
            return constant
        raise TypeError("not a value a formula holds")
    if isinstance(node, ast.Name):
        return values[int(node.id.removeprefix("__column_"))]
    if isinstance(node, ast.BinOp):
        operate = _ARITHMETIC[type(node.op)]
        return operate(
            _number(_evaluate(node.left, values)), _number(_evaluate(node.right, values))
        )
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values)
        if isinstance(node.op, ast.Not):
            return not operand
        return -_number(operand) if isinstance(node.op, ast.USub) else _number(operand)
    if isinstance(node, ast.BoolOp):
        # Short-circuits, so `AND({D} <> 0, 10 / {D} > 1)` never divides by zero.
        stops_on = not isinstance(node.op, ast.And)
        for value in node.values:
            if bool(_evaluate(value, values)) is stops_on:
                return stops_on
        return not stops_on
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, values)
            if not _COMPARISONS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id.upper() == "IF":
            # Only the chosen branch is worked out, so `IF({D} = 0, 0, 10 / {D})` is 0.
            if len(node.args) != 3:
                raise ArithmeticError("IF takes a condition and two values")
            condition, then, otherwise = node.args
            return _evaluate(then if _evaluate(condition, values) else otherwise, values)
        args = [_evaluate(arg, values) for arg in node.args]
        return FUNCTIONS[node.func.id.upper()](*args)
    raise ArithmeticError("unreachable for a checked formula")


def _as_read(column: ColumnDef, value: Value) -> Value:
    """A cell as a formula reads it: a choice by its label, as a person wrote it."""
    labels = {str(option.id): option.label for option in column.options}
    if isinstance(value, str) and labels:
        return labels.get(value, value)
    if isinstance(value, list) and labels:
        return [labels.get(str(item), item) for item in value]
    return value


def work_out(formula: str, columns: Sequence[ColumnDef], record: Mapping[str, Value]) -> Value:
    """A checked formula's value for one record, or `None` when it has none."""
    by_label = {column.label: column for column in columns if not column.archived}
    named = references(formula)
    if any(label not in by_label for label in named):
        return None
    tree = _parse(formula, named)
    values = [_as_read(by_label[label], record.get(str(by_label[label].id))) for label in named]
    try:
        result = _evaluate(tree, values)
    except (ArithmeticError, TypeError, ValueError, IndexError):
        return None
    if isinstance(result, float):
        if not math.isfinite(result):
            return None
        # Binary fractions: 0.1 + 0.2 reads 0.3, as a person expects of a sum, and
        # 2.5 * 4 reads 10 rather than 10.0.
        rounded = round(result, 10)
        return int(rounded) if rounded.is_integer() else rounded
    return result
