"""Navigation and notices are intersected; they never create permissions."""

from itertools import product

import pytest
from pydantic import ValidationError

from app.schemas.console_presentation import (
    NAVIGATION_ENTRIES,
    SIMPLE_NAVIGATION,
    ConsoleNotices,
    ConsolePreferences,
    RoleConsoleUpdate,
    StoredConsolePreferences,
    StoredRoleConsole,
    resolve_console_presentation,
    stored_role_defaults,
)
from app.schemas.organization import OrganizationUpdate


def test_strict_write_boundary_keeps_omission_clear_and_empty_distinct() -> None:
    assert ConsolePreferences().changes() == {}
    assert ConsolePreferences(navigation=[]).changes() == {"navigation": []}
    assert ConsolePreferences(navigation=None).changes() == {"navigation": None}
    assert ConsoleNotices(product_notices=False).changes() == {"product_notices": False}
    assert RoleConsoleUpdate(navigation=list(SIMPLE_NAVIGATION)).changes() == {
        "navigation": list(SIMPLE_NAVIGATION)
    }
    for data in (
        {"navigation": ["invented"]},
        {"navigation": ["chat", "chat"]},
        {"navigation": "chat"},
        {"desktop_install_prompt": 1},
        {"product_notices": "false"},
        {"role": "owner"},
    ):
        with pytest.raises(ValidationError):
            ConsolePreferences.model_validate(data)
    with pytest.raises(ValidationError):
        RoleConsoleUpdate(navigation=["chat", "chat"])
    with pytest.raises(ValidationError):
        OrganizationUpdate.model_validate(
            {"console_role_defaults": {"superuser": {"navigation": []}}}
        )


def test_default_and_retired_navigation_keys() -> None:
    default = resolve_console_presentation(
        StoredConsolePreferences(),
        StoredRoleConsole(),
        ConsoleNotices(),
        StoredConsolePreferences(),
    )
    assert default.navigation == list(NAVIGATION_ENTRIES)
    assert default.desktop_install_prompt and default.product_notices
    result = resolve_console_presentation(
        StoredConsolePreferences(),
        StoredRoleConsole(navigation=["retired", "chat"]),
        ConsoleNotices(),
        StoredConsolePreferences(navigation=["chat", "retired"]),
    )
    assert result.navigation == ["chat"]
    assert stored_role_defaults(None) == {}
    assert stored_role_defaults({"member": {"navigation": []}})["member"].navigation == []


@pytest.mark.parametrize(
    ("ceiling", "organization", "personal"),
    list(product((None, [], ["chat"], ["chat", "inbox"]), repeat=3)),
)
def test_navigation_cannot_widen_a_parent_and_empty_is_intentional(
    ceiling: list[str] | None, organization: list[str] | None, personal: list[str] | None
) -> None:
    result = resolve_console_presentation(
        StoredConsolePreferences(navigation=ceiling),
        StoredRoleConsole(navigation=organization),
        ConsoleNotices(),
        StoredConsolePreferences(navigation=personal),
    )
    expected = [
        entry
        for entry in NAVIGATION_ENTRIES
        if (ceiling is None or entry in ceiling)
        and (organization is None or entry in organization)
        and (personal is None or entry in personal)
    ]
    assert result.navigation == expected


@pytest.mark.parametrize(
    ("ceiling", "organization", "personal"), list(product((None, True, False), repeat=3))
)
def test_notice_choices_cannot_override_organization_or_deployment(
    ceiling: bool | None, organization: bool | None, personal: bool | None
) -> None:
    result = resolve_console_presentation(
        StoredConsolePreferences(desktop_install_prompt=ceiling, product_notices=ceiling),
        StoredRoleConsole(),
        ConsoleNotices(desktop_install_prompt=organization, product_notices=organization),
        StoredConsolePreferences(desktop_install_prompt=personal, product_notices=personal),
    )
    assert result.desktop_install_prompt is (
        ceiling is not False and organization is not False and personal is not False
    )
    assert result.product_notices is result.desktop_install_prompt


def test_role_dashboard_inherits_until_a_person_saves_a_layout_and_retains_retired_entries() -> (
    None
):
    from uuid import uuid4

    from app.schemas.console_dashboard import OrganizationDashboardUpdate

    empty = OrganizationDashboardUpdate(entries=[])
    assert empty.entries == []
    with pytest.raises(ValidationError):
        OrganizationDashboardUpdate.model_validate(
            {
                "entries": [
                    {"widget": "projects", "span": "s6", "options": {"agent_id": str(uuid4())}}
                ]
            }
        )
    with pytest.raises(ValidationError):
        OrganizationDashboardUpdate.model_validate(
            {
                "entries": [
                    {"widget": "projects", "span": "s6", "options": {"user_id": str(uuid4())}}
                ]
            }
        )
    valid = OrganizationDashboardUpdate.model_validate(
        {
            "entries": [
                {"kind": "section", "label": "My work"},
                {"widget": "projects", "span": "s6"},
                {"widget": "runs", "span": "s6", "options": {"period": "7d"}},
            ]
        }
    )
    assert len(valid.entries) == 3
    stored = StoredRoleConsole.model_validate(
        {"dashboard": {"entries": [{"widget": "retired-card", "span": "retired-width"}]}}
    )
    result = resolve_console_presentation(
        StoredConsolePreferences(), stored, ConsoleNotices(), StoredConsolePreferences()
    )
    assert result.dashboard_default is not None
    assert result.dashboard_default.entries[0].widget == "retired-card"
