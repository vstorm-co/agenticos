"""Currency preferences never reinterpret limit declarations or historical USD."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec, BudgetSpec
from app.core.currency import CurrencyAmount, MonetaryTerm
from app.core.exceptions import BadRequestError
from app.repositories.monetary import set_terms
from app.services.monetary import MonetaryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def quote(rate: str | None = "4", currency: str = "PLN") -> SimpleNamespace:
    return SimpleNamespace(
        currency=currency, reporting_units_per_usd=None if rate is None else Decimal(rate)
    )


async def test_legacy_usd_edits_replace_only_the_named_original_terms() -> None:
    service = MonetaryService(AsyncMock())
    old = {"monthly_budget_usd": {"currency": "PLN"}, "other": {"currency": "EUR"}}
    result = await service.terms(
        uuid4(), values={"monthly_budget_usd": Decimal("25")}, inputs={}, previous=old
    )
    assert result["other"] == old["other"]
    assert result["monthly_budget_usd"] == {
        "amount": "25",
        "currency": "USD",
        "units_per_usd": "1",
        "cost_usd": "25",
    }
    assert old["monthly_budget_usd"] == {"currency": "PLN"}
    unchanged = await service.terms(uuid4(), values={}, inputs={}, previous=result)
    assert unchanged == result
    removed = await service.terms(
        uuid4(), values={"monthly_budget_usd": None}, inputs={}, previous=result
    )
    assert "monthly_budget_usd" not in removed and removed["other"] == old["other"]


async def test_a_currency_input_uses_the_authoritative_frozen_quote() -> None:
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ):
        result = await MonetaryService(AsyncMock()).terms(
            uuid4(),
            values={"monthly_budget_usd": Decimal("25")},
            inputs={"monthly_budget_usd": CurrencyAmount(amount="100", currency="PLN")},
        )
    assert result["monthly_budget_usd"] == {
        "amount": "100",
        "currency": "PLN",
        "units_per_usd": "4",
        "cost_usd": "25.000000",
    }


@pytest.mark.parametrize(
    "case",
    ["mismatch", "missing_quote", "other_currency", "unknown_field", "removed", "below_precision"],
)
async def test_unknown_mismatched_or_unsupported_declarations_cannot_write_a_limit(
    case: str,
) -> None:
    inputs = {
        "budget_usd": CurrencyAmount(
            amount="100", currency="EUR" if case == "other_currency" else "PLN"
        )
    }
    values = {"budget_usd": None if case == "removed" else Decimal("25")}
    if case == "unknown_field":
        values = {}
    if case == "mismatch":
        values["budget_usd"] = Decimal("24")
    if case == "below_precision":
        values["budget_usd"] = Decimal(0)
        inputs["budget_usd"] = CurrencyAmount(amount="0.000000001", currency="PLN")
    with (
        patch(
            "app.services.monetary.CurrencyService.context",
            new=AsyncMock(return_value=quote(None if case == "missing_quote" else "4")),
        ),
        pytest.raises(BadRequestError),
    ):
        await MonetaryService(AsyncMock()).terms(uuid4(), values=values, inputs=inputs)


async def test_named_metadata_updates_merge_under_the_resource_lock() -> None:
    resource = SimpleNamespace(monetary_terms={"other": "concurrent-write", "budget_usd": "old"})
    db = AsyncMock()
    await set_terms(
        db,
        resource,
        terms={"budget_usd": "new", "other": "stale"},
        fields=frozenset({"budget_usd"}),
    )
    assert resource.monetary_terms == {"other": "concurrent-write", "budget_usd": "new"}
    db.refresh.assert_awaited_once_with(
        resource, attribute_names=["monetary_terms"], with_for_update=True
    )
    await set_terms(db, resource, terms={}, fields=frozenset({"budget_usd"}))
    assert resource.monetary_terms == {"other": "concurrent-write"}


async def test_agent_budget_terms_survive_a_save_clone_and_portable_json_round_trip() -> None:
    service = MonetaryService(AsyncMock())
    spec = AgentSpec(
        name="Limit",
        budget=BudgetSpec(
            monthly_usd=25,
            monetary_inputs={"monthly_usd": CurrencyAmount(amount=100, currency="PLN")},
        ),
    )
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ):
        saved = await service.agent_budget(uuid4(), spec)
    assert "monetary_inputs" not in saved.model_dump_json()
    assert saved.budget is not None
    assert saved.budget.monetary_terms["monthly_usd"].currency == "PLN"
    copied = AgentSpec.model_validate_json(saved.model_dump_json())
    clone = await service.agent_budget(uuid4(), copied, preserve_terms=True)
    assert clone.budget == saved.budget
    stripped = saved.model_copy(update={"budget": BudgetSpec(monthly_usd=25)})
    kept = await service.agent_budget(uuid4(), stripped, previous=saved)
    assert kept.budget == saved.budget
    edited = saved.model_copy(update={"budget": BudgetSpec(monthly_usd=30)})
    updated = await service.agent_budget(uuid4(), edited, previous=saved)
    assert updated.budget is not None
    assert updated.budget.monetary_terms["monthly_usd"].currency == "USD"


async def test_legacy_agent_budget_serialization_stays_compatible() -> None:
    service = MonetaryService(AsyncMock())
    empty = AgentSpec(name="No limit")
    assert await service.agent_budget(uuid4(), empty) is empty
    legacy = AgentSpec(name="Legacy", budget=BudgetSpec(monthly_usd=25))
    assert (await service.agent_budget(uuid4(), legacy)).model_dump(mode="json")["budget"] == {
        "monthly_usd": 25.0
    }


@pytest.mark.parametrize("amount,usd,rate", [("10", "10", "2"), ("100", "26", "4")])
def test_corrupt_original_terms_are_not_accepted_as_historical_truth(
    amount: str, usd: str, rate: str
) -> None:
    with pytest.raises(ValidationError):
        MonetaryTerm(
            amount=amount,
            currency="USD" if rate == "2" else "PLN",
            units_per_usd=rate,
            cost_usd=usd,
        )


async def test_legacy_float_spec_refuses_an_unrepresentable_declared_limit_at_the_write_boundary() -> (
    None
):
    # The API keeps its existing float field. The separately declared original
    # amount must never be rounded along with it and accepted as a different cap.
    spec = AgentSpec.model_validate(
        {
            "name": "Exact cap",
            "budget": {
                "monthly_usd": "9007199254740993",
                "monetary_inputs": {
                    "monthly_usd": {"amount": "9007199254740993", "currency": "USD"}
                },
            },
        }
    )
    with pytest.raises(BadRequestError) as caught:
        await MonetaryService(AsyncMock()).agent_budget(uuid4(), spec)
    assert caught.value.details["fields"][0]["field"] == "budget.monthly_usd"
    assert "precision" in caught.value.message


async def test_legacy_spec_tiny_usd_terms_are_not_rounded_to_six_places() -> None:
    spec = AgentSpec(
        name="Tiny",
        budget=BudgetSpec(
            monthly_usd=0.00000001,
            monetary_inputs={"monthly_usd": CurrencyAmount(amount="0.00000001", currency="USD")},
        ),
    )
    saved = await MonetaryService(AsyncMock()).agent_budget(uuid4(), spec)
    assert saved.budget is not None
    assert saved.budget.monetary_terms["monthly_usd"].cost_usd == Decimal("0.00000001")
    assert AgentSpec.from_yaml(saved.to_yaml()) == saved


async def test_an_old_infinite_limit_still_loads_but_cannot_be_saved_as_a_new_configuration() -> (
    None
):
    spec = AgentSpec.model_validate({"name": "Old", "budget": {"monthly_usd": "Infinity"}})
    with pytest.raises(BadRequestError, match="finite"):
        await MonetaryService(AsyncMock()).agent_budget(uuid4(), spec)


async def test_cost_capped_nodes_keep_original_terms_without_touching_other_config() -> None:
    service = MonetaryService(AsyncMock())
    config = {
        "model_profile_id": str(uuid4()),
        "prompt": "Keep",
        "max_cost_usd": "0.25",
        "monetary_inputs": {"max_cost_usd": {"amount": "1", "currency": "PLN"}},
    }
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ):
        stored = await service.node_config(uuid4(), config)
    assert "monetary_inputs" not in stored
    assert stored["prompt"] == "Keep"
    assert stored["monetary_terms"]["max_cost_usd"]["currency"] == "PLN"
    changed_prompt = {**stored, "prompt": "Changed"}
    assert (await service.node_config(uuid4(), changed_prompt, previous=stored))[
        "monetary_terms"
    ] == stored["monetary_terms"]
    # A portable original quote remains history after moving to another org.
    assert (await service.node_config(uuid4(), stored, preserve_terms=True))[
        "monetary_terms"
    ] == stored["monetary_terms"]
    changed_cap = await service.node_config(
        uuid4(), {**stored, "max_cost_usd": "0.5"}, previous=stored
    )
    assert changed_cap["monetary_terms"]["max_cost_usd"]["currency"] == "USD"
    removed = await service.node_config(uuid4(), {**stored, "max_cost_usd": None}, previous=stored)
    assert "monetary_terms" not in removed


@pytest.mark.parametrize("value", ["unfinished", "Infinity"])
async def test_unfinished_legacy_node_caps_remain_editable_but_cannot_claim_currency_terms(
    value: str,
) -> None:
    service = MonetaryService(AsyncMock())
    config = {"max_cost_usd": value, "monetary_terms": {"untrusted": True}}
    assert await service.node_config(uuid4(), config) == {"max_cost_usd": value}
    with pytest.raises(BadRequestError):
        await service.node_config(
            uuid4(),
            {**config, "monetary_inputs": {"max_cost_usd": {"amount": "1", "currency": "USD"}}},
        )


async def test_malformed_node_declarations_and_unbalanced_imported_terms_are_refused() -> None:
    service = MonetaryService(AsyncMock())
    with pytest.raises(BadRequestError, match="declaration"):
        await service.node_config(uuid4(), {"max_cost_usd": 1, "monetary_inputs": "not an object"})
    with pytest.raises(BadRequestError, match="Original cap"):
        await service.node_config(
            uuid4(),
            {
                "max_cost_usd": 2,
                "monetary_terms": {
                    "max_cost_usd": {
                        "amount": "1",
                        "currency": "USD",
                        "units_per_usd": "1",
                        "cost_usd": "1",
                    }
                },
            },
            preserve_terms=True,
        )


async def test_cost_criteria_are_currency_aware_thresholds_and_preserve_legacy_latency_checks() -> (
    None
):
    from app.schemas.scoring import CeilingCheck

    cost = CeilingCheck(
        type="max_cost_usd", value=0.25, monetary_input=CurrencyAmount(amount="1", currency="PLN")
    )
    latency = CeilingCheck(type="max_latency_ms", value=100)
    service = MonetaryService(AsyncMock())
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ):
        stored = await service.checks(uuid4(), [cost, latency])
    assert stored[1] is latency
    assert "monetary_input" not in stored[0].model_dump(mode="json")
    assert stored[0].monetary_term.currency == "PLN"
    old_terms = stored[0].monetary_term
    reloaded = CeilingCheck.model_validate(stored[0].model_dump(mode="json"))
    assert (await service.checks(uuid4(), [reloaded], preserve_terms=True))[
        0
    ].monetary_term == old_terms
    no_descriptor = CeilingCheck(type="max_cost_usd", value=0.25)
    assert (await service.checks(uuid4(), [no_descriptor], previous=stored))[
        0
    ].monetary_term == old_terms
    changed = CeilingCheck(type="max_cost_usd", value=0.5)
    assert (await service.checks(uuid4(), [changed], previous=stored))[
        0
    ].monetary_term.currency == "USD"
    legacy = [CeilingCheck(type="max_cost_usd", value=0.25)]
    assert (await service.checks(uuid4(), legacy, previous=legacy))[0].monetary_term is None
    with pytest.raises(BadRequestError, match="Original criterion"):
        await service.checks(
            uuid4(), [changed.model_copy(update={"monetary_term": old_terms})], preserve_terms=True
        )
    with pytest.raises(ValidationError, match="monetary threshold"):
        CeilingCheck(
            type="max_latency_ms",
            value=100,
            monetary_input=CurrencyAmount(amount=1, currency="USD"),
        )


def test_original_currency_metadata_does_not_change_the_operational_grading_hash() -> None:
    from app.schemas.scoring import CeilingCheck, ChecksScorer, DatasetScoring
    from app.services.eval_run import scoring_hash

    plain = DatasetScoring(
        checks=ChecksScorer(defaults=[CeilingCheck(type="max_cost_usd", value=0.25)])
    )
    described = plain.model_copy(
        update={
            "checks": plain.checks.model_copy(
                update={
                    "defaults": [
                        CeilingCheck(
                            type="max_cost_usd",
                            value=0.25,
                            monetary_term=MonetaryTerm(
                                amount=1, currency="PLN", units_per_usd=4, cost_usd="0.25"
                            ),
                        )
                    ]
                }
            )
        }
    )
    assert scoring_hash(described) == scoring_hash(plain)


async def test_dataset_request_raw_checks_reach_the_same_normalization_as_typed_defaults() -> None:
    from app.schemas.dataset import DatasetCaseContent
    from app.schemas.scoring import CaseCheck

    request = DatasetCaseContent(
        input="Question",
        checks=[
            {
                "type": "max_cost_usd",
                "value": 0.25,
                "monetary_input": {"amount": "1", "currency": "PLN"},
            }
        ],
    )
    assert type(request.checks[0]) is CaseCheck
    service = MonetaryService(AsyncMock())
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ):
        normalized = await service.checks(uuid4(), request.checks)
    assert type(normalized[0]) is CaseCheck
    raw = normalized[0].model_dump(mode="json")
    assert "monetary_input" not in raw
    assert raw["monetary_term"]["currency"] == "PLN"
    assert raw["value"] == 0.25
    assert "monetary_input" in request.checks[0].model_dump(mode="json")


@pytest.mark.parametrize("root", ["", "budget"])
async def test_nonfinite_accounting_values_are_controlled_field_refusals(root: str) -> None:
    with pytest.raises(BadRequestError, match="finite") as refused:
        await MonetaryService(AsyncMock()).terms(
            uuid4(), values={"limit": Decimal("Infinity")}, inputs={}, field_root=root
        )
    assert refused.value.details["fields"][0]["field"] == (f"{root}.limit" if root else "limit")


@pytest.mark.parametrize("limit", [None, 2])
async def test_imported_agent_terms_cannot_claim_a_different_accounting_limit(
    limit: int | None,
) -> None:
    spec = AgentSpec(
        name="Import",
        budget=BudgetSpec(
            monthly_usd=limit,
            monetary_terms={
                "monthly_usd": MonetaryTerm(amount=1, currency="USD", units_per_usd=1, cost_usd=1)
            },
        ),
    )
    with pytest.raises(BadRequestError, match="imported budget terms"):
        await MonetaryService(AsyncMock()).agent_budget(uuid4(), spec, preserve_terms=True)


async def test_invalid_original_node_metadata_and_old_raw_check_shapes_do_not_become_500s() -> None:
    from app.schemas.scoring import CaseCheck

    service = MonetaryService(AsyncMock())
    with pytest.raises(BadRequestError, match="original cap terms"):
        await service.node_config(
            uuid4(), {"max_cost_usd": 1, "monetary_terms": "invalid"}, preserve_terms=True
        )
    with pytest.raises(BadRequestError, match="monetary criterion"):
        await service.checks(uuid4(), [CaseCheck(type="max_cost_usd", value="unfinished")])


def test_cost_thresholds_compare_accounting_decimals_without_float_rounding() -> None:
    from app.services.scorers import ScoredAnswer, run_checks

    results, _ = run_checks(
        [{"type": "max_cost_usd", "value": 9007199254740992}],
        ScoredAnswer(text="", cost_usd=Decimal("9007199254740993.000001")),
        required=True,
    )
    assert results[0].score == 0
    assert results[0].cost_observed_usd == Decimal("9007199254740993.000001")
    assert results[0].cost_limit_usd == Decimal("9007199254740992")
    assert "9007199254740993.0000" in results[0].reason


def test_unmeasured_cost_thresholds_remain_unknown_and_nonfinite_legacy_thresholds_are_errors() -> (
    None
):
    from app.services.scorers import ScoredAnswer, run_checks

    results, _ = run_checks(
        [{"type": "max_cost_usd", "value": 1}], ScoredAnswer(text=""), required=True
    )
    assert results[0].status == "error" and results[0].reason_code == "not_measured"
    assert results[0].cost_limit_usd == Decimal(1)
    assert "cost_observed_usd" not in results[0].model_dump(mode="json")
    invalid, _ = run_checks(
        [{"type": "max_cost_usd", "value": float("inf")}],
        ScoredAnswer(text="", cost_usd=Decimal(1)),
        required=True,
    )
    assert invalid[0].status == "error" and invalid[0].reason_code == "invalid_check"


async def test_one_write_reuses_its_quote_but_another_write_reads_fresh_terms() -> None:
    organization_id = uuid4()
    with patch(
        "app.services.monetary.CurrencyService.context", new=AsyncMock(return_value=quote())
    ) as context:
        service = MonetaryService(AsyncMock())
        for field in ("monthly_budget_usd", "max_run_usd"):
            await service.terms(
                organization_id,
                values={field: Decimal("25")},
                inputs={field: CurrencyAmount(amount="100", currency="PLN")},
            )
        context.assert_awaited_once_with(organization_id)
        await MonetaryService(AsyncMock()).terms(
            organization_id,
            values={"max_run_usd": Decimal("25")},
            inputs={"max_run_usd": CurrencyAmount(amount="100", currency="PLN")},
        )
        assert context.await_count == 2


@pytest.mark.parametrize("raw", [False, True])
async def test_removing_or_reordering_checks_preserves_the_cost_criterion_origin(raw: bool) -> None:
    from app.schemas.scoring import CaseCheck, CeilingCheck, TextCheck

    term = MonetaryTerm(amount="100", currency="PLN", units_per_usd="4", cost_usd="25")
    cost = CeilingCheck(type="max_cost_usd", value=25, monetary_term=term)
    text = TextCheck(type="contains", value="answer")
    service = MonetaryService(AsyncMock())
    if raw:
        old = [CaseCheck.model_validate(item.model_dump(mode="json")) for item in (text, cost)]
        checks = [CaseCheck.model_validate(cost.model_dump(mode="json"))]
        result = await service.checks(uuid4(), checks, previous=old)
    else:
        result = await service.checks(uuid4(), [cost, text], previous=[text, cost])
    assert result[0].model_dump(mode="json")["monetary_term"] == term.model_dump(mode="json")


async def test_duplicate_cost_thresholds_keep_their_own_declared_origins_when_reordered() -> None:
    from app.schemas.scoring import CeilingCheck

    pln = CeilingCheck(
        type="max_cost_usd",
        value=25,
        monetary_term=MonetaryTerm(
            amount="100",
            currency="PLN",
            units_per_usd="4",
            cost_usd="25",
        ),
    )
    eur = CeilingCheck(
        type="max_cost_usd",
        value=25,
        monetary_term=MonetaryTerm(
            amount="20",
            currency="EUR",
            units_per_usd="0.8",
            cost_usd="25",
        ),
    )
    result = await MonetaryService(AsyncMock()).checks(uuid4(), [eur, pln], previous=[pln, eur])
    assert [item.monetary_term for item in result] == [eur.monetary_term, pln.monetary_term]


async def test_changing_the_criterion_family_does_not_inherit_another_origin() -> None:
    from app.schemas.scoring import CeilingCheck

    old = CeilingCheck(
        type="max_cost_usd",
        value=25,
        family="billing",
        monetary_term=MonetaryTerm(
            amount="100",
            currency="PLN",
            units_per_usd="4",
            cost_usd="25",
        ),
    )
    new = old.model_copy(update={"family": "customer_total"})
    result = await MonetaryService(AsyncMock()).checks(uuid4(), [new], previous=[old])
    assert result[0].monetary_term is not None
    assert result[0].monetary_term.currency == "USD"


@pytest.mark.parametrize("value", ["25.000001", "99999999999999999999999999999999.999999"])
def test_routine_budget_write_schemas_preserve_the_six_decimal_storage_contract(value: str) -> None:
    from app.schemas.agent_trigger import TriggerCreate, TriggerUpdate

    create = TriggerCreate(
        prompt="Read the project",
        schedule_kind="cron",
        cron_expression="0 9 * * *",
        monthly_budget_usd=value,
    )
    update = TriggerUpdate(monthly_budget_usd=value)
    assert create.monthly_budget_usd == update.monthly_budget_usd == Decimal(value)


@pytest.mark.parametrize(
    "value", ["25.0000001", "100000000000000000000000000000000", "NaN", "Infinity"]
)
def test_routine_budget_write_schemas_refuse_rounding_and_overflow_before_storage(
    value: str,
) -> None:
    from app.schemas.agent_trigger import TriggerCreate, TriggerUpdate

    for schema, fields in [
        (TriggerUpdate, {}),
        (
            TriggerCreate,
            {"prompt": "Read the project", "schedule_kind": "cron", "cron_expression": "0 9 * * *"},
        ),
    ]:
        with pytest.raises(ValidationError):
            schema.model_validate({**fields, "monthly_budget_usd": value})
