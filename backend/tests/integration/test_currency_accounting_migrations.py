"""Currency migrations preserve receipts and refuse lossy historical downgrades."""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models.ingestion_spend import IngestionSpend

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def migration(name: str):
    path = Path(__file__).parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_receipt_capacity_keeps_twelve_places_and_refuses_an_out_of_range_downgrade(
    db: AsyncSession,
) -> None:
    change = migration("0376_monetary_cost_capacity")
    row = IngestionSpend(model="migration-test", cost_usd=Decimal("1.000000000001"))
    db.add(row)
    await db.flush()

    def exercise(session: Session) -> None:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            connection.execute(
                text("ALTER TABLE ingestion_spend ALTER COLUMN cost_usd TYPE numeric(18,12)")
            )
            change.upgrade()
            assert connection.scalar(text("SELECT cost_usd FROM ingestion_spend")) == Decimal(
                "1.000000000001"
            )
            connection.execute(text("UPDATE ingestion_spend SET cost_usd=1000000.000000000001"))
            with pytest.raises(DBAPIError) as refused, connection.begin_nested():
                change.downgrade()
            assert refused.value.orig.sqlstate == "22003"
            assert connection.scalar(text("SELECT cost_usd FROM ingestion_spend")) == Decimal(
                "1000000.000000000001"
            )
            connection.execute(text("UPDATE ingestion_spend SET cost_usd=1.000000000001"))
            change.downgrade()
            assert connection.scalar(text("SELECT cost_usd FROM ingestion_spend")) == Decimal(
                "1.000000000001"
            )
            change.upgrade()

    await db.run_sync(exercise)


async def test_reporting_backfill_snapshots_existing_rates_without_reinterpreting_limit_units(
    db: AsyncSession,
) -> None:
    change = migration("0378_currency_accounting_terms")

    def exercise(session: Session) -> None:
        connection = session.connection()
        # Temporary tables isolate legacy JSON and migration refusal cases without
        # rewriting the current model's schema or any other test's state.
        columns = {
            "organizations": "monthly_budget_usd numeric, proactive_limit_usd numeric, currency text",
            "groups": "monthly_budget_usd numeric",
            "agent_triggers": "monthly_budget_usd numeric",
            "eval_suites": "max_run_usd numeric",
            "improvement_runs": "budget_usd numeric",
            "skill_improvement_runs": "budget_usd numeric",
            "system_agent_profiles": "monthly_budget_usd numeric",
            "phone_endpoints": "daily_budget_usd numeric, price_per_minute_usd numeric",
        }
        for table, fields in columns.items():
            connection.execute(
                text(f"CREATE TEMP TABLE {table} (id integer, {fields}) ON COMMIT DROP")
            )
        connection.execute(
            text("CREATE TEMP TABLE deployment_settings (currency_settings jsonb) ON COMMIT DROP")
        )
        connection.execute(
            text('INSERT INTO deployment_settings VALUES (\'{"rates":{"USD":"1","PLN":"4"}}\')')
        )
        connection.execute(
            text("INSERT INTO organizations VALUES (1,25,3,'PLN'),(2,10,1,'USD'),(3,NULL,2,'EUR')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            change.upgrade()
            rows = connection.execute(
                text("SELECT id, reporting_quote, monetary_terms FROM organizations ORDER BY id")
            ).all()
            assert rows[0].reporting_quote == {"currency": "PLN", "units_per_usd": "4"}
            assert rows[0].monetary_terms["monthly_budget_usd"] == {
                "amount": "25",
                "currency": "USD",
                "units_per_usd": "1",
                "cost_usd": "25",
            }
            assert rows[1].reporting_quote == {"currency": "USD", "units_per_usd": "1"}
            assert rows[2].reporting_quote == {"currency": "EUR", "units_per_usd": None}
            assert "monthly_budget_usd" not in rows[2].monetary_terms
            connection.execute(
                text(
                    'UPDATE organizations SET monetary_terms=\'{"monthly_budget_usd":{"currency":"PLN"}}\' WHERE id=1'
                )
            )
            with pytest.raises(RuntimeError, match="original non-USD"):
                change.downgrade()
            connection.execute(text("UPDATE organizations SET monetary_terms='{}' WHERE id=1"))
            change.downgrade()
            change.upgrade()

    await db.run_sync(exercise)


async def test_routine_budget_precision_survives_upgrade_and_lossy_downgrade_is_refused(
    db: AsyncSession,
) -> None:
    change = migration("0379_trigger_budget_precision")

    def exercise(session: Session) -> None:
        connection = session.connection()
        connection.execute(
            text(
                "CREATE TEMP TABLE agent_triggers (monthly_budget_usd numeric(12,4)) ON COMMIT DROP"
            )
        )
        connection.execute(text("INSERT INTO agent_triggers VALUES (25.0001),(NULL)"))
        with Operations.context(MigrationContext.configure(connection)):
            change.upgrade()
            assert connection.scalar(
                text(
                    "SELECT monthly_budget_usd FROM agent_triggers WHERE monthly_budget_usd IS NOT NULL"
                )
            ) == Decimal("25.000100")
            for value in ("25.000001", "99999999999999999999999999999999.999999"):
                connection.execute(
                    text(
                        "UPDATE agent_triggers SET monthly_budget_usd=:value WHERE monthly_budget_usd IS NOT NULL"
                    ),
                    {"value": Decimal(value)},
                )
                with pytest.raises(RuntimeError, match="four-decimal capacity"):
                    change.downgrade()
                assert connection.scalar(
                    text(
                        "SELECT monthly_budget_usd FROM agent_triggers WHERE monthly_budget_usd IS NOT NULL"
                    )
                ) == Decimal(value)
            connection.execute(
                text(
                    "UPDATE agent_triggers SET monthly_budget_usd=25.0001 WHERE monthly_budget_usd IS NOT NULL"
                )
            )
            change.downgrade()
            assert connection.scalar(
                text(
                    "SELECT monthly_budget_usd FROM agent_triggers WHERE monthly_budget_usd IS NOT NULL"
                )
            ) == Decimal("25.0001")
            change.upgrade()
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM agent_triggers WHERE monthly_budget_usd IS NULL")
                )
                == 1
            )

    await db.run_sync(exercise)
