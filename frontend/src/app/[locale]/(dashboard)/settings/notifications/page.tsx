"use client";

import { useState } from "react";
import {
  Bell,
  CircleDollarSign,
  FileCheck2,
  FileX2,
  Hand,
  KeyRound,
  Mail,
  Megaphone,
  PieChart,
  UserPlus,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { Switch } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth, useNotificationPreferences } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import type { NotificationChannel } from "@/lib/notification-preferences-api";
import { useTranslations } from "next-intl";

/**
 * Every toggle on this page controls a real send.
 *
 * The rule this page lives by: a preference is only real once something
 * consults it before sending. The first section's three switches each write
 * one `notify_*` column through PATCH `/users/me`; the second section's
 * switches PATCH `/notifications/preferences`, one `(event_type, channel)`
 * row at a time. Both are wired on both sides
 * (`backend/tests/test_notifications.py`,
 * `backend/tests/integration/test_notification_center.py`). A switch with no
 * sender behind it does not belong here; this page once had four of those,
 * saving to localStorage that nothing read.
 *
 * The transactional emails are listed without switches on purpose: each one
 * carries access to an account or an organization, so the honest control is
 * no control, with the reason stated. `security_event`/`configuration_changed`
 * are the same shape, one layer up (#1598, Decision 4) - mandatory, and so
 * never offered a toggle by `GET /notifications/preferences` either.
 */

type PreferenceKey = "notify_budget_alerts" | "notify_approval_requests" | "notify_usage_reports";

interface OptionalEmail {
  key: PreferenceKey;
  /** Catalog key: the name, plus `Trigger` and `Audience` for its two sentences. */
  words: string;
  icon: LucideIcon;
}

const OPTIONAL_EMAILS: readonly OptionalEmail[] = [
  { key: "notify_budget_alerts", words: "optionalBudget", icon: CircleDollarSign },
  { key: "notify_approval_requests", words: "optionalApprovals", icon: Hand },
  { key: "notify_usage_reports", words: "optionalUsage", icon: PieChart },
];

interface SentEmail {
  key: string;
  /** Catalog key: the name, plus `Trigger` and `Reason`. Every entry needs a reason;
   * that is the point of the section. */
  words: string;
  icon: LucideIcon;
}

const SENT_EMAILS: readonly SentEmail[] = [
  { key: "welcome", words: "sentWelcome", icon: Mail },
  { key: "password_reset", words: "sentPasswordReset", icon: KeyRound },
  { key: "invitation", words: "sentInvitation", icon: UserPlus },
];

interface PreferenceEvent {
  /** The backend's own `NotificationEventType` value. */
  eventType: string;
  /** Catalog key: the name, plus `Trigger` - the same suffix `OPTIONAL_EMAILS`
   * uses, so the three events that reuse those keys need no key of their own. */
  words: string;
  icon: LucideIcon;
  /** Which channels `GET /notifications/preferences` offers for this event -
   * a subset of `["in_app", "email"]`, per Decision 4's togglable-pairs rule. */
  channels: readonly NotificationChannel[];
}

const PREFERENCE_EVENTS: readonly PreferenceEvent[] = [
  {
    eventType: "run_completed",
    words: "prefRunCompleted",
    icon: Bell,
    channels: ["in_app", "email"],
  },
  { eventType: "run_failed", words: "prefRunFailed", icon: XCircle, channels: ["in_app", "email"] },
  {
    eventType: "ingestion_completed",
    words: "prefIngestionCompleted",
    icon: FileCheck2,
    channels: ["in_app", "email"],
  },
  {
    eventType: "ingestion_failed",
    words: "prefIngestionFailed",
    icon: FileX2,
    channels: ["in_app", "email"],
  },
  // These three reuse `OPTIONAL_EMAILS`' own catalog keys: same event, same
  // name and trigger sentence, just this event's *in-app* channel rather
  // than its email one - `notify_budget_alerts` and friends above already
  // cover email, and `GET /notifications/preferences` never offers it again.
  {
    eventType: "budget_exceeded",
    words: "optionalBudget",
    icon: CircleDollarSign,
    channels: ["in_app"],
  },
  { eventType: "approval_requested", words: "optionalApprovals", icon: Hand, channels: ["in_app"] },
  { eventType: "usage_report", words: "optionalUsage", icon: PieChart, channels: ["in_app"] },
  {
    eventType: "agent_usage_report",
    words: "prefAgentUsageReport",
    icon: PieChart,
    channels: ["in_app"],
  },
  {
    eventType: "announcement",
    words: "prefAnnouncement",
    icon: Megaphone,
    channels: ["in_app", "email"],
  },
];

export default function NotificationsSettingsPage() {
  const tErrors = useTranslations("errors");

  const t = useTranslations("pages.settings");
  const { user } = useAuth();
  const { setUser } = useAuthStore();
  const [saving, setSaving] = useState<PreferenceKey | null>(null);
  const {
    isEnabled,
    setPreference,
    isLoading: preferencesLoading,
    error: preferencesError,
  } = useNotificationPreferences();
  const [pending, setPending] = useState<Set<string>>(new Set());

  if (!user) {
    return null;
  }

  const handleToggle = async (key: PreferenceKey, enabled: boolean) => {
    setSaving(key);
    try {
      const updated = await apiClient.patch<User>("/users/me", { [key]: enabled });
      setUser(updated);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedSavePreference"),
      );
    } finally {
      setSaving(null);
    }
  };

  const handlePreferenceToggle = async (
    eventType: string,
    channel: NotificationChannel,
    enabled: boolean,
  ) => {
    const pendingKey = `${eventType}:${channel}`;
    setPending((prev) => new Set(prev).add(pendingKey));
    try {
      await setPreference(eventType, channel, enabled);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedSavePreference"),
      );
    } finally {
      setPending((prev) => {
        const next = new Set(prev);
        next.delete(pendingKey);
        return next;
      });
    }
  };

  return (
    <div className="space-y-6">
      <SectionCard title={t("agentActivity")} description={t("emailsAboutRunsNobody")}>
        <ul className="divide-border divide-y">
          {OPTIONAL_EMAILS.map((email) => (
            <li key={email.key} className="flex items-start gap-3 py-4 first:pt-0 last:pb-0">
              <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <email.icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-foreground text-sm font-medium">{t(email.words)}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {t(`${email.words}Trigger`)}
                </p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {t(`${email.words}Audience`)}
                </p>
              </div>
              <Switch
                aria-label={t(email.words)}
                checked={user[email.key] ?? true}
                disabled={saving !== null}
                onCheckedChange={(enabled) => handleToggle(email.key, enabled)}
              />
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard
        title={t("notificationPreferences")}
        description={t("notificationPreferencesDescription")}
      >
        {preferencesError ? (
          // A failed read has no stored values either, and showing every
          // switch as on regardless of what is actually saved is a refusal
          // dressed as a preference (#32's shape).
          <ErrorState description={preferencesError} />
        ) : (
          <ul className="divide-border divide-y">
            {PREFERENCE_EVENTS.map((event) => (
              <li
                key={event.eventType}
                className="flex items-start gap-3 py-4 first:pt-0 last:pb-0"
              >
                <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                  <event.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-foreground text-sm font-medium">{t(event.words)}</p>
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    {t(`${event.words}Trigger`)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-4">
                  {event.channels.map((channel) => {
                    const pendingKey = `${event.eventType}:${channel}`;
                    const label = `${t(event.words)} - ${t(
                      channel === "in_app" ? "inAppChannel" : "emailChannel",
                    )}`;
                    return (
                      <div key={channel} className="flex flex-col items-center gap-1">
                        <span className="text-muted-foreground text-[10px] tracking-wide uppercase">
                          {t(channel === "in_app" ? "inAppChannel" : "emailChannel")}
                        </span>
                        <Switch
                          aria-label={label}
                          checked={isEnabled(event.eventType, channel)}
                          disabled={preferencesLoading || pending.has(pendingKey)}
                          onCheckedChange={(enabled) =>
                            handlePreferenceToggle(event.eventType, channel, enabled)
                          }
                        />
                      </div>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard title={t("alwaysSent")} description={t("transactionalEmailsWhatTriggers")}>
        <ul className="divide-border divide-y">
          {SENT_EMAILS.map((email) => (
            <li key={email.key} className="flex gap-3 py-4 first:pt-0 last:pb-0">
              <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <email.icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 space-y-1">
                <p className="text-foreground text-sm font-medium">{t(email.words)}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {t(`${email.words}Trigger`)}
                </p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  <span className="text-foreground/70 font-medium">{t("notOptional")}</span>
                  {t(`${email.words}Reason`)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard title={t("whatNotSent")} description={t("absencesWorthStatingBecause")}>
        <ul className="text-muted-foreground space-y-2 text-xs leading-relaxed">
          <li>
            <span className="text-foreground/70 font-medium">{t("noMarketingEmail")}</span>
            {t("selfHostedDeploymentThere")}
          </li>
          <li>
            <span className="text-foreground/70 font-medium">{t("noBillingEmail")}</span>
            {t("nothingHereChargesYou")}
          </li>
        </ul>
      </SectionCard>
    </div>
  );
}
