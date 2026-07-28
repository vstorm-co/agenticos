"use client";

import { useState } from "react";
import { CircleDollarSign, Hand, KeyRound, Mail, PieChart, UserPlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { Switch } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

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
  label: string;
  trigger: string;
  audience: string;
  icon: LucideIcon;
}

const OPTIONAL_EMAILS: readonly OptionalEmail[] = [
  {
    key: "notify_budget_alerts",
    label: "Budget alerts",
    trigger: "An agent run stops because a spending limit was reached.",
    audience: "Sent to organization owners and admins, and to the agent's owner.",
    icon: CircleDollarSign,
  },
  {
    key: "notify_approval_requests",
    label: "Approval requests",
    trigger: "A run parks because a tool call is waiting for a person to approve it.",
    audience: "Sent to whoever started the run; for scheduled runs, to owners and admins.",
    icon: Hand,
  },
  {
    key: "notify_usage_reports",
    label: "Usage reports",
    trigger: "Weekly and monthly, when your organization's agents ran anything at all.",
    audience: "Sent to organization owners and admins. A period with zero runs sends nothing.",
    icon: PieChart,
  },
];

interface SentEmail {
  key: string;
  label: string;
  trigger: string;
  /** Why this is not a preference. Every entry needs one; that is the point. */
  reason: string;
  icon: LucideIcon;
}

const SENT_EMAILS: readonly SentEmail[] = [
  {
    key: "welcome",
    label: "Welcome",
    trigger: "Once, when your account is created - and again for each sign-in link you request.",
    reason:
      "It is sent while the account is being created, before there is anywhere to record a preference, and the sign-in link is how you get in.",
    icon: Mail,
  },
  {
    key: "password_reset",
    label: "Password reset",
    trigger: "Each time someone asks for a reset link for your address.",
    reason:
      "Security mail is not a preference. Switching this off would leave you unable to recover your own account, so the control does not exist rather than existing and being dangerous.",
    icon: KeyRound,
  },
  {
    key: "invitation",
    label: "Organization invitation",
    trigger: "When a member invites an email address to an organization.",
    reason:
      "It goes to the person being invited, who often has no account here yet - there is no recipient whose preference could be consulted.",
    icon: UserPlus,
  },
];

export default function NotificationsSettingsPage() {
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
      toast.error(err instanceof ApiError ? err.message : "Failed to save preference");
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="space-y-6">
      <SectionCard
        title="Agent activity"
        description="Emails about runs nobody is watching. Each switch is checked before the email is sent."
      >
        <ul className="divide-border divide-y">
          {OPTIONAL_EMAILS.map((email) => (
            <li key={email.key} className="flex items-start gap-3 py-4 first:pt-0 last:pb-0">
              <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <email.icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-foreground text-sm font-medium">{email.label}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">{email.trigger}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">{email.audience}</p>
              </div>
              <Switch
                aria-label={email.label}
                checked={user[email.key] ?? true}
                disabled={saving !== null}
                onCheckedChange={(enabled) => handleToggle(email.key, enabled)}
              />
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard
        title="Always sent"
        description="The transactional emails, what triggers each, and why none of them is optional."
      >
        <ul className="divide-border divide-y">
          {SENT_EMAILS.map((email) => (
            <li key={email.key} className="flex gap-3 py-4 first:pt-0 last:pb-0">
              <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <email.icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 space-y-1">
                <p className="text-foreground text-sm font-medium">{email.label}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">{email.trigger}</p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  <span className="text-foreground/70 font-medium">Not optional - </span>
                  {email.reason}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard
        title="What is not sent"
        description="Absences worth stating, because a settings page implies the opposite."
      >
        <ul className="text-muted-foreground space-y-2 text-xs leading-relaxed">
          <li>
            <span className="text-foreground/70 font-medium">No marketing email.</span> This is a
            self-hosted deployment. There is no newsletter and no subscriber list.
          </li>
          <li>
            <span className="text-foreground/70 font-medium">No billing email.</span> Nothing here
            charges you, so there are no renewals, payment failures or credit warnings.
          </li>
          <li>
            <span className="text-foreground/70 font-medium">No in-app notifications.</span> There
            is no notification feed to route anything to; activity lives on the pages that own it.
          </li>
        </ul>
      </SectionCard>
    </div>
  );
}
