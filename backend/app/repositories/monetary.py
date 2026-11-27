"""Persist original terms on the same already-authorized resource transaction."""

from typing import Protocol

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession


class HasMonetaryTerms(Protocol):
    monetary_terms: dict[str, JsonValue]


async def set_terms(
    db: AsyncSession,
    resource: HasMonetaryTerms,
    *,
    terms: dict[str, JsonValue],
    fields: frozenset[str],
) -> None:
    await db.refresh(resource, attribute_names=["monetary_terms"], with_for_update=True)
    merged = dict(resource.monetary_terms)
    for field in fields:
        if field in terms:
            merged[field] = terms[field]
        else:
            merged.pop(field, None)
    resource.monetary_terms = merged
    await db.flush()
