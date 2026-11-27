"""The upstream workspace adapter still consumes the Daytona 0.x root API."""

from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams, DaytonaConfig


def test_workspace_sdk_exposes_the_root_methods_used_by_the_adapter() -> None:
    # No client construction or provider calls: catch the SDK 2.x namespace
    # migration before a configured deployment tries to open its first sandbox.
    assert callable(AsyncDaytona.create)
    assert callable(AsyncDaytona.get)
    params = CreateSandboxFromSnapshotParams()
    assert params.model_copy(update={"name": "workspace"}).name == "workspace"
    config = DaytonaConfig(api_key="contract-test-not-a-real-key")
    assert config.api_key == "contract-test-not-a-real-key"
