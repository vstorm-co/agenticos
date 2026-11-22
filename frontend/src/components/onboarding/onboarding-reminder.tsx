"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ArrowRight, Compass, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { cn } from "@/lib/utils";
import styles from "./onboarding-reminder.module.css";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { useStart } from "@/hooks/use-start";
import { useAuthStore } from "@/stores";
import { useOnboardingResume } from "./onboarding-resume-link";
import { useOnboardingReminderPolicy } from "@/components/settings/console-experience-provider";

/** Completion, reminder policy and snooze timing are server-owned, never local UI storage. */
export function OnboardingReminder({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const policy = useOnboardingReminderPolicy();
  const { href, userId, orgId } = useOnboardingResume();
  const userLoading = useAuthStore((state) => state.isLoading);
  const state = useStart(!userLoading && policy.enabled);
  useEffect(() => {
    if (
      userId &&
      orgId &&
      !state.error &&
      state.data?.organization_id === orgId &&
      state.data.completed
    )
      useOnboardingLocationStore.getState().clearStartLocation(userId, orgId);
  }, [userId, orgId, state.error, state.data]);
  const t = useTranslations("start.sidebarReminder");
  if (
    !policy.enabled ||
    userLoading ||
    state.waitingForScope ||
    state.isLoading ||
    state.error ||
    !state.data ||
    state.data.organization_id !== orgId ||
    state.data.completed
  )
    return null;

  if (collapsed || state.data.dismissed)
    return (
      <Link
        href={href}
        onClick={onNavigate}
        title={collapsed ? t("title") : undefined}
        aria-label={collapsed ? t("title") : undefined}
        className={
          collapsed
            ? "text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 mx-auto mb-1 grid size-9 shrink-0 place-items-center rounded-lg outline-none focus-visible:ring-2"
            : "text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 mx-3 mb-2 flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs outline-none focus-visible:ring-2"
        }
      >
        <span className={cn(styles.railMark, !state.data.dismissed && styles.unfinished)}>
          <Compass className="size-4 shrink-0" aria-hidden />
        </span>
        {!collapsed && t("title")}
      </Link>
    );

  return (
    <section aria-label={t("title")} className={styles.card}>
      <div className={styles.heading}>
        <span className={styles.artwork} aria-hidden="true">
          <AvatarFace seed="agenticos" background={false} />
          <span className={styles.spark} />
        </span>
        <h3>{t("heading")}</h3>
        <button
          type="button"
          disabled={state.save.isPending}
          onClick={() => state.save.mutate({ dismissed: true })}
          aria-label={t("snoozeDays", { days: policy.snooze_days })}
          title={t("snoozeDays", { days: policy.snooze_days })}
          className={styles.dismiss}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      <p className={styles.hint}>{t("hint")}</p>
      <Link href={href} onClick={onNavigate} className={styles.action}>
        {t("title")}
        <ArrowRight className="size-3.5" aria-hidden />
      </Link>
      {state.save.isError && (
        <p role="alert" className="text-destructive mt-2 text-xs">
          {t("saveFailed")}
        </p>
      )}
    </section>
  );
}
