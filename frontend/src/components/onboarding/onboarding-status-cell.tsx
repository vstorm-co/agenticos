"use client";

import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui";
import { formatDate, formatDateTime } from "@/lib/utils";
import type {
  OnboardingProgressStatus,
  OrganizationOnboardingStatus,
} from "@/types/onboarding-status";

const ADMIN_STEPS = [
  "workspace",
  "identity",
  "profile",
  "context",
  "subscriptions",
  "team",
  "deployment",
  "organization",
  "task",
] as const;
const MEMBER_STEPS = ["welcome", "profile", "context", "subscriptions", "task"] as const;

/** The stored step stays a protocol identifier; tables show the console's own step labels. */
function useStepLabel(step: string | null | undefined): string | null {
  const admin = useTranslations("start.administration");
  const member = useTranslations("start.guided");
  const preferences = useTranslations("start.preferences");
  const experience = useTranslations("start.experience");
  const t = useTranslations("onboardingStatus");
  if (!step) return null;
  if (step === "preferences.language") return preferences("languageTitle");
  if (step === "preferences.appearance") return preferences("appearanceTitle");
  if (step === "admin.models" || step === "member.models") return experience("modelsTitle");
  if (step === "admin.tools" || step === "member.tools") return experience("toolsTitle");
  const adminStep = ADMIN_STEPS.find((key) => step === `admin.${key}`);
  if (adminStep) return admin(adminStep);
  const memberStep = MEMBER_STEPS.find((key) => step === `member.${key}`);
  return memberStep ? member(`memberStep.${memberStep}`) : t("otherStep");
}

export function OnboardingStatusCell({
  completed_at,
  current_step,
  updated_at,
}: OnboardingProgressStatus) {
  const t = useTranslations("onboardingStatus");
  const locale = useLocale();
  const step = useStepLabel(current_step);
  const status = completed_at
    ? "completed"
    : current_step || updated_at
      ? "inProgress"
      : completed_at === undefined && current_step === undefined && updated_at === undefined
        ? "unknown"
        : "notStarted";
  const timestamp = completed_at || updated_at;
  return (
    <div
      className="flex min-w-0 flex-col items-start gap-1"
      title={timestamp ? formatDateTime(timestamp, locale) : undefined}
    >
      <Badge
        variant="outline"
        className={
          status === "completed"
            ? "border-success/20 bg-success/10 text-success font-normal"
            : "border-border text-muted-foreground font-normal"
        }
      >
        {t(status)}
      </Badge>
      {completed_at ? (
        <time dateTime={completed_at} className="text-muted-foreground text-xs">
          {formatDate(completed_at, locale)}
        </time>
      ) : step ? (
        <span className="text-muted-foreground text-xs">{step}</span>
      ) : null}
    </div>
  );
}

/** App admins see each membership independently, never an invented global completion. */
export function UserOnboardingStatusCell({
  onboarding,
  completedAt,
}: {
  onboarding?: OrganizationOnboardingStatus[];
  completedAt?: string | null;
}) {
  const t = useTranslations("onboardingStatus");
  if (onboarding === undefined) return <OnboardingStatusCell />;
  if (onboarding.length === 0)
    return (
      <div className="text-muted-foreground grid gap-1 text-xs">
        <span>{completedAt ? t("account") : t("noWorkspace")}</span>
        <OnboardingStatusCell completed_at={completedAt ?? null} />
      </div>
    );
  return (
    <ul className="grid max-w-64 min-w-40 gap-3">
      {onboarding.map((entry) => (
        <li key={entry.organization_id} className="grid gap-1">
          <span className="text-foreground text-xs font-medium">{entry.organization_name}</span>
          <OnboardingStatusCell {...entry} />
        </li>
      ))}
    </ul>
  );
}
