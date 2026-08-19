"use client";

import { Info, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";

/**
 * What this deployment's sign-up rule is, said before somebody types.
 *
 * The backend refuses the registration either way. The point of saying it here is
 * that a form which accepts an address and *then* reports "that email domain
 * cannot register" is a form that lies - the visitor has no way to know the rule
 * exists, and reads the refusal as the product being broken.
 *
 * Returns nothing on an open deployment with no domain list, which is the default
 * and the shape most installations keep. `closed` is handled by the form itself,
 * which does not render at all - and somebody arriving with an invitation is told
 * that instead, because the warnings below are addressed to people who have none.
 */
export function SignupPolicyNotice({ invited = false }: { invited?: boolean }) {
  const t = useTranslations("auth");
  const { signupMode, allowedEmailDomains } = useBranding();

  // Somebody holding an invitation is not the audience for "ask an administrator to
  // invite you", and the domain list does not apply to them either - an invitation
  // overrides it, which is the policy's rule and not this component's guess.
  if (invited) {
    return (
      <div className="border-border bg-muted/40 text-foreground/75 flex items-start gap-2.5 rounded-xl border p-3 text-xs">
        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <p>{t("signupWithInvitation")}</p>
      </div>
    );
  }

  const inviteOnly = signupMode === "invite_only";
  const narrowed = allowedEmailDomains.length > 0;
  if (!inviteOnly && !narrowed) return null;

  return (
    <div className="border-border bg-muted/40 text-foreground/75 flex items-start gap-2.5 rounded-xl border p-3 text-xs">
      {inviteOnly ? (
        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : (
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      <div className="space-y-1">
        {inviteOnly && <p>{t("signupInviteOnly")}</p>}
        {narrowed && (
          <p>{t("signupDomainsAllowed", { domains: allowedEmailDomains.join(", ") })}</p>
        )}
      </div>
    </div>
  );
}
