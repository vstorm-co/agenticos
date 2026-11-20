"""Node state and enrollment credentials rotate together and cannot leak to logs."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.commands.vault_rotate import SEALED_TABLES, Report, _rotate_table
from app.core.config import settings
from app.core.logging import redact_secret_paths
from app.core.vault import seal, unseal
from app.services.network_connections.secrets import connection_scope
from tests.network_connection_fixtures import network_row

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_rotation_preserves_both_envelopes_under_the_connections_owner_scope(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: "synthetic-old-key-" + "a" * 32})
    row = network_row()
    scope = connection_scope(row)
    row.state_payload = seal("synthetic node state", scope=scope).ciphertext
    row.login_payload = seal(
        "https://login.tailscale.com/a/synthetic-login", scope=scope
    ).ciphertext
    monkeypatch.setattr(
        settings,
        "VAULT_MASTER_KEYS",
        {1: "synthetic-old-key-" + "a" * 32, 2: "synthetic-new-key-" + "b" * 32},
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    report = Report()
    spec = next(spec for spec in SEALED_TABLES if spec.label == "network_connections")
    await _rotate_table(db, spec, target=2, dry_run=False, report=report)
    assert report.rotated == 1 and report.failures == []
    assert row.secret_key_version == 2
    assert unseal(row.state_payload, scope=scope, key_version=2) == "synthetic node state"
    assert (
        unseal(row.login_payload, scope=scope, key_version=2)
        == "https://login.tailscale.com/a/synthetic-login"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://login.tailscale.com/a/synthetic-bearer",
        "https://login.tailscale.com:443/a/synthetic-bearer?flow=synthetic-query",
        "https://LOGIN.TAILSCALE.COM/a/synthetic-bearer/more?unlisted=synthetic-query",
    ],
)
def test_log_redaction_removes_the_entire_enrollment_bearer_and_query(url):
    redacted = redact_secret_paths(f'provider returned "{url}"')
    assert "synthetic-bearer" not in redacted
    assert "synthetic-query" not in redacted
    assert "/a/[REDACTED]" in redacted


def test_an_ordinary_tailscale_documentation_url_is_not_treated_as_a_credential():
    url = "https://tailscale.com/kb/1017/install"
    assert redact_secret_paths(url) == url
