"""How long data lives here, and the sweep that makes that true (#1420).

Nothing was deleted on a schedule before this, which is a data-protection
problem in one direction and, for audit, a compliance problem in the other. Two
standards pull opposite ways: HIPAA wants an audit record kept six years, GDPR
wants everything else minimised.

Three things are worth testing and they are different questions. The precedence
is arithmetic and is tested as arithmetic. The sweep is a hard delete, so what is
asserted is what *left* and what survived it - particularly the spend, because a
month's bill is a sum over exactly the rows being removed. And the refusals: a
period below the audit floor, and a member without `org:settings`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.retention import (
    DEFAULT_AUDIT_FLOOR_DAYS,
    RETENTION_CLASSES,
    effective_policy,
    known_periods,
    policy_conflicts,
)
from app.schemas.deployment_settings import DeploymentSettingsUpdate
from app.schemas.retention import RetentionUpdate
from app.services.retention import BATCH, MAX_BATCHES, RetentionService

pytestmark = pytest.mark.anyio

MODULE = "app.services.retention"
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class TestWhichNumberWins:
    """Three layers, and audit running the other way round."""

    def test_an_organization_that_has_said_nothing_gets_the_deployments_default(self) -> None:
        policy = effective_policy(
            organization=None,
            defaults={"conversations": 90},
            ceilings=None,
            audit_floor_days=None,
        )

        assert policy["conversations"] == 90

    def test_an_organization_that_has_said_something_gets_it(self) -> None:
        policy = effective_policy(
            organization={"conversations": 30},
            defaults={"conversations": 90},
            ceilings=None,
            audit_floor_days=None,
        )

        assert policy["conversations"] == 30

    def test_keeping_for_ever_is_a_thing_an_organization_can_say(self) -> None:
        """`null` and absent are different answers, which is why the policy is a
        mapping with holes rather than six integers."""
        policy = effective_policy(
            organization={"conversations": None},
            defaults={"conversations": 90},
            ceilings=None,
            audit_floor_days=None,
        )

        assert policy["conversations"] is None

    def test_nobody_saying_anything_keeps_it_for_ever(self) -> None:
        """A platform that started deleting an existing installation's history on
        upgrade would be one nobody could trust with the next upgrade either."""
        policy = effective_policy(
            organization=None, defaults=None, ceilings=None, audit_floor_days=None
        )

        assert [name for name in RETENTION_CLASSES if policy[name] is not None] == ["audit"]

    def test_the_deployments_ceiling_cuts_an_organization_asking_for_longer(self) -> None:
        policy = effective_policy(
            organization={"conversations": 3650},
            defaults=None,
            ceilings={"conversations": 365},
            audit_floor_days=None,
        )

        assert policy["conversations"] == 365

    def test_the_ceiling_also_cuts_for_ever(self) -> None:
        """ "Nothing lives longer than N days here" is a statement about the
        deployment, not about who bothered to configure something."""
        policy = effective_policy(
            organization=None, defaults=None, ceilings={"runs": 180}, audit_floor_days=None
        )

        assert policy["runs"] == 180

    def test_audit_takes_the_floor_when_nobody_asked_for_longer(self) -> None:
        policy = effective_policy(
            organization=None, defaults=None, ceilings=None, audit_floor_days=None
        )

        assert policy["audit"] == DEFAULT_AUDIT_FLOOR_DAYS

    def test_an_organization_may_keep_audit_longer_than_the_floor(self) -> None:
        policy = effective_policy(
            organization={"audit": 4000}, defaults=None, ceilings=None, audit_floor_days=2190
        )

        assert policy["audit"] == 4000

    def test_a_compatible_audit_ceiling_still_binds(self) -> None:
        """A ceiling above the floor is a valid upper bound, and skipping it let
        an organization ask for longer than the deployment permitted and get it -
        while the API reported the ceiling it was not applying."""
        policy = effective_policy(
            organization={"audit": 5000},
            defaults=None,
            ceilings={"audit": 4000},
            audit_floor_days=2190,
        )

        assert policy["audit"] == 4000

    def test_an_organization_may_not_keep_audit_shorter_than_the_floor(self) -> None:
        """A trail an administrator can shorten is not a trail."""
        policy = effective_policy(
            organization={"audit": 30}, defaults=None, ceilings=None, audit_floor_days=2190
        )

        assert policy["audit"] == 2190

    def test_an_audit_ceiling_below_the_floor_is_reported_not_resolved(self) -> None:
        """It asks for a trail kept six years and deleted after one. Picking
        either leaves a deployment behaving unlike its own settings page."""
        assert policy_conflicts(ceilings={"audit": 30}, audit_floor_days=2190) == ["audit"]

    def test_an_audit_ceiling_above_the_floor_is_no_conflict(self) -> None:
        assert policy_conflicts(ceilings={"audit": 4000}, audit_floor_days=2190) == []

    def test_a_class_this_version_does_not_know_never_leaves_the_column(self) -> None:
        """JSONB holds whatever was written, including a class a later version
        renamed. The row keeps it; nothing downstream sees it."""
        assert known_periods({"conversations": 30, "telepathy": 7}) == {"conversations": 30}


def _service(**overrides: object) -> RetentionService:
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = RetentionService(db, **overrides)  # type: ignore[arg-type]
    return service


def _organization(**fields: object) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), **{"retention_days": None, **fields})


class TestReadingThePolicy:
    async def test_the_read_says_what_was_asked_what_sweeps_and_what_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three answers, because a page showing only the last cannot explain why
        the number on screen is not the number somebody typed."""
        service = _service()
        organization = _organization(retention_days={"conversations": 3650})
        monkeypatch.setattr(
            f"{MODULE}.deployment_settings_repo.get",
            AsyncMock(
                return_value=SimpleNamespace(
                    retention_defaults={"runs": 90},
                    retention_max_days={"conversations": 365},
                    audit_retention_floor_days=2190,
                )
            ),
        )
        with patch(
            "app.services.organization.OrganizationService.get_for_user",
            new=AsyncMock(return_value=(organization, MagicMock(role="owner"))),
        ):
            read = await service.read(organization.id, requester_id=uuid.uuid4())

        assert read.requested == {"conversations": 3650}
        assert read.effective["conversations"] == 365
        assert read.effective["runs"] == 90
        assert read.ceilings == {"conversations": 365}
        assert read.audit_floor_days == 2190

    async def test_a_member_without_org_settings_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """How long this tenant keeps what its people said is a statement about
        the tenant, not a fact every member needs."""
        service = _service()
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        with (
            patch(
                "app.services.organization.OrganizationService.get_for_user",
                new=AsyncMock(return_value=(_organization(), MagicMock(role="viewer"))),
            ),
            pytest.raises(AuthorizationError),
        ):
            await service.read(uuid.uuid4(), requester_id=uuid.uuid4())


class TestChangingThePolicy:
    async def test_a_class_left_out_of_the_request_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A page that sends one row must not silently reset the other five."""
        service = _service()
        organization = _organization(retention_days={"conversations": 30, "runs": 60})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        stored = AsyncMock(return_value=organization)
        monkeypatch.setattr(f"{MODULE}.retention_repo.set_retention", stored)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())
        with patch(
            "app.services.organization.OrganizationService.get_for_user",
            new=AsyncMock(return_value=(organization, MagicMock(role="owner"))),
        ):
            await service.update(
                organization.id,
                RetentionUpdate(retention_days={"runs": 90}),
                actor_user_id=uuid.uuid4(),
            )

        assert stored.await_args.kwargs["retention_days"] == {"conversations": 30, "runs": 90}

    async def test_an_audit_period_below_the_floor_is_refused_not_raised_to_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silently keeping entries longer than the number on the screen is its
        own kind of wrong."""
        service = _service()
        organization = _organization()
        monkeypatch.setattr(
            f"{MODULE}.deployment_settings_repo.get",
            AsyncMock(return_value=SimpleNamespace(audit_retention_floor_days=2190)),
        )
        with (
            patch(
                "app.services.organization.OrganizationService.get_for_user",
                new=AsyncMock(return_value=(organization, MagicMock(role="owner"))),
            ),
            pytest.raises(BadRequestError) as refusal,
        ):
            await service.update(
                organization.id,
                RetentionUpdate(retention_days={"audit": 30}),
                actor_user_id=uuid.uuid4(),
            )

        assert refusal.value.details["fields"][0]["field"] == "audit"

    async def test_the_change_is_audited_as_periods_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        organization = _organization()
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        monkeypatch.setattr(
            f"{MODULE}.retention_repo.set_retention", AsyncMock(return_value=organization)
        )
        audited = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.record_audit", audited)
        with patch(
            "app.services.organization.OrganizationService.get_for_user",
            new=AsyncMock(return_value=(organization, MagicMock(role="owner"))),
        ):
            await service.update(
                organization.id,
                RetentionUpdate(retention_days={"conversations": 30}),
                actor_user_id=uuid.uuid4(),
            )

        assert audited.await_args.kwargs["action"] == "retention.updated"
        assert audited.await_args.kwargs["details"] == {"retention_days": {"conversations": 30}}

    def test_a_period_outside_the_bounds_is_refused_by_the_schema(self) -> None:
        with pytest.raises(ValueError, match="between"):
            RetentionUpdate(retention_days={"conversations": 0})
        with pytest.raises(ValueError, match="between"):
            RetentionUpdate(retention_days={"conversations": 40000})


class TestTheSweep:
    """What leaves, in batches, and what survives it."""

    @staticmethod
    def _repo(monkeypatch: pytest.MonkeyPatch, **counts: int) -> dict[str, AsyncMock]:
        """Stub every delete, each answering how many rows one pass took."""
        mocks = {
            "delete_conversations": AsyncMock(return_value=counts.get("conversations", 0)),
            "delete_runs_keeping_their_spend": AsyncMock(return_value=(counts.get("runs", 0), [])),
            "delete_workspaces": AsyncMock(return_value=counts.get("workspaces", 0)),
            "delete_memory": AsyncMock(return_value=counts.get("memory", 0)),
            "stored_paths_for_expiring_conversations": AsyncMock(return_value=[]),
            "expiring_documents": AsyncMock(return_value=[]),
            "record_purged_spend": AsyncMock(),
            "delete_documents": AsyncMock(return_value=0),
        }
        for name, mock in mocks.items():
            monkeypatch.setattr(f"{MODULE}.retention_repo.{name}", mock)
        return mocks

    @staticmethod
    def _one_organization(
        monkeypatch: pytest.MonkeyPatch, policy: dict[str, int | None]
    ) -> uuid.UUID:
        organization_id = uuid.uuid4()
        monkeypatch.setattr(
            f"{MODULE}.retention_repo.organizations_with_retention",
            AsyncMock(return_value=[(organization_id, policy)]),
        )
        return organization_id

    async def test_a_class_with_no_period_is_not_swept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Keep for ever" has to mean the sweep does not touch it at all."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": None})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        await service.sweep(now=NOW)

        repo["delete_conversations"].assert_not_awaited()

    async def test_the_cutoff_is_the_period_measured_back_from_now(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30, "audit": None})
        monkeypatch.setattr(
            f"{MODULE}.deployment_settings_repo.get",
            AsyncMock(
                return_value=SimpleNamespace(
                    retention_defaults=None,
                    retention_max_days=None,
                    audit_retention_floor_days=None,
                )
            ),
        )
        repo = self._repo(monkeypatch, conversations=3)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        await service.sweep(now=NOW)

        assert repo["delete_conversations"].await_args.kwargs["cutoff"] == NOW - timedelta(days=30)

    async def test_it_keeps_taking_batches_until_a_pass_comes_back_short(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An organization arriving at a ninety-day policy after two years has
        two years to remove, and one statement deleting a million rows holds a
        lock for the length of it."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        repo["delete_conversations"].side_effect = [BATCH, BATCH, 7]
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        assert repo["delete_conversations"].await_count == 3
        assert results[0].removed["conversations"] == BATCH * 2 + 7

    async def test_a_backlog_is_worked_off_over_several_sweeps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One sweep does not run for an hour with every other periodic flow
        queued behind it; the rest is the next sweep's."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch, conversations=BATCH)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        await service.sweep(now=NOW)

        assert repo["delete_conversations"].await_count == MAX_BATCHES

    async def test_what_a_purged_run_spent_is_kept_before_the_row_goes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A month's bill is a sum over exactly these rows. Without this, an
        organization on a thirty-day run retention watches its month-to-date fall
        to zero on the thirty-first and its cap stops enforcing."""
        service = _service()
        self._one_organization(monkeypatch, {"runs": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        month = datetime(2026, 8, 1, tzinfo=UTC)
        repo["delete_runs_keeping_their_spend"].return_value = (2, [(month, Decimal("4.25"), 2)])
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        await service.sweep(now=NOW)

        kept = repo["record_purged_spend"].await_args.kwargs
        assert (kept["period_start"], kept["cost"], kept["runs"]) == (month, Decimal("4.25"), 2)

    async def test_a_conversations_files_are_unlinked_with_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rows cascade and the bytes do not: a purge that left the upload on
        disk would be a retention policy whose files outlive it."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch, conversations=1)
        repo["stored_paths_for_expiring_conversations"].return_value = ["chat/a.pdf"]
        deleted = AsyncMock()
        monkeypatch.setattr("app.services.file_storage.delete_files_best_effort", deleted)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        await service.sweep(now=NOW)

        deleted.assert_awaited_with(["chat/a.pdf"])

    async def test_one_class_failing_does_not_stop_the_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A vector store that is down must not stop conversations being purged.
        The next pass retries it, because a batch that removed nothing comes
        round again."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30, "runs": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch, conversations=4)
        repo["delete_runs_keeping_their_spend"].side_effect = RuntimeError("the database said no")
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        assert results[0].removed == {"conversations": 4}
        assert results[0].failed == ["runs"]

    async def test_audit_resolves_to_a_period_and_is_still_not_swept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The hash chain and its append-only checkpoint are built on entries not
        going anywhere: a bare delete makes `audit-verify` report the retirement
        as tampering. Retiring a chain verifiably is #1622's, and a retention that
        broke the integrity check would be worse than one that says so."""
        service = _service()
        self._one_organization(monkeypatch, {"audit": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        self._repo(monkeypatch)
        audited = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.record_audit", audited)

        assert await service.sweep(now=NOW) == []
        audited.assert_not_awaited()

    async def test_a_vector_store_that_does_not_confirm_fails_the_class(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`remove_document` catches its own store failures and answers False
        rather than raising, so ignoring the answer would delete the only handle
        to content that is still searchable."""
        service = _service(remove_vectors=AsyncMock(return_value=False))
        self._one_organization(monkeypatch, {"knowledge_documents": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        repo["expiring_documents"].return_value = [(uuid.uuid4(), "kb", "vec", None)]
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        assert results[0].failed == ["knowledge_documents"]
        repo["delete_documents"].assert_not_awaited()

    async def test_each_organization_is_committed_on_its_own_for_the_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One transaction around a whole sweep holds every deleted row and every
        audit lock until the last tenant is done, and rolls every delete back if a
        late organization fails - after its files and vectors are already gone."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        self._repo(monkeypatch, conversations=1)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())
        service.db.commit = AsyncMock()

        await service.sweep(now=NOW, commit_each=True)

        service.db.commit.assert_awaited_once()

    async def test_nothing_commits_outside_the_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        self._repo(monkeypatch, conversations=1)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())
        service.db.commit = AsyncMock()

        await service.sweep(now=NOW)

        service.db.commit.assert_not_awaited()

    async def test_the_sweep_records_counts_and_no_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An audit entry that quoted what it deleted would keep the content past
        the retention that removed it."""
        service = _service()
        organization_id = self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        self._repo(monkeypatch, conversations=9)
        audited = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.record_audit", audited)

        await service.sweep(now=NOW)

        entry = audited.await_args.kwargs
        assert entry["action"] == "retention.swept"
        assert entry["actor_user_id"] is None
        assert entry["organization_id"] == organization_id
        assert entry["details"] == {"removed": {"conversations": 9}, "failed": []}

    async def test_an_organization_with_nothing_to_do_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A log line per tenant per day saying "nothing" is a log nobody reads."""
        service = _service()
        self._one_organization(monkeypatch, {"conversations": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        self._repo(monkeypatch)
        audited = AsyncMock()
        monkeypatch.setattr(f"{MODULE}.record_audit", audited)

        assert await service.sweep(now=NOW) == []
        audited.assert_not_awaited()

    async def test_documents_lose_their_vectors_and_files_before_their_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other order leaves content searchable with nothing left to find it
        by, which is #992's shape."""
        remove_vectors = AsyncMock(return_value=True)
        service = _service(remove_vectors=remove_vectors)
        self._one_organization(monkeypatch, {"knowledge_documents": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        document_id = uuid.uuid4()
        repo["expiring_documents"].side_effect = [
            [(document_id, "kb_main", "vec-1", "uploads/a.pdf")],
            [],
        ]
        repo["delete_documents"].return_value = 1
        deleted = AsyncMock()
        monkeypatch.setattr("app.services.file_storage.delete_files_best_effort", deleted)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        remove_vectors.assert_awaited_once_with("kb_main", "vec-1")
        deleted.assert_awaited_with(["uploads/a.pdf"])
        assert repo["delete_documents"].await_args.kwargs["document_ids"] == [document_id]
        assert results[0].removed["knowledge_documents"] == 1

    async def test_a_document_with_no_vectors_and_no_file_still_leaves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A row whose ingestion never completed has neither, and is still a row
        past its window."""
        remove_vectors = AsyncMock()
        service = _service(remove_vectors=remove_vectors)
        self._one_organization(monkeypatch, {"knowledge_documents": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        repo["expiring_documents"].return_value = [(uuid.uuid4(), "kb_main", None, None)]
        repo["delete_documents"].return_value = 1
        deleted = AsyncMock()
        monkeypatch.setattr("app.services.file_storage.delete_files_best_effort", deleted)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        remove_vectors.assert_not_awaited()
        deleted.assert_not_awaited()
        assert results[0].removed["knowledge_documents"] == 1

    async def test_a_document_class_with_nothing_expired_removes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _service(remove_vectors=AsyncMock(return_value=True))
        self._one_organization(monkeypatch, {"knowledge_documents": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        assert await service.sweep(now=NOW) == []
        repo["delete_documents"].assert_not_awaited()

    async def test_a_sweep_with_no_vector_remover_fails_that_class_rather_than_half_purging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document whose row is gone and whose vectors are not is exactly the
        state #992 describes, so the class is reported failed instead."""
        service = _service()
        self._one_organization(monkeypatch, {"knowledge_documents": 30})
        monkeypatch.setattr(f"{MODULE}.deployment_settings_repo.get", AsyncMock(return_value=None))
        repo = self._repo(monkeypatch)
        repo["expiring_documents"].return_value = [(uuid.uuid4(), "kb", "vec", None)]
        monkeypatch.setattr(f"{MODULE}.record_audit", AsyncMock())

        results = await service.sweep(now=NOW)

        assert results[0].failed == ["knowledge_documents"]
        repo["delete_documents"].assert_not_awaited()


class TestTheDeploymentsOwnBounds:
    """The three numbers an app admin sets, on the settings they already write."""

    def test_a_default_and_a_ceiling_are_accepted_per_class(self) -> None:
        update = DeploymentSettingsUpdate(
            retention_defaults={"conversations": 90},
            retention_max_days={"runs": 365},
            audit_retention_floor_days=2190,
        )

        assert update.retention_defaults == {"conversations": 90}
        assert update.retention_max_days == {"runs": 365}
        assert update.audit_retention_floor_days == 2190

    def test_keeping_a_class_for_ever_is_a_thing_a_deployment_can_say(self) -> None:
        assert DeploymentSettingsUpdate(retention_defaults={"runs": None}).retention_defaults == {
            "runs": None
        }

    def test_a_period_outside_the_bounds_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="conversations"):
            DeploymentSettingsUpdate(retention_defaults={"conversations": 0})
        with pytest.raises(ValueError, match="runs"):
            DeploymentSettingsUpdate(retention_max_days={"runs": 40000})

    def test_an_audit_floor_outside_the_bounds_is_refused(self) -> None:
        with pytest.raises(ValueError):
            DeploymentSettingsUpdate(audit_retention_floor_days=0)
