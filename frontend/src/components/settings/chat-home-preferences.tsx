"use client";

import { useTranslations } from "next-intl";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { SectionCard } from "./settings-section";
import { OnboardingReminderControls } from "./onboarding-reminder-controls";
import { ConsoleNavigationControls } from "./console-navigation-controls";
import { ConsoleNoticeControls } from "./console-notice-controls";
import { PersonalChatCostControl } from "./chat-cost-controls";
import { ChatHomeControls } from "./chat-home-controls";
import { CHAT_HOME_ITEMS, DEFAULT_CHAT_HOME } from "@/lib/console-experience-api";

export function ChatHomePreferences() {
  const t = useTranslations("consoleExperience");
  const tc = useTranslations("common");
  const experience = useConsoleExperience();
  const defaults = { ...DEFAULT_CHAT_HOME };
  for (const field of CHAT_HOME_ITEMS)
    defaults[field] = experience.data?.organization_defaults[field] ?? true;
  return (
    <>
      {experience.data?.presentation && (
        <SectionCard
          title={t("presentation.personalTitle")}
          description={t("presentation.personalHint")}
          tour="personal-console-navigation"
        >
          <ConsoleNavigationControls
            key={`${experience.organizationId}-${experience.userId}`}
            showUnavailable={false}
            value={experience.data.presentation.preferences.navigation}
            allowed={experience.data.presentation.organization_navigation}
            disabled={experience.save.isPending}
            onSave={(navigation, onSaved) =>
              experience.save.mutate({ console: { navigation } }, onSaved)
            }
          />
        </SectionCard>
      )}
      {experience.data?.presentation && (
        <SectionCard
          title={t("presentation.noticesTitle")}
          description={t("presentation.personalNoticesHint")}
          tour="personal-console-notices"
        >
          <ConsoleNoticeControls
            mode="preference"
            value={experience.data.presentation.preferences}
            ceiling={{
              desktop_install_prompt:
                experience.data.presentation.notices_available.desktop_install_prompt !== false &&
                experience.data.presentation.organization_notices.desktop_install_prompt !== false,
              product_notices:
                experience.data.presentation.notices_available.product_notices !== false &&
                experience.data.presentation.organization_notices.product_notices !== false,
            }}
            disabled={experience.save.isPending}
            onChange={(console) => experience.save.mutate({ console })}
          />
        </SectionCard>
      )}
      <SectionCard title={t("title")} description={t("personalHint")}>
        {experience.isPending ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : experience.error || !experience.data ? (
          <ErrorState cta={{ label: tc("retry"), onClick: () => void experience.refetch() }} />
        ) : (
          <>
            <ChatHomeControls
              mode="inheritance"
              value={experience.data.preferences}
              defaults={defaults}
              availability={experience.data.availability}
              disabled={experience.save.isPending}
              onChange={(field, value) =>
                experience.save.mutate({ preferences: { [field]: value } })
              }
            />
            <Button
              variant="ghost"
              size="sm"
              className="mt-4"
              disabled={
                experience.save.isPending ||
                Object.values(experience.data.preferences).every((value) => value === null)
              }
              onClick={() => experience.save.mutate({ preferences: null })}
            >
              {t("reset")}
            </Button>
          </>
        )}
      </SectionCard>
      <SectionCard
        title={t("costs.title")}
        description={t("costs.personalHint")}
        tour="personal-chat-costs"
      >
        {experience.data?.costs && (
          <PersonalChatCostControl
            policy={experience.data.costs}
            disabled={experience.save.isPending}
            onChange={(chat_costs) => experience.save.mutate({ chat_costs })}
          />
        )}
      </SectionCard>
      <SectionCard title={t("remindersTitle")} description={t("remindersPersonalHint")}>
        {experience.data && (
          <OnboardingReminderControls
            value={experience.data.reminders.preferences}
            available={experience.data.reminders.availability}
            defaults={{
              enabled: experience.data.reminders.organization_defaults.enabled ?? true,
              snooze_days: experience.data.reminders.organization_defaults.snooze_days ?? 1,
            }}
            disabled={experience.save.isPending}
            onChange={(reminders) => experience.save.mutate({ reminders })}
          />
        )}
        {experience.error && (
          <ErrorState cta={{ label: tc("retry"), onClick: () => void experience.refetch() }} />
        )}
      </SectionCard>
    </>
  );
}
