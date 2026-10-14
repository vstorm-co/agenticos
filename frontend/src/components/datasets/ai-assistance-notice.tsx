"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useOrganizations } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * Why a model will not help here, and the way to change that.
 *
 * Nothing while AI assistance is on. Off, somebody who may change the switch is
 * sent to it; anybody else is told who can. `body` says what is off; the judge's
 * sentence when it is left out.
 */
export function AiAssistanceNotice({ body }: { body?: string }) {
  const t = useTranslations("datasets.scoring.aiOff");
  const { activeOrg } = useOrganizations();
  const { can } = usePermissions();
  if (activeOrg === null || activeOrg.ai_assistance_enabled) return null;

  return (
    <p className="bg-muted rounded-md px-3 py-2 text-xs">
      {body ?? t("body")}{" "}
      {can(Perm.orgSettings) ? (
        <Link href={ROUTES.ORG_MEMBERS(activeOrg.id)} className="font-medium underline">
          {t("enable")}
        </Link>
      ) : (
        t("askAdmin")
      )}
    </p>
  );
}
