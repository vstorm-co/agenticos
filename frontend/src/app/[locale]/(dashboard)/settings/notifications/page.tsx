"use client";

import { useState } from "react";
import { CircleDollarSign, Hand, KeyRound, Mail, PieChart, UserPlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { Switch } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import { useTranslations } from "next-intl";

/**
 * Every toggle on this page controls a real send.
 *
 * The rule this page lives by: a preference is only real once something
 * consults it before sending. Each switch below writes one `notify_*` column
 * through PATCH `/users/me`, and `NotificationService` filters recipients on
 * that column before an email leaves - the wiring is tested on both sides
 * (`backend/tests/test_notifications.py` pins the refusal). A switch with no
 * sender behind it does not belong here; this page once had four of those,
 * saving to localStorage that nothing read.
 *
 * The transactional emails are listed without switches on purpose: each one
 * carries access to an account or an organization, so the honest control is
 * no control, with the reason stated.
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

export default function NotificationsSettingsPage() {
  const tErrors = useTranslations("errors");

  const t = useTranslations("pages.settings");
  const { user } = useAuth();
  const { setUser } = useAuthStore();
  const [saving, setSaving] = useState<PreferenceKey | null>(null);

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
          <li>
            <span className="text-foreground/70 font-medium">{t("noAppNotifications")}</span>
            {t("thereNoNotificationFeed")}
          </li>
        </ul>
      </SectionCard>
    </div>
  );
}
