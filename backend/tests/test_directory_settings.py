"""The directory sign-in settings are refused at startup when they cannot work (#1773).

A misconfigured directory does not fail loudly on its own: it tells every person
in the company that their password is wrong. So each configuration that would
send a password in the clear or find nobody is refused when the process starts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_VALID = {"LDAP_URL": "ldaps://dc.corp.example", "LDAP_USER_BASE_DN": "ou=people,dc=corp"}


def test_no_directory_is_a_valid_configuration() -> None:
    settings = Settings(LDAP_URL="", KERBEROS_ENABLED=False)

    assert settings.LDAP_URL == ""


def test_ldaps_with_a_base_dn_is_enough() -> None:
    assert Settings(**_VALID).LDAP_URL == "ldaps://dc.corp.example"


def test_ldap_with_start_tls_is_accepted() -> None:
    assert Settings(**{**_VALID, "LDAP_URL": "ldap://dc", "LDAP_START_TLS": True}).LDAP_START_TLS


@pytest.mark.security
def test_plaintext_ldap_is_refused_unless_allowed_by_name() -> None:
    with pytest.raises(ValidationError, match="in the clear"):
        Settings(**{**_VALID, "LDAP_URL": "ldap://dc"})

    assert Settings(**{**_VALID, "LDAP_URL": "ldap://dc", "LDAP_ALLOW_PLAINTEXT": True})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"LDAP_URL": "https://dc"}, "must start with ldaps://"),
        ({"LDAP_START_TLS": True}, "already TLS"),
        ({"LDAP_USER_BASE_DN": ""}, "LDAP_USER_BASE_DN is required"),
        ({"LDAP_USER_FILTER": "(uid=jane)"}, "must contain {username}"),
        ({"LDAP_BIND_DN": "cn=svc"}, "together"),
        ({"LDAP_BIND_PASSWORD": "secret"}, "together"),
        (
            {"LDAP_GROUP_BASE_DN": "ou=groups", "LDAP_GROUP_FILTER": "(objectClass=group)"},
            "must contain {dn} or {username}",
        ),
        (
            {"KERBEROS_ENABLED": True, "LDAP_KERBEROS_FILTER": "(objectClass=user)"},
            "must contain {principal} or {username}",
        ),
    ],
)
def test_a_directory_that_would_find_nobody_is_refused(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**{**_VALID, **overrides})


def test_a_group_filter_on_the_username_is_enough() -> None:
    settings = Settings(
        **_VALID, LDAP_GROUP_BASE_DN="ou=groups", LDAP_GROUP_FILTER="(memberUid={username})"
    )

    assert settings.LDAP_GROUP_FILTER == "(memberUid={username})"


def test_kerberos_needs_a_directory_to_resolve_principals_in() -> None:
    with pytest.raises(ValidationError, match="KERBEROS_ENABLED needs LDAP_URL"):
        Settings(LDAP_URL="", KERBEROS_ENABLED=True)

    assert Settings(**_VALID, KERBEROS_ENABLED=True).KERBEROS_ENABLED


def test_ldap_and_an_oidc_groups_claim_together_are_refused() -> None:
    """Found in review: each reports groups in its own ids, and each sign-in would
    reconcile the person's directory memberships against only its own - so
    alternating sign-in methods removed and recreated their access."""
    with pytest.raises(ValidationError, match="not both"):
        Settings(**_VALID, OIDC_GROUPS_CLAIM="groups")
