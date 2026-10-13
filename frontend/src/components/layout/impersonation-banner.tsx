"use client";

import { Loader2, UserCog } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImpersonation } from "@/hooks/use-impersonation";

/**
 * The strip that says this browser is acting as somebody else, and ends it.
 *
 * Persistent and unmissable on purpose: everything done while it is showing is
 * recorded as the administrator's, against an account that is not theirs, and
 * a tab left open is an account left open. It is not dismissible, unlike the
 * announcement banner beside it - the only way to make it go away is to stop
 * (#1044).
 *
 * Above the whole shell rather than inside the page, so it stays put across
 * navigation and above the sidebar: the sidebar names the account being acted
 * as, and this is what says that name is not the reader's own.
 */
export function ImpersonationBanner() {
  const t = useTranslations("layout");
  const locale = useLocale();
  const { impersonation, actingAs, end, ending } = useImpersonation();

  if (!impersonation || !actingAs) return null;

  const endsAt = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(impersonation.expires_at),
  );

  return (
    <div
      role="status"
      className="border-warning/40 bg-warning/10 text-foreground flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2 text-sm"
    >
      <UserCog className="h-4 w-4 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">
        {t("impersonationActingAs", {
          target: actingAs.email,
          admin: impersonation.impersonator.email,
        })}
      </p>
      <span className="text-muted-foreground text-xs">
        {t("impersonationEndsAt", { time: endsAt })}
      </span>
      <Button variant="outline" size="sm" onClick={() => void end()} disabled={ending}>
        {ending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />}
        {t("endImpersonation")}
      </Button>
    </div>
  );
}
