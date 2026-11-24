"use client";

import { useTranslations } from "next-intl";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { SectionCard } from "./settings-section";
import { OnboardingReminderControls } from "./onboarding-reminder-controls";
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
