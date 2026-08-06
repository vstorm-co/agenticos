"""Turning a search box into a `LIKE` predicate.

A search term is text; a `LIKE` operand is a pattern. Interpolating one into
the other hands the caller's punctuation the meaning of the query: `%` and `_`
are wildcards, so `a_b` matched `axb` and a lone `%` matched every row in the
table. Not injection - the term is still bound - but the wrong answer, and a
sequential scan no index can serve (#372).

Escaping the term is only half of it. Postgres recognises no escape character
inside a pattern unless the statement declares one, so the escaped term and the
`ESCAPE` clause have to agree; SQLAlchemy's `autoescape` writes both from one
flag. That flag is the whole concept, which is why it is spelled once here
rather than at each of the three call sites - a search that forgets it still
returns rows, so nothing about the omission is loud.
"""

from sqlalchemy import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute

type SearchableColumn = InstrumentedAttribute[str] | InstrumentedAttribute[str | None]


def contains_ci(column: SearchableColumn, term: str) -> ColumnElement[bool]:
    """Match rows whose `column` contains `term`, ignoring case.

    The only wildcards in the emitted pattern are the two that surround the
    term. Every `%`, `_` and escape character inside `term` itself is matched
    literally, so searching for `100%` finds the row that says `100%` rather
    than all of them.
    """
    return column.icontains(term, autoescape=True)
