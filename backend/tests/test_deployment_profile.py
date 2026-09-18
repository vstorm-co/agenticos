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
from app.services.deployment_profile import AUDIT_FLOOR_DAYS, evaluate, sso_issuer

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _db(
    *, deployment=None, profiles=(), checkpoints=1, tracing_agents=(), tracing_environments=0
) -> MagicMock:
    """A session answering the reads the sheet makes, in the order it makes them.

    `scalar`: the deployment settings, the count of environments carrying their
    own tracing token, then the audit checkpoints. `execute`: the model profiles,
    then the published agents that export traces.
    """
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[deployment, tracing_environments, checkpoints])
    scalars = MagicMock()
    scalars.all.return_value = list(profiles)
    models = MagicMock()
    models.scalars.return_value = scalars
    agents = MagicMock()
    agents.all.return_value = list(tracing_agents)
    db.execute = AsyncMock(side_effect=[models, agents])
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

    `issuer` goes through `sso_issuer` rather than the settings object, so a
    test about a control's *outcome* does not restate which settings compose
    into one; `TestWhatCountsAsConfiguredSso` covers that composition directly.
    """
    for name, value in overrides.items():
        monkeypatch.setattr(settings, name, value)
    if issuer is not None:
        monkeypatch.setattr(MODULE, "sso_issuer", lambda: issuer)
    return {row.key: (row.outcome, row.detail) for row in await evaluate(db, "hipaa")}


class TestWhatCountsAsConfiguredSso:
    """`sso_issuer` is the seam the sheet reads, and it answers for a sign-in
    that can actually happen rather than for a setting that is merely present."""

    def test_an_issuer_and_a_client_id_is_configured(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "OIDC_ISSUER", "https://id.corp.example")
        monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "agenticos")

        assert sso_issuer() == "https://id.corp.example"

    def test_an_issuer_without_a_client_id_is_not(self, monkeypatch) -> None:
        """`app.core.oauth._oidc` returns `None` without a client id and the
        sign-in route answers 404, so a control reading "met" off the issuer
        alone would attest a sign-in nobody can perform."""
        monkeypatch.setattr(settings, "OIDC_ISSUER", "https://id.corp.example")
        monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "")

        assert sso_issuer() == ""

    def test_neither_is_not(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "OIDC_ISSUER", "")
        monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "")

        assert sso_issuer() == ""


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

    async def test_verify_ca_does_not_either(self, monkeypatch) -> None:
        """It validates the chain and not the hostname, so a server holding any
        certificate from the same CA satisfies it (#1448 review)."""
        sheet = await _sheet(_db(), monkeypatch, POSTGRES_SSLMODE="verify-ca")

        outcome, detail = sheet["postgres-tls"]
        assert outcome == "unmet"
        assert "hostname" in detail

    async def test_the_browsers_hop_is_checked_too(self, monkeypatch) -> None:
        """Store and model transport could both pass while a sign-in, a prompt
        and its answer crossed the client boundary in plaintext."""
        sheet = await _sheet(
            _db(), monkeypatch, FRONTEND_URL="http://console.example", PUBLIC_BASE_URL="https://api"
        )

        outcome, detail = sheet["browser-tls"]
        assert outcome == "unmet"
        assert "FRONTEND_URL" in detail and "PUBLIC_BASE_URL" not in detail

    async def test_https_addresses_leave_the_certificate_to_the_proxy(self, monkeypatch) -> None:
        sheet = await _sheet(
            _db(), monkeypatch, FRONTEND_URL="https://console", PUBLIC_BASE_URL="https://api"
        )

        outcome, detail = sheet["browser-tls"]
        assert outcome == "attested"
        assert "reverse proxy" in detail

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
        sheet = await _sheet(
            _db(), monkeypatch, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={1: "k" * 64}
        )

        assert sheet["vault-key"][0] == "met"

    async def test_no_key_at_all_is_unmet(self, monkeypatch) -> None:
        sheet = await _sheet(_db(), monkeypatch, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={})

        assert sheet["vault-key"][0] == "unmet"

    async def test_a_guessable_key_is_unmet_however_well_it_is_derived(self, monkeypatch) -> None:
        """HKDF derives a correctly sized wrapping key from anything and cannot
        add entropy to a one-character secret - so an attacker with the
        ciphertext recovers the credentials the sheet reports protected."""
        sheet = await _sheet(_db(), monkeypatch, VAULT_MASTER_KEY="x", VAULT_MASTER_KEYS={})

        outcome, detail = sheet["vault-key"]
        assert outcome == "unmet"
        assert "openssl rand -hex 32" in detail

    async def test_one_weak_key_in_a_rotation_set_is_enough_to_fail(self, monkeypatch) -> None:
        """A rotation set is every key the vault may unwrap with, so a weak one
        in it is a weak one in use."""
        sheet = await _sheet(
            _db(), monkeypatch, VAULT_MASTER_KEY="", VAULT_MASTER_KEYS={1: "k" * 64, 2: "x"}
        )

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

    async def test_a_public_host_with_a_local_word_in_its_name_does_not(self, monkeypatch) -> None:
        """A substring test called `https://ollama.vendor.example/v1` local and
        passed the sheet while prompts left the network (#1448 review)."""
        db = _db(profiles=[_model("Vendor", "https://ollama.vendor.example/v1")])

        outcome, detail = (await _sheet(db, monkeypatch))["local-model"]
        assert outcome == "unmet"
        assert "Vendor" in detail

    async def test_a_private_address_is_local(self, monkeypatch) -> None:
        db = _db(profiles=[_model("On the rack", "http://10.1.2.3:8000/v1")])

        assert (await _sheet(db, monkeypatch))["local-model"][0] == "met"

    async def test_a_public_address_is_not(self, monkeypatch) -> None:
        db = _db(profiles=[_model("Somewhere", "https://93.184.216.34/v1")])

        assert (await _sheet(db, monkeypatch))["local-model"][0] == "unmet"

    async def test_a_cluster_name_is_local(self, monkeypatch) -> None:
        db = _db(profiles=[_model("In cluster", "http://llm.ai.svc.cluster.local/v1")])

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

    async def test_an_agent_carrying_its_own_token_is_unmet_too(self, monkeypatch) -> None:
        """A deployment with no token of its own could report that nothing left
        while a published agent exported every run (#1448 review)."""
        spec = {"observability": {"token_secret_id": str(uuid.uuid4())}}
        db = _db(tracing_agents=[("Support", spec)])

        outcome, detail = (await _sheet(db, monkeypatch, LOGFIRE_TOKEN=None))["traces-local"]
        assert outcome == "unmet"
        assert "1 published agent" in detail

    async def test_an_agent_that_traces_without_content_is_not_counted(self, monkeypatch) -> None:
        """Timing, tokens, cost and tool names leave; the protected content does
        not, which is what this control is about."""
        spec = {"observability": {"token_secret_id": str(uuid.uuid4()), "content": "none"}}
        db = _db(tracing_agents=[("Support", spec)])

        assert (await _sheet(db, monkeypatch, LOGFIRE_TOKEN=None))["traces-local"][0] == "met"

    async def test_an_agent_with_no_observability_block_is_not_counted(self, monkeypatch) -> None:
        """Most published specs carry none, and one that does may name no token."""
        db = _db(
            tracing_agents=[
                ("Plain", {"name": "Plain"}),
                ("Named", {"observability": {"service_name": "support"}}),
            ]
        )

        assert (await _sheet(db, monkeypatch, LOGFIRE_TOKEN=None))["traces-local"][0] == "met"

    async def test_an_environment_carrying_a_token_is_unmet(self, monkeypatch) -> None:
        db = _db(tracing_environments=2)

        outcome, detail = (await _sheet(db, monkeypatch, LOGFIRE_TOKEN=None))["traces-local"]
        assert outcome == "unmet"
        assert "2 environment" in detail


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
        monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {})
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")
        monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.example")
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
