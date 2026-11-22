"""Presentation preferences for the signed-in chat home, scoped to one membership."""

from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, field_validator

from app.schemas.base import BaseSchema


class ChatHomeOverrides(BaseSchema):
    """Omitted PATCH fields stay unchanged; null clears one inherited override."""

    model_config = ConfigDict(extra="forbid")

    inbox: StrictBool | None = Field(
        default=None,
        description="Inbox preview on the empty chat home; never changes Inbox access.",
    )
    starters: StrictBool | None = Field(
        default=None, description="Suggested prompts below the empty chat composer."
    )
    greeting: StrictBool | None = Field(
        default=None, description="Welcome heading on the empty chat home; not agent behavior."
    )
    feature_hints: StrictBool | None = Field(
        default=None,
        description="Contextual product-discovery hints on chat home; essential labels and tooltips remain.",
    )

    def changes(self) -> dict[str, bool | None]:
        """The supplied fields, retaining explicit clears without accepting arbitrary keys."""
        values = {
            "inbox": self.inbox,
            "starters": self.starters,
            "greeting": self.greeting,
            "feature_hints": self.feature_hints,
        }
        return {key: value for key, value in values.items() if key in self.model_fields_set}


class ChatHomeOptions(BaseSchema):
    """Effective presentation, defaulting to the existing chat-home experience."""

    inbox: bool = True
    starters: bool = True
    greeting: bool = True
    feature_hints: bool = True


def resolve_chat_home(
    available: ChatHomeOverrides, defaults: ChatHomeOverrides, preferences: ChatHomeOverrides
) -> ChatHomeOptions:
    """Only the deployment ceiling restricts a member's presentation choice."""

    def resolve(ceiling: bool | None, organization: bool | None, member: bool | None) -> bool:
        return ceiling is not False and (
            member if member is not None else organization if organization is not None else True
        )

    return ChatHomeOptions(
        inbox=resolve(available.inbox, defaults.inbox, preferences.inbox),
        starters=resolve(available.starters, defaults.starters, preferences.starters),
        greeting=resolve(available.greeting, defaults.greeting, preferences.greeting),
        feature_hints=resolve(
            available.feature_hints, defaults.feature_hints, preferences.feature_hints
        ),
    )


class OnboardingReminderOverrides(BaseSchema):
    """Presentation frequency only; null inherits the parent/default of one day."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = Field(
        default=None, description="Show setup reminders here; null inherits the parent default."
    )
    snooze_days: Literal[1, 3, 7] | None = Field(
        default=None,
        description="Days after dismissal before the next reminder: 1, 3 or 7; null inherits.",
    )

    @field_validator("snooze_days", mode="before")
    @classmethod
    def integer_days(cls, value: object) -> object:
        if value is True or value is False:
            raise ValueError("Snooze days must be 1, 3 or 7")
        return value

    def changes(self) -> dict[str, bool | int | None]:
        values: dict[str, bool | int | None] = {
            "enabled": self.enabled,
            "snooze_days": self.snooze_days,
        }
        return {key: value for key, value in values.items() if key in self.model_fields_set}


class OnboardingReminderOptions(BaseSchema):
    enabled: bool = True
    snooze_days: Literal[1, 3, 7] = 1


class OnboardingReminderRead(BaseSchema):
    availability: bool = True
    organization_defaults: OnboardingReminderOverrides
    preferences: OnboardingReminderOverrides
    effective: OnboardingReminderOptions


def resolve_onboarding_reminders(
    available: bool | None,
    defaults: OnboardingReminderOverrides,
    preferences: OnboardingReminderOverrides,
) -> OnboardingReminderRead:
    return OnboardingReminderRead(
        availability=available is not False,
        organization_defaults=defaults,
        preferences=preferences,
        effective=OnboardingReminderOptions(
            enabled=available is not False
            and (
                preferences.enabled
                if preferences.enabled is not None
                else defaults.enabled
                if defaults.enabled is not None
                else True
            ),
            snooze_days=preferences.snooze_days or defaults.snooze_days or 1,
        ),
    )


class ConsoleExperienceRead(BaseSchema):
    """The active membership's hierarchy, without deployment policy unrelated to the console."""

    reminders: OnboardingReminderRead
    availability: ChatHomeOptions
    organization_defaults: ChatHomeOverrides
    preferences: ChatHomeOverrides
    effective: ChatHomeOptions


class ConsoleExperienceUpdate(BaseSchema):
    """Change only my active membership; null resets all four personal choices."""

    model_config = ConfigDict(extra="forbid")
    preferences: ChatHomeOverrides | None = None
    reminders: OnboardingReminderOverrides | None = None
