"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * Why the assistant's buttons are off, and where to turn it on.
 *
 * Whoever may change the switch is linked to it; anybody else is told who can.
 */
export function AiOffNotice({ orgId }: { orgId: string }) {
  const t = useTranslations("authoring.aiOff");
  const { can } = usePermissions();
  return (
    <p role="status" className="text-muted-foreground flex items-start gap-2 text-sm">
      <Sparkles className="text-primary mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>
        {t("body")}{" "}
        {can(Perm.orgSettings) ? (
          <Link href={ROUTES.ORG_MEMBERS(orgId)} className="font-medium underline">
            {t("enable")}
          </Link>
        ) : (
          t("askAdmin")
        )}
      </span>
    </p>
  );
}
