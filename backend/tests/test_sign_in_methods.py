"""Only usable deployment identity providers belong on the public sign-in page."""

import pytest

from app.core.config import settings
from app.core.sign_in_methods import configured_sign_in_providers


@pytest.mark.parametrize(
    ("google_id", "google_secret", "oidc_issuer", "oidc_id", "ldap_url", "kerberos", "expected"),
    [
        ("", "", "", "", "", False, []),
        ("client", "", "", "", "", False, []),
        ("", "secret", "", "", "", False, []),
        ("client", "secret", "", "", "", False, ["google"]),
        ("", "", "https://id.example", "", "", False, []),
        ("", "", "", "client", "", False, []),
        ("", "", "https://id.example", "client", "", False, ["oidc"]),
        ("", "", "", "", "", True, []),
        ("", "", "", "", "ldaps://directory.example", False, ["ldap"]),
        (
            "client",
            "secret",
            "https://id.example",
            "oidc",
            "ldaps://directory.example",
            True,
            ["google", "oidc", "ldap", "kerberos"],
        ),
    ],
)
def test_only_configured_providers_are_offered(
    google_id: str,
    google_secret: str,
    oidc_issuer: str,
    oidc_id: str,
    ldap_url: str,
    kerberos: bool,
    expected: list[str],
) -> None:
    config = settings.model_copy(
        update={
            "GOOGLE_CLIENT_ID": google_id,
            "GOOGLE_CLIENT_SECRET": google_secret,
            "OIDC_ISSUER": oidc_issuer,
            "OIDC_CLIENT_ID": oidc_id,
            "LDAP_URL": ldap_url,
            "KERBEROS_ENABLED": kerberos,
        }
    )
    assert configured_sign_in_providers(config) == expected
