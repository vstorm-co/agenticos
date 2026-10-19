"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAiAssistance } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * Why the judge will not grade here, and the way to change that.
 *
 * Nothing while AI assistance is on, or before it is known. Off, somebody who
 * may change the switch is sent to it; anybody else is told who can.
 */
export function AiAssistanceNotice() {
  const t = useTranslations("datasets.scoring.aiOff");
  const { orgId, enabled } = useAiAssistance();
  const { can } = usePermissions();
  if (orgId === null || enabled !== false) return null;

  return (
    <div
      role="status"
      className="border-primary/30 bg-primary/5 flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
    >
      <Sparkles className="text-primary mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <p>
        {t("body")}{" "}
        {can(Perm.orgSettings) ? (
          <Link href={ROUTES.ORG_MEMBERS(orgId)} className="font-medium underline">
            {t("enable")}
          </Link>
        ) : (
          t("askAdmin")
        )}
      </p>
    </div>
  );
}
