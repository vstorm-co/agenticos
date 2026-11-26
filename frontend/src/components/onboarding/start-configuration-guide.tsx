"use client";

import Link from "next/link";
import {
  Building2,
  ChevronDown,
  FolderOpen,
  Package,
  SlidersHorizontal,
  Workflow,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores/org-store";
import { Perm } from "@/types/permissions";

/** Optional discovery after setup; no choice here blocks completion or changes settings. */
export function StartConfigurationGuide() {
  const t = useTranslations("start.configurationGuide");
  const { can } = usePermissions();
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const options = [
    {
      id: "preferences" as const,
      href: ROUTES.SETTINGS_PROFILE,
      icon: SlidersHorizontal,
      visible: true,
    },
    {
      id: "projects" as const,
      href: ROUTES.PROJECTS,
      icon: FolderOpen,
      visible: can(Perm.projectsView),
    },
    {
      id: "transfer" as const,
      href: ROUTES.AGENTS,
      icon: Package,
      visible: can(Perm.agentsView),
    },
    {
      id: "workflow" as const,
      href: ROUTES.WORKFLOWS,
      icon: Workflow,
      visible: can(Perm.workflowsView),
    },
    {
      id: "organization" as const,
      href: organizationId ? `${ROUTES.ORG_MEMBERS(organizationId)}?tab=assistant` : ROUTES.ORGS,
      icon: Building2,
      visible: organizationId !== null && can(Perm.orgSettings),
    },
  ];
  return (
    <details
      className="group border-border rounded-xl border text-sm"
      data-tour="start-configuration-guide"
    >
      <summary className="focus-visible:outline-ring flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 font-medium focus-visible:outline-2 [&::-webkit-details-marker]:hidden">
        {t("title")}
        <ChevronDown
          className="text-muted-foreground size-4 shrink-0 group-open:rotate-180"
          aria-hidden
        />
      </summary>
      <div className="space-y-3 px-4 pb-4">
        <p className="text-muted-foreground text-xs leading-relaxed">{t("hint")}</p>
        <ul className="divide-border divide-y">
          {options
            .filter((option) => option.visible)
            .map(({ id, href, icon: Icon }) => (
              <li key={id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                <Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden />
                <div className="min-w-0 space-y-1">
                  <Link
                    href={href}
                    className="focus-visible:outline-ring font-medium underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2"
                  >
                    {t(`${id}Title`)}
                  </Link>
                  <p className="text-muted-foreground text-xs leading-relaxed">{t(`${id}Body`)}</p>
                </div>
              </li>
            ))}
        </ul>
      </div>
    </details>
  );
}
