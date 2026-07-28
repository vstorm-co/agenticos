import { KeyRound, Mail, UserPlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { SectionCard } from "@/components/settings/settings-section";

/**
 * What this deployment emails, and why none of it is a switch.
 *
 * This page used to offer four toggles - Billing, Team activity, Security
 * alerts, Product updates - over two channels, a Save button and a
 * "Notification preferences saved" toast. It wrote to `localStorage`. No
 * notification-preference model existed on the server, so nothing was saved
 * anywhere a sender could read it: turning a toggle off did not stop an email,
 * and the setting did not survive a different browser. The toast claimed a
 * success that had not happened.
 *
 * The categories were wrong on top of that. This deployment has no billing and
 * no newsletter, so `Billing` and `Product updates` metered mail that cannot
 * exist, while the three emails it does send were named nothing like any of the
 * four.
 *
 * A statement of what is actually sent is worth more than a control that lies,
 * so that is what this page is until there is a notification a recipient can
 * genuinely decline. When one arrives, its toggle belongs here and the check
 * belongs in `EmailService.send` - at the send site, not in this component. A
 * preference the sender does not consult is the same facade in another table.
 */

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
  return (
    <div className="space-y-6">
      <SectionCard
        title="Email from this deployment"
        description="Every email AgenticOS sends, what triggers it, and why none of them is optional."
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

      <SectionCard title="Preferences" description="Why this page has no controls yet.">
        <p className="text-muted-foreground text-xs leading-relaxed">
          A preference is only real once something consults it before sending. All three emails
          above are transactional - they carry access to your account or to an organization - so
          there is nothing here a toggle could switch off without breaking it. Controls appear on
          this page when the first genuinely optional notification does; the leading candidate is an
          alert when an organization approaches its monthly spend limit, which needs a spend cap to
          exist and a scheduled job to evaluate it.
        </p>
      </SectionCard>
    </div>
  );
}
