"""Validate limit declarations while keeping the existing USD enforcement paths."""

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import CurrencyAmount, MonetaryTerm, ReportingQuote
from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems, refused_field
from app.services.currency import CurrencyService

if TYPE_CHECKING:
    from app.agents.spec import AgentSpec
    from app.schemas.scoring import CaseCheck, Check


class MonetaryService:
    """Normalize only authorized monetary writes; no query mutates financial terms."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._quotes: dict[UUID, ReportingQuote] = {}

    async def _reporting_quote(self, organization_id: UUID) -> ReportingQuote:
        """One authoritative snapshot for all fields in this write operation."""
        if organization_id not in self._quotes:
            context = await CurrencyService(self.db).context(organization_id)
            self._quotes[organization_id] = ReportingQuote(
                currency=context.currency, units_per_usd=context.reporting_units_per_usd
            )
        return self._quotes[organization_id]

    async def terms(
        self,
        organization_id: UUID,
        *,
        values: Mapping[str, Decimal | float | int | None],
        inputs: Mapping[str, CurrencyAmount],
        previous: Mapping[str, JsonValue] | None = None,
        field_root: str = "",
    ) -> dict[str, JsonValue]:
        """Verify declarations and retain original terms for the named fields.

        Callers establish write authority and pass only monetary fields the
        request names. Existing clients supplying USD alone remain valid; an
        explicit USD edit replaces only that field's original terms.
        """
        if inputs.keys() - values.keys():
            raise BadRequestError(message="A monetary input must name a supplied monetary field")
        quote = ReportingQuote()
        if any(value.currency != "USD" for value in inputs.values()):
            quote = await self._reporting_quote(organization_id)
        result = dict(previous or {})
        for field, canonical in values.items():
            if canonical is None:
                if field in inputs:
                    raise BadRequestError(
                        message="A removed spending limit cannot declare an amount"
                    )
                result.pop(field, None)
                continue
            usd = Decimal(str(canonical))
            if not usd.is_finite():
                raise refused_field(
                    f"{field_root}.{field}" if field_root else field,
                    "Enter a finite accounting limit",
                )
            if usd < 0:
                raise refused_field(
                    f"{field_root}.{field}" if field_root else field,
                    "Enter a non-negative accounting limit",
                )
            declared = inputs.get(field)
            if declared is None:
                result[field] = MonetaryTerm(
                    amount=usd, currency="USD", units_per_usd=Decimal(1), cost_usd=usd
                ).model_dump(mode="json")
                continue
            rate = Decimal(1)
            if declared.currency != "USD":
                if declared.currency != quote.currency or quote.units_per_usd is None:
                    raise BadRequestError(
                        message="Choose the organization reporting currency with a known quote, or USD"
                    )
                rate = quote.units_per_usd
            with localcontext() as arithmetic:
                arithmetic.prec = 128
                converted = (
                    declared.amount
                    if declared.currency == "USD"
                    else (declared.amount / rate).quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                    )
                )
            if declared.amount > 0 and converted == 0:
                raise BadRequestError(
                    message="The amount is below accounting precision; choose a larger limit"
                )
            if converted != usd:
                raise refused_field(
                    f"{field_root}.{field}" if field_root else field,
                    "The declared amount does not match its exact accounting USD value; check the quote and supported precision",
                )
            result[field] = MonetaryTerm(
                amount=declared.amount,
                currency=declared.currency,
                units_per_usd=rate,
                cost_usd=converted,
            ).model_dump(mode="json")
        return result

    async def agent_budget(
        self,
        organization_id: UUID,
        spec: AgentSpec,
        *,
        previous: AgentSpec | None = None,
        preserve_terms: bool = False,
    ) -> AgentSpec:
        """Keep a nested budget's original terms through saves, clones and imports.

        Imported terms are descriptive history, validated against accounting USD;
        only an explicit new monetary input selects this deployment's live quote.
        Neither history nor a client-provided USD equivalent changes enforcement.
        """
        budget = spec.budget
        if budget is None:
            return spec
        old = previous.budget if previous is not None else None
        retained = (
            budget.monetary_terms
            if preserve_terms
            else old.monetary_terms
            if old is not None
            else {}
        )
        keep_history = preserve_terms or old is None or old.monthly_usd == budget.monthly_usd
        current = budget.monthly_usd
        if current is not None and not Decimal(str(current)).is_finite():
            raise refused_field("budget.monthly_usd", "Enter a finite spending limit")
        if not budget.monetary_inputs and retained and keep_history:
            term = retained["monthly_usd"]
            if current is None or term.cost_usd != Decimal(str(current)):
                raise BadRequestError(
                    message="The imported budget terms do not match its accounting limit"
                )
            terms = {key: value.model_dump(mode="json") for key, value in retained.items()}
        elif not budget.monetary_inputs and keep_history:
            # Legacy USD specs need no serialized metadata merely for being read or copied.
            return spec.model_copy(
                update={"budget": budget.model_copy(update={"monetary_terms": {}})}
            )
        else:
            terms = await self.terms(
                organization_id,
                values={"monthly_usd": current},
                inputs=budget.monetary_inputs,
                field_root="budget",
            )
        return spec.model_copy(
            update={
                "budget": budget.model_copy(
                    update={
                        "monetary_terms": {
                            "monthly_usd": MonetaryTerm.model_validate(terms["monthly_usd"])
                        }
                        if terms
                        else {},
                        "monetary_inputs": {},
                    }
                )
            }
        )

    async def node_config(
        self,
        organization_id: UUID,
        config: dict[str, JsonValue],
        *,
        previous: dict[str, JsonValue] | None = None,
        preserve_terms: bool = False,
    ) -> dict[str, JsonValue]:
        """Normalize a known cost-capped node, including a bound Python action.

        Unfinished legacy draft values remain editable. Only a valid declared
        cap can create original terms, and declarations never survive storage.
        """
        result = dict(config)
        try:
            inputs = TypeAdapter(dict[str, CurrencyAmount]).validate_python(
                result.pop("monetary_inputs", {})
            )
        except ValidationError as error:
            raise BadRequestError(
                message="Invalid currency declaration",
                details={"fields": field_problems(error.errors(), root="monetary_inputs")},
            ) from None
        raw = result.get("max_cost_usd")
        try:
            parsed = TypeAdapter(float | None).validate_python(raw)
            value = None if parsed is None else Decimal(str(parsed))
        except ValidationError:
            if inputs:
                raise refused_field("max_cost_usd", "Enter a valid accounting limit") from None
            result.pop("monetary_terms", None)
            return result
        if value is not None and not value.is_finite():
            if inputs:
                raise refused_field("max_cost_usd", "Enter a finite accounting limit")
            result.pop("monetary_terms", None)
            return result
        retained: dict[str, JsonValue] = {}
        original = config if preserve_terms else previous
        if original is not None and original.get("max_cost_usd") == raw:
            try:
                typed = TypeAdapter(dict[str, MonetaryTerm]).validate_python(
                    original.get("monetary_terms", {})
                )
            except ValidationError as error:
                raise BadRequestError(
                    message="Invalid original cap terms",
                    details={"fields": field_problems(error.errors(), root="monetary_terms")},
                ) from None
            for field, term in typed.items():
                if field != "max_cost_usd" or value is None or term.cost_usd != value:
                    raise refused_field(
                        "max_cost_usd", "Original cap terms do not match the accounting limit"
                    )
                retained[field] = term.model_dump(mode="json")
        if not inputs:
            terms = retained
        else:
            terms = await self.terms(organization_id, values={"max_cost_usd": value}, inputs=inputs)
        if terms:
            result["monetary_terms"] = terms
        else:
            result.pop("monetary_terms", None)
        return result

    async def checks[T: CaseCheck | Check](
        self,
        organization_id: UUID,
        checks: Sequence[T],
        *,
        previous: Sequence[T] | None = None,
        preserve_terms: bool = False,
    ) -> list[T]:
        """Normalize both stored raw checks and typed scoring defaults, preserving their shape."""
        from app.schemas.scoring import CHECK, CeilingCheck

        result: list[T] = []
        unmatched = list(previous or ())
        for index, check in enumerate(checks):
            if check.type != "max_cost_usd":
                result.append(check)
                continue
            try:
                priced = CHECK.validate_python(check.model_dump(by_alias=True))
                assert isinstance(priced, CeilingCheck)
                if not Decimal(str(priced.value)).is_finite():
                    raise refused_field(f"checks.{index}.value", "Enter a finite accounting limit")
                candidates = [
                    (position, CHECK.validate_python(candidate.model_dump(by_alias=True)))
                    for position, candidate in enumerate(unmatched)
                    if candidate.type == "max_cost_usd"
                ]
                identity = priced.model_dump(exclude={"monetary_input", "monetary_term"})
                matching = [
                    (position, candidate)
                    for position, candidate in candidates
                    if isinstance(candidate, CeilingCheck)
                    and candidate.model_dump(exclude={"monetary_input", "monetary_term"})
                    == identity
                ]
                selected = next(
                    (item for item in matching if item[1].monetary_term == priced.monetary_term),
                    matching[0] if matching else None,
                )
                old = selected[1] if selected is not None else None
                if selected is not None:
                    unmatched.pop(selected[0])
            except ValidationError as error:
                raise BadRequestError(
                    message="Invalid monetary criterion",
                    details={"fields": field_problems(error.errors(), root=f"checks.{index}")},
                ) from None
            assert isinstance(priced, CeilingCheck)
            retained = (
                old.monetary_term
                if isinstance(old, CeilingCheck) and old.value == priced.value
                else priced.monetary_term
                if preserve_terms
                else None
            )
            if priced.monetary_input is None and retained is not None:
                if retained.cost_usd != Decimal(str(priced.value)):
                    raise refused_field(
                        f"checks.{index}.value",
                        "Original criterion terms do not match its USD threshold",
                    )
                term = retained
            elif priced.monetary_input is None:
                term = None
            else:
                terms = await self.terms(
                    organization_id,
                    values={"value": priced.value},
                    inputs={"value": priced.monetary_input}
                    if priced.monetary_input is not None
                    else {},
                    field_root=f"checks.{index}",
                )
                term = MonetaryTerm.model_validate(terms["value"])
            raw = check.model_dump(mode="json", by_alias=True)
            raw.pop("monetary_input", None)
            if term is None:
                raw.pop("monetary_term", None)
            else:
                raw["monetary_term"] = term.model_dump(mode="json")
            result.append(type(check).model_validate(raw))
        return result
