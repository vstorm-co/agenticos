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
 * which does not render at all.
 */
export function SignupPolicyNotice() {
  const t = useTranslations("auth");
  const { signupMode, allowedEmailDomains } = useBranding();

  const invited = signupMode === "invite_only";
  const narrowed = allowedEmailDomains.length > 0;
  if (!invited && !narrowed) return null;

  return (
    <div className="border-border bg-muted/40 text-foreground/75 flex items-start gap-2.5 rounded-xl border p-3 text-xs">
      {invited ? (
        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : (
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      <div className="space-y-1">
        {invited && <p>{t("signupInviteOnly")}</p>}
        {narrowed && (
          <p>{t("signupDomainsAllowed", { domains: allowedEmailDomains.join(", ") })}</p>
        )}
      </div>
    </div>
  );
}
