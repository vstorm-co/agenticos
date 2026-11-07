"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import { useCanCreateTrigger } from "@/hooks/use-can-create-trigger";
import { StartTeam } from "./start-team";
import { Perm } from "@/types/permissions";

export function StartNextSteps({ orgId }: { orgId: string }) {
  const t = useTranslations("start");
  const { can } = usePermissions();
  const canCreateTrigger = useCanCreateTrigger();
  const actions = [
    { key: "files", href: "/chat" },
    ...(can(Perm.agentsEdit) ? [{ key: "build", href: "/agents" }] : []),
    { key: "connect", href: "/settings/mcp" },
    ...(canCreateTrigger ? [{ key: "repeat", href: "/routines" }] : []),
    ...(can(Perm.membersManage) ? [{ key: "team", href: `/orgs/${orgId}/members` }] : []),
  ];
  return (
    <>
      <section className="space-y-3 rounded-xl border p-5">
        <h2 className="font-semibold">{t("extrasTitle")}</h2>
        <p className="text-muted-foreground text-sm">{t("savedHint")}</p>
        <div className="flex flex-wrap gap-3">
          {actions.map((action) => (
            <Link
              key={action.key}
              href={action.href}
              className="rounded-lg border px-3 py-2 text-sm"
            >
              {t(action.key)}
            </Link>
          ))}
        </div>
        {can(Perm.membersManage) && (
          <p className="text-muted-foreground text-xs">{t("teamHint")}</p>
        )}
      </section>
      {can(Perm.membersManage) && <StartTeam orgId={orgId} />}
    </>
  );
}
