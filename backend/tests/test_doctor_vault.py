"""`doctor`'s vault line: which master key seals the vault, never a false failure."""

import pytest

from app.commands.doctor import _report, _vault_configured
from app.core.config import settings


def test_the_fallback_master_key_is_healthy_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """`VAULT_MASTER_KEY` unset is sealed under `SECRET_KEY`, which config only allows in
    local and development: a working vault, so a warning rather than a failure."""
    monkeypatch.setattr(settings, "VAULT_MASTER_KEY", "")
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {})

    status, detail = _vault_configured()

    assert status == "unconfigured"
    assert "SECRET_KEY" in detail
    assert "VAULT_MASTER_KEYS" in detail and "vault-rotate" in detail
    assert _report("vault", status, detail) is False


@pytest.mark.parametrize(("single", "staged"), [("a" * 64, {}), ("", {1: "a" * 64, 2: "b" * 64})])
def test_a_dedicated_key_is_healthy(
    monkeypatch: pytest.MonkeyPatch, single: str, staged: dict[int, str]
) -> None:
    monkeypatch.setattr(settings, "VAULT_MASTER_KEY", single)
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", staged)

    assert _vault_configured() == ("healthy", "a dedicated master key is configured")
