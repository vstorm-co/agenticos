"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { AppIcon as PanelsTopLeft } from "@/components/icons/product-icons";
import { useArtifacts } from "@/hooks/use-artifacts";
import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";

/** How many pages the column lists before "All pages" takes over. */
const SHOWN = 8;

/**
 * The section of pages an agent published that the caller may open: the most
 * recently published few, then "All pages".
 *
 * The list comes from the same endpoint the Pages page reads, with
 * `mine_or_shared`, so the server decides which pages appear: the caller's own,
 * organization-wide ones, and those shared with them. An admin sees other
 * members' private pages only on the "All pages" page, never here. The section is absent - heading and link included - when the caller
 * lacks `artifacts:view`, and while the list is loading or empty, so a person
 * with no pages never sees an empty "Pages" heading.
 */
export function AppsRows({
  onNavigate,
  collapsed,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  const t = useTranslations("nav");
  const { can } = usePermissions();
  const pathname = stripLocale(usePathname());
  const allowed = can(Perm.artifactsView);
  const { artifacts } = useArtifacts({ limit: SHOWN, mineOrShared: true, enabled: allowed });

  if (!allowed || artifacts.length === 0) return null;

  const allHref = ROUTES.ARTIFACTS;
  const allActive = pathname === allHref;

  return (
    <div className={cn("flex flex-col gap-0.5", collapsed && "w-full items-center")}>
      {collapsed ? (
        <div aria-hidden className="flex h-6 items-center">
          <span className="bg-border h-px w-5" />
        </div>
      ) : (
        <div className="text-muted-foreground flex h-7 items-center px-2.5 text-xs font-medium">
          {t("apps")}
        </div>
      )}
      {artifacts.slice(0, SHOWN).map((app) => {
        const href = ROUTES.ARTIFACT_DETAIL(app.id);
        const active = pathname === href;
        const name = app.title || app.name;
        return (
          <Link
            key={app.id}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? name : undefined}
            aria-label={collapsed ? name : undefined}
            className={cn(
              "touch:min-h-11 focus-visible:ring-ring flex h-8 items-center rounded-xl text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
              collapsed ? "touch:min-w-11 w-8 justify-center" : "gap-2.5 px-2.5",
              active
                ? "bg-accent text-foreground"
                : "text-foreground/80 hover:bg-foreground/5 hover:text-foreground",
            )}
          >
            <PanelsTopLeft className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
            {collapsed ? null : <span className="min-w-0 flex-1 truncate">{name}</span>}
          </Link>
        );
      })}
      <Link
        href={allHref}
        onClick={onNavigate}
        aria-current={allActive ? "page" : undefined}
        title={collapsed ? t("allApps") : undefined}
        aria-label={collapsed ? t("allApps") : undefined}
        className={cn(
          "touch:min-h-11 focus-visible:ring-ring flex h-8 items-center rounded-xl text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
          collapsed ? "touch:min-w-11 w-8 justify-center" : "gap-2.5 px-2.5",
          allActive
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
        )}
      >
        <PanelsTopLeft className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
        {collapsed ? null : <span className="truncate">{t("allApps")}</span>}
      </Link>
    </div>
  );
}
