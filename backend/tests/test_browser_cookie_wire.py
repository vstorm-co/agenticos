"""Saved sign-ins retain only valid CDP write fields without leaking their values."""

import pytest
from pydantic import JsonValue

from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._page import restored_cookie_parameters


def test_saved_session_cookie_retains_security_flags_without_read_only_metadata() -> None:
    cookie: dict[str, JsonValue] = {
        "name": "session",
        "value": "private-cookie-value",
        "domain": "example.test",
        "path": "/",
        "session": True,
        "expires": -1,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Strict",
        "priority": "High",
        "size": 42,
    }
    parameters = restored_cookie_parameters([cookie], "owned-context")
    assert parameters == {
        "browserContextId": "owned-context",
        "cookies": [
            {
                "name": "session",
                "value": "private-cookie-value",
                "domain": "example.test",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Strict",
                "priority": "High",
            }
        ],
    }
    assert cookie["expires"] == -1
    assert cookie["session"] is True


def test_default_browser_context_is_omitted_and_persistent_cookie_expiry_survives() -> None:
    assert restored_cookie_parameters(
        [
            {
                "name": "session",
                "value": "private",
                "domain": "example.test",
                "expires": 2000000000,
            }
        ],
        None,
    ) == {
        "cookies": [
            {
                "name": "session",
                "value": "private",
                "domain": "example.test",
                "expires": 2000000000,
            }
        ]
    }


@pytest.mark.security
@pytest.mark.parametrize(
    "cookie",
    [
        {"value": "secret-cookie-marker"},
        {"name": "session", "value": ["secret-cookie-marker"]},
        {"name": "session", "value": "secret-cookie-marker", "secure": "true"},
        {"name": "session", "value": "secret-cookie-marker", "sameSite": "invalid"},
    ],
)
def test_invalid_saved_cookie_is_refused_without_its_secret_in_the_error(
    cookie: dict[str, JsonValue],
) -> None:
    with pytest.raises(EndpointError) as caught:
        restored_cookie_parameters([cookie], None)
    assert str(caught.value) == "Saved browser sign-in cookies are invalid."
    assert "secret-cookie-marker" not in str(caught.value)
    assert caught.value.__suppress_context__
