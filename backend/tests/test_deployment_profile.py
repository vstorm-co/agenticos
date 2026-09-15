"""The HIPAA profile's control sheet, control by control (#1448).

A security review asks *can we run this inside our compliant environment, and
can you prove it*. This is the "prove it" half, so every row has to be right in
both directions: a control that passed on a deployment that does not satisfy it
is a sheet somebody puts in front of an auditor, and a control that failed on one
that does is a sheet nobody trusts twice.

The three-outcome shape matters as much as the answers. `attested` exists so a
control that is genuinely the operator's - volume encryption - is *named* rather
than quietly passed, and does not fail a command nobody could otherwise pass.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services import deployment_profile as MODULE
from app.services.deployment_profile import AUDIT_FLOOR_DAYS, evaluate

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _db(*, deployment=None, profiles=(), checkpoints=1) -> MagicMock:
    """A session answering the three reads the sheet makes."""
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[deployment, checkpoints])
    scalars = MagicMock()
    scalars.all.return_value = list(profiles)
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return db


def _model(label: str, base_url: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), label=label, base_url=base_url)


def _settings(**fields: object) -> SimpleNamespace:
    return SimpleNamespace(
        **{"signup_mode": "invite_only", "audit_retention_floor_days": None, **fields}
    )


async def _sheet(
    db, monkeypatch: pytest.MonkeyPatch, *, issuer: str | None = None, **overrides: object
) -> dict[str, tuple[str, str]]:
    """The sheet as a lookup, with settings and the issuer seam patched.

    `issuer` goes through `sso_issuer` rather than the settings object: the
    setting arrives with #1419, and a pydantic settings model refuses an
    attribute it does not declare.
    """
    for name, value in overrides.items():
        monkeypatch.setattr(settings, name, value)
    if issuer is not None:
        monkeypatch.setattr(MODULE, "sso_issuer", lambda: issuer)
    return {row.key: (row.outcome, row.detail) for row in await evaluate(db, "hipaa")}


class TestInTransit:
    async def test_a_verified_certificate_satisfies_postgres(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, POSTGRES_SSLMODE="verify-full")

        assert sheet["postgres-tls"][0] == "met"

    async def test_require_does_not(self, monkeypatch) -> None:
        """It encrypts the socket and verifies no certificate, which is a
        different control from the one the profile asks for."""
        sheet = await _sheet(_db(), monkeypatch, POSTGRES_SSLMODE="require")

        outcome, detail = sheet["postgres-tls"]
        assert outcome == "unmet"
        assert "verifies no certificate" in detail

    async def test_plaintext_postgres_is_named_as_plaintext(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, POSTGRES_SSLMODE="")

        assert sheet["postgres-tls"] == (
            "unmet",
            "POSTGRES_SSLMODE is unset: the link is plaintext",
        )

    async def test_redis_carries_queued_work_and_is_checked_too(self, monkeypatch) -> None:
        assert (await _sheet(_db(), monkeypatch, REDIS_SSL=True))["redis-tls"][0] == "met"
        assert (await _sheet(_db(), monkeypatch, REDIS_SSL=False))["redis-tls"][0] == "unmet"


class TestAtRest:
    async def test_a_vault_key_satisfies_the_credential_control(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, VAULT_MASTER_KEY="k" * 64, VAULT_MASTER_KEYS={})

        assert sheet["vault-key"][0] == "met"

    async def test_a_rotation_set_satisfies_it_as_well(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={1: "k"})

        assert sheet["vault-key"][0] == "met"

    async def test_no_key_at_all_is_unmet(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={})

        assert sheet["vault-key"][0] == "unmet"

    async def test_volume_encryption_is_named_rather_than_passed(self, monkeypatch) -> None:
        """A sheet that quietly skipped what this code cannot see would read as
        complete and would not be."""
        sheet = await _sheet(_db(), monkeypatch)

        outcome, detail = sheet["content-at-rest"]
        assert outcome == "attested"
        assert "operator's" in detail


class TestWhereContentGoes:
    async def test_a_model_on_your_own_network_satisfies_it(self, monkeypatch) -> None:
        db = _db(profiles=[_model("Local", "http://ollama:11434/v1")])

        assert (await _sheet(db, monkeypatch))["local-model"][0] == "met"

    async def test_a_profile_with_no_endpoint_is_the_vendors_public_api(self, monkeypatch) -> None:
        """With no `base_url` of its own it is the provider's public API by
        definition, which takes the content of every run with it."""
        db = _db(profiles=[_model("GPT", None)])

        outcome, detail = (await _sheet(db, monkeypatch))["local-model"]
        assert outcome == "unmet"
        assert "GPT" in detail

    async def test_every_profile_is_read_not_only_a_default(self, monkeypatch) -> None:
        """There is no deployment-wide default: a profile belongs to an
        organization, and any one of them can carry a run's content."""
        db = _db(profiles=[_model("Local", "http://vllm.internal/v1"), _model("Claude", None)])

        outcome, detail = (await _sheet(db, monkeypatch))["local-model"]
        assert outcome == "unmet"
        assert "Claude" in detail and "Local" not in detail

    async def test_no_model_at_all_is_named_rather_than_passed(self, monkeypatch) -> None:
        assert (await _sheet(_db(), monkeypatch))["local-model"][0] == "attested"

    async def test_no_logfire_token_keeps_every_span_here(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, LOGFIRE_TOKEN=None)

        assert sheet["traces-local"][0] == "met"

    async def test_a_token_is_unmet_because_content_defaults_to_full(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, LOGFIRE_TOKEN="pylf_x")

        outcome, detail = sheet["traces-local"]
        assert outcome == "unmet"
        assert "content" in detail


class TestWhoGetsIn:
    async def test_an_identity_provider_satisfies_authentication(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, issuer="https://id.corp.example")

        outcome, detail = sheet["sso"]
        assert outcome == "met"
        # MFA is the provider's job, and the sheet says so rather than claiming it.
        assert "provider" in detail

    async def test_passwords_alone_are_unmet(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, issuer="")

        assert sheet["sso"][0] == "unmet"

    async def test_open_registration_is_unmet(self, monkeypatch) -> None:
        db = _db(deployment=_settings(signup_mode="open"))

        assert (await _sheet(db, monkeypatch))["signup"][0] == "unmet"

    async def test_invite_only_and_closed_both_satisfy_it(self, monkeypatch) -> None:
        for mode in ("invite_only", "closed"):
            db = _db(deployment=_settings(signup_mode=mode))
            assert (await _sheet(db, monkeypatch))["signup"][0] == "met"

    async def test_a_deployment_that_has_never_been_configured_counts_as_open(
        self, monkeypatch
    ) -> None:
        """No row means nobody has closed it, and the default is open."""
        assert (await _sheet(_db(deployment=None), monkeypatch))["signup"][0] == "unmet"


class TestTheTrail:
    async def test_the_built_in_floor_is_six_years(self, monkeypatch) -> None:
        sheet = await _sheet(_db(deployment=_settings()), monkeypatch)

        outcome, detail = sheet["audit-retention"]
        assert outcome == "met"
        assert str(AUDIT_FLOOR_DAYS) in detail

    async def test_a_shortened_floor_is_unmet_and_names_the_number(self, monkeypatch) -> None:
        db = _db(deployment=_settings(audit_retention_floor_days=30))

        outcome, detail = (await _sheet(db, monkeypatch))["audit-retention"]
        assert outcome == "unmet"
        assert "30 days" in detail

    async def test_a_chain_with_entries_satisfies_integrity(self, monkeypatch) -> None:
        sheet = await _sheet(_db(checkpoints=3), monkeypatch)

        outcome, detail = sheet["audit-chain"]
        assert outcome == "met"
        assert "audit-verify" in detail

    async def test_an_empty_trail_has_nothing_to_verify(self, monkeypatch) -> None:
        assert (await _sheet(_db(checkpoints=0), monkeypatch))["audit-chain"][0] == "attested"


class TestTheSheetItself:
    async def test_only_an_unmet_control_fails_the_command(self, monkeypatch) -> None:
        """An attested control is the operator's to evidence, and a command that
        failed on one would be a command nobody could ever pass."""
        monkeypatch.setattr(settings, "POSTGRES_SSLMODE", "verify-full")
        monkeypatch.setattr(settings, "REDIS_SSL", True)
        monkeypatch.setattr(settings, "VAULT_MASTER_KEY", "k" * 64)
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
        monkeypatch.setattr(MODULE, "sso_issuer", lambda: "https://id.corp.example")
        db = _db(deployment=_settings(), profiles=[_model("Local", "http://ollama:11434/v1")])

        rows = await evaluate(db, "hipaa")

        assert [row.key for row in rows if row.failed] == []
        assert {row.outcome for row in rows} == {"met", "attested"}

    async def test_every_control_cites_the_safeguard_it_answers(self, monkeypatch) -> None:
        """The sheet is read by somebody holding the regulation, not the code."""
        rows = await evaluate(_db(), "hipaa")

        assert all(row.safeguard.startswith("§164.312") for row in rows)
        assert len({row.key for row in rows}) == len(rows)
