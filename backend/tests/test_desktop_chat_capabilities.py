"""Conversation opt-ins add local tools without changing the published spec."""

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.schemas.local_target import LocalTarget
from app.services.agent_runner import _with_local_capabilities


@pytest.mark.parametrize(
    "browser,folder", [(True, None), (True, "/approved"), (False, "/approved")]
)
def test_local_tools_are_run_only_and_preserve_authors_policy(
    browser: bool, folder: str | None
) -> None:
    original = AgentSpec(name="Plain")
    local = LocalTarget(folder=folder, browser=browser)
    runnable = _with_local_capabilities(original, local)
    assert not original.capabilities
    bindings = {binding.id: binding for binding in runnable.capabilities}
    assert ("sandbox" in bindings) == (folder is not None)
    assert ("browser_use" in bindings) == browser
    if browser:
        assert bindings["browser_use"].config["connection"] == "local"
    assert _with_local_capabilities(original, None) is original
    guarded = original.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(
                    id="browser_use",
                    enabled=False,
                    approval="required",
                    config={"allowed_domains": ["example.com"]},
                ),
                CapabilityBindingSpec(
                    id="sandbox", enabled=False, tool_approval={"execute": "required"}
                ),
            ]
        }
    )
    result = _with_local_capabilities(guarded, local)
    bindings = {binding.id: binding for binding in result.capabilities}
    assert bindings["browser_use"].approval == "required"
    assert bindings["browser_use"].config["allowed_domains"] == ["example.com"]
    assert bindings["sandbox"].tool_approval == {"execute": "required"}
    assert not any(binding.enabled for binding in guarded.capabilities)
