"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ArrowRight, Compass, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { cn } from "@/lib/utils";
import { pendingSharedStart, startIsComplete } from "@/lib/onboarding/scopes";
import styles from "./onboarding-reminder.module.css";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { useStart } from "@/hooks/use-start";
import { useAuthStore } from "@/stores";
import { useOnboardingResume } from "./onboarding-resume-link";
import { useOnboardingReminderPolicy } from "@/components/settings/console-experience-provider";

/** Completion, reminder policy and snooze timing remain server-owned. */
export function useOnboardingReminder() {
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
      startIsComplete(state.data)
    )
      useOnboardingLocationStore.getState().clearStartLocation(userId, orgId);
  }, [userId, orgId, state.error, state.data]);
  const eligible = Boolean(
    policy.enabled &&
    !userLoading &&
    !state.waitingForScope &&
    !state.isLoading &&
    !state.error &&
    state.data &&
    state.data.organization_id === orgId &&
    (pendingSharedStart(state.data) || (!state.data.completed && !state.data.dismissed)),
  );
  return { eligible, href, state, policy };
}

export function OnboardingReminder(props: { collapsed?: boolean; onNavigate?: () => void }) {
  const reminder = useOnboardingReminder();
  return reminder.eligible ? <OnboardingReminderCard {...props} reminder={reminder} /> : null;
}

export function OnboardingReminderCard({
  collapsed = false,
  onNavigate,
  reminder,
  embedded = false,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
  reminder: ReturnType<typeof useOnboardingReminder>;
  embedded?: boolean;
}) {
  const { href, state, policy } = reminder;
  const t = useTranslations("start.sidebarReminder");
  const scopes = useTranslations("start.scopes");
  const shared =
    state.data?.active_scope === "deployment" || state.data?.active_scope === "organization"
      ? state.data.active_scope
      : null;
  const title = shared ? scopes(`${shared}.title`) : t("title");
  if (collapsed)
    return (
      <Link
        href={href}
        onClick={onNavigate}
        title={title}
        aria-label={title}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 mx-auto mb-1 grid size-9 shrink-0 place-items-center rounded-lg outline-none focus-visible:ring-2"
      >
        <span className={cn(styles.railMark, styles.unfinished)}>
          <Compass className="size-4 shrink-0" aria-hidden />
        </span>
      </Link>
    );

  return (
    <section aria-label={title} className={cn(styles.card, embedded && styles.embedded)}>
      <div className={styles.heading}>
        <span className={styles.artwork} aria-hidden="true">
          <AvatarFace seed="agenticos" background={false} />
          <span className={styles.spark} />
        </span>
        <h3>{shared ? scopes(`${shared}.title`) : t("heading")}</h3>
        {!shared && (
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
        )}
      </div>
      <p className={styles.hint}>{shared ? scopes(`${shared}.hint`) : t("hint")}</p>
      <Link href={href} onClick={onNavigate} className={styles.action}>
        {title}
        <ArrowRight className="size-3.5" aria-hidden />
      </Link>
      {!shared && state.save.isError && (
        <p role="alert" className="text-destructive mt-2 text-xs">
          {t("saveFailed")}
        </p>
      )}
    </section>
  );
}
