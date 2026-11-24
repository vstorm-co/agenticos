"""A browser binding may turn teaching on only when it uses the operator's built-in browser."""

import pytest

from app.agents.capabilities.browser_use import WebBrowserConfig, connection_problems
from app.core.config import settings

PROVISIONED = "http://browser.internal:9222"
BUILT_IN = "Browser teaching requires the operator-provisioned built-in browser"
REFINEMENT_NEEDS_TEACHING = (
    "Enable browser teaching before allowing procedure refinement suggestions"
)


def _config(**fields: object) -> WebBrowserConfig:
    return WebBrowserConfig.model_construct(
        **{"connection": "built_in", "cdp_url": PROVISIONED, **fields}
    )


@pytest.fixture(autouse=True)
def provisioned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", PROVISIONED)


@pytest.mark.parametrize("field", ["allow_teaching", "learn_site_procedures"])
def test_teaching_on_the_operators_browser_raises_no_binding_problem(field: str) -> None:
    config = _config(allow_teaching=True, learn_site_procedures=field == "learn_site_procedures")
    assert BUILT_IN not in connection_problems(config, has_secret=False)


def test_teaching_is_refused_on_any_other_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert BUILT_IN in connection_problems(
        _config(allow_teaching=True, connection="hosted"), has_secret=False
    )


def test_teaching_is_refused_when_the_operator_provisioned_no_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")
    assert BUILT_IN in connection_problems(_config(allow_teaching=True), has_secret=False)


def test_teaching_is_refused_on_an_endpoint_other_than_the_operators() -> None:
    config = _config(allow_teaching=True, cdp_url="http://elsewhere.example:9222")
    assert BUILT_IN in connection_problems(config, has_secret=False)


def test_a_trailing_slash_on_either_endpoint_does_not_change_the_answer() -> None:
    config = _config(allow_teaching=True, cdp_url=PROVISIONED + "/")
    assert BUILT_IN not in connection_problems(config, has_secret=False)


def test_procedure_refinement_needs_teaching_enabled_first() -> None:
    problems = connection_problems(_config(learn_site_procedures=True), has_secret=False)
    assert REFINEMENT_NEEDS_TEACHING in problems
    assert REFINEMENT_NEEDS_TEACHING not in connection_problems(
        _config(learn_site_procedures=True, allow_teaching=True), has_secret=False
    )
