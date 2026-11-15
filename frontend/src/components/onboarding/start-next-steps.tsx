"use client";

import Link from "next/link";
import { FileText, Bot, Cable, CalendarClock, Users, ArrowUpRight } from "lucide-react";
import styles from "./start.module.css";
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
    { key: "files", href: "/chat", icon: FileText },
    ...(can(Perm.agentsEdit) ? [{ key: "build", href: "/agents", icon: Bot }] : []),
    { key: "connect", href: "/settings/mcp", icon: Cable },
    ...(canCreateTrigger ? [{ key: "repeat", href: "/routines", icon: CalendarClock }] : []),
    ...(can(Perm.membersManage)
      ? [{ key: "team", href: `/orgs/${orgId}/members`, icon: Users }]
      : []),
  ];
  return (
    <>
      <section className={`${styles.panel} ${styles.next} space-y-4`}>
        <h2 className="font-semibold">{t("extrasTitle")}</h2>
        <p className="text-muted-foreground text-sm">{t("savedHint")}</p>
        <div className={styles.nextLinks}>
          {actions.map((action) => (
            <Link key={action.key} href={action.href} className={styles.nextLink}>
              <action.icon size={17} aria-hidden />
              <span className="flex-1">{t(action.key)}</span>
              <ArrowUpRight size={13} aria-hidden />
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
