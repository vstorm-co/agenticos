"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Star } from "lucide-react";

import { AppIcon as PanelsTopLeft } from "@/components/icons/product-icons";
import { useArtifacts, useToggleArtifactFavourite } from "@/hooks/use-artifacts";
import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";

/** How many starred apps the column lists before "All apps" takes over. */
const SHOWN = 8;

/**
 * The apps the caller starred, in the sidebar: a star pins an app here, and a
 * hover on its row unstars it. "All apps" stays below them, always.
 *
 * The list comes from the same endpoint the Apps page reads, with
 * `mine_or_shared` and `favourites`, so the server decides which apps appear.
 * With nothing starred the column says how to pin one and still links to
 * "All apps". The whole section is absent when the caller lacks
 * `artifacts:view`; the server refuses that list to them anyway.
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
  const { artifacts } = useArtifacts({
    limit: SHOWN,
    mineOrShared: true,
    favourites: true,
    enabled: allowed,
  });
  const toggle = useToggleArtifactFavourite();
  const tArtifacts = useTranslations("artifacts");

  if (!allowed) return null;

  const allHref = ROUTES.ARTIFACTS;
  const allActive = pathname === allHref;
  const linkClass = cn(
    "touch:min-h-11 focus-visible:ring-ring flex h-8 items-center rounded-xl text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
    collapsed ? "touch:min-w-11 w-8 justify-center" : "min-w-0 flex-1 gap-2.5 px-2.5",
  );

  return (
    <div
      data-tour={artifacts.length > 0 ? "nav-pinned" : undefined}
      className={cn("flex flex-col gap-0.5", collapsed && "w-full items-center")}
    >
      {collapsed ? (
        <div aria-hidden className="flex h-6 items-center">
          <span className="bg-border h-px w-5" />
        </div>
      ) : (
        <div className="text-muted-foreground flex h-7 items-center px-2.5 text-xs font-medium">
          {t("apps")}
        </div>
      )}
      {artifacts.length === 0 && !collapsed && (
        <p className="text-muted-foreground px-2.5 py-1 text-xs leading-relaxed">
          {t.rich("noFavouriteApps", {
            link: (chunks) => (
              <Link href={allHref} onClick={onNavigate} className="text-foreground underline">
                {chunks}
              </Link>
            ),
          })}
        </p>
      )}
      {artifacts.slice(0, SHOWN).map((app) => {
        const href = ROUTES.ARTIFACT_DETAIL(app.id);
        const active = pathname === href || pathname.startsWith(`${href}/`);
        const name = app.title || app.name;
        return (
          <div key={app.id} className="group relative flex w-full items-center">
            <Link
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              title={collapsed ? name : undefined}
              aria-label={collapsed ? name : undefined}
              className={cn(
                linkClass,
                !collapsed && "pr-8",
                active
                  ? "bg-accent text-foreground"
                  : "text-foreground/80 hover:bg-foreground/5 hover:text-foreground",
              )}
            >
              <PanelsTopLeft
                className="h-[18px] w-[18px] shrink-0"
                strokeWidth={1.75}
                aria-hidden
              />
              {collapsed ? null : <span className="min-w-0 flex-1 truncate">{name}</span>}
            </Link>
            {!collapsed && (
              <button
                type="button"
                aria-label={tArtifacts("removeFavouriteNamed", { name })}
                title={tArtifacts("removeFavourite")}
                disabled={toggle.isPending}
                onClick={() => toggle.mutate({ id: app.id, favourite: false })}
                className="text-warning focus-visible:ring-ring hover:bg-foreground/5 absolute top-1/2 right-1 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md opacity-100 transition-opacity outline-none focus-visible:ring-2 disabled:opacity-50 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
              >
                <Star className="h-3.5 w-3.5 fill-current" aria-hidden />
              </button>
            )}
          </div>
        );
      })}
      <Link
        href={allHref}
        onClick={onNavigate}
        aria-current={allActive ? "page" : undefined}
        title={collapsed ? t("allApps") : undefined}
        aria-label={collapsed ? t("allApps") : undefined}
        className={cn(
          linkClass,
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
