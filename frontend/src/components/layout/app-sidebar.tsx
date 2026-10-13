"use client";

/**
 * The primary navigation: a column on the left, present at all times.
 *
 * It replaces a top nav bar, and the reason is not taste. The platform has
 * eleven destinations across four concerns, and a horizontal bar cannot hold
 * them - which is why half of them had ended up behind dropdowns and the other
 * half (Agents, Skills, Activity) had fallen out of the primary nav entirely,
 * reachable only from a mobile drawer nobody opens on a desktop. A column has
 * room to show every destination at once, grouped, with the group label doing
 * the work a dropdown was doing badly.
 *
 * Below `md` it is not rendered here at all: the same links appear in the
 * existing slide-over, because a fixed column is most of a phone screen.
 *
 * What it shows is filtered by permission. That is presentation, never
 * enforcement - the server refuses regardless - but a Viewer given a link to a
 * page that will only refuse them has been told to try something that cannot
 * work. While permissions are loading `can()` answers false, so the sidebar
 * reveals entries rather than briefly offering ones about to disappear.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { BrandLink } from "@/components/layout/brand-link";
import { SidebarShell } from "@/components/layout/sidebar-shell";
import { useMounted } from "@/hooks/use-mounted";
import { usePermissions } from "@/hooks/use-permissions";
import { cn, isAppAdmin } from "@/lib/utils";
import { useAuthStore, useSidebarStore } from "@/stores";
import { NAV_GROUPS, isActive, type NavItem } from "@/lib/nav-sections";

export { NAV_GROUPS, isActive, navSectionFor, type NavDomain } from "@/lib/nav-sections";

function NavLink({
  item,
  onNavigate,
  collapsed = false,
}: {
  item: NavItem;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const pathname = usePathname();
  const t = useTranslations("nav");
  const active = isActive(pathname, item.href);
  const label = t(item.labelKey);

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      data-tour={item.dataTour}
      aria-current={active ? "page" : undefined}
      // On the rail the label is the only thing naming this destination, so it
      // moves to `title` and `aria-label` rather than disappearing - a column
      // of eleven unlabelled icons is a column nobody can read.
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={cn(
        "flex items-center rounded-lg text-sm transition-colors",
        collapsed ? "h-9 w-9 justify-center" : "gap-2.5 px-2.5 py-1.5",
        // Selected is a neutral raised pill with a dark label. Section hues live
        // on the page's own tile, not here: a column of coloured pills competed
        // with the content it points at.
        active
          ? "bg-accent text-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      <item.icon className="h-4 w-4 shrink-0" aria-hidden />
      {collapsed ? null : <span className="truncate">{label}</span>}
    </Link>
  );
}

/**
 * The link list on its own, so the desktop column and the mobile slide-over
 * cannot drift into offering different destinations.
 */
export function SidebarNav({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const { can } = usePermissions();
  const { user } = useAuthStore();
  const t = useTranslations("nav");
  const admin = isAppAdmin(user);

  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.permission || can(item.permission)),
  })).filter((group) => group.items.length > 0 && (!group.adminOnly || admin));

  return (
    <nav
      aria-label={t("primary")}
      className={cn("flex flex-col py-4", collapsed ? "items-center gap-3 px-2" : "gap-5 px-3")}
    >
      {groups.map((group) => (
        <div
          key={group.labelKey ?? "main"}
          className={cn("flex flex-col gap-0.5", collapsed && "w-full items-center gap-1")}
        >
          {group.labelKey &&
            // The heading is what tells the four groups apart, and on the rail
            // there is no room for the word. A rule does the same job: it says
            // "a different kind of thing starts here" without claiming to say
            // which, which an abbreviation would do badly.
            (collapsed ? (
              <div aria-hidden className="bg-border mb-1 h-px w-5" />
            ) : (
              <div className="text-muted-foreground px-2.5 pb-1.5 text-xs font-medium tracking-wide uppercase">
                {t(group.labelKey)}
              </div>
            ))}
          {group.items.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
          ))}
        </div>
      ))}
    </nav>
  );
}

export function AppSidebar() {
  const t = useTranslations("nav");
  // The stored value only after mount. `persist` reads `localStorage`
  // synchronously, so the browser's first render already knows the column was
  // collapsed while the server rendered it expanded - two different trees,
  // which React reports as a hydration mismatch and repairs by rebuilding.
  // Both first renders agree on "expanded" now, and the rail arrives one
  // render later. The width transition is held back with it, so that arrival
  // is a jump rather than an animation somebody watches on every reload.
  const mounted = useMounted();
  const stored = useSidebarStore((state) => state.isCollapsed);
  const collapsed = mounted && stored;
  const toggleCollapsed = useSidebarStore((state) => state.toggleCollapsed);

  return (
    // `bg-sidebar`, a surface of its own, where this used to be `bg-card/55`
    // over a blur. Translucency put the column's apparent depth at the mercy of
    // whatever was behind it - it read as one shade over the page and another
    // over a card scrolled underneath - and the blur cost a compositor layer
    // the width of the window on every scroll. A token is one colour, it is the
    // deepest of the four surfaces in both themes, and a deployment can
    // retheme it.
    <aside
      className={cn(
        "bg-sidebar hidden shrink-0 border-r md:flex md:flex-col",
        mounted && "transition-[width] duration-200",
        collapsed ? "w-14" : "w-[240px]",
      )}
    >
      {/* The brand heads the column because there is no top bar above `md` for
          it to head instead, and the collapse control sits beside it: the one
          control that is about the column rather than about anything in it,
          on the column's own title bar - where every editor and console with a
          collapsible panel puts one. Search and the bell are actions and live
          with the account at the foot, where a hand rests. */}
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b",
          collapsed ? "justify-center px-2" : "gap-1 px-3",
        )}
      >
        {collapsed ? null : (
          <div className="min-w-0 flex-1">
            <BrandLink />
          </div>
        )}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
          aria-expanded={!collapsed}
          title={collapsed ? t("expandSidebar") : t("collapseSidebar")}
          className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-1"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-[1.1rem] w-[1.1rem]" aria-hidden />
          ) : (
            <PanelLeftClose className="h-[1.1rem] w-[1.1rem]" aria-hidden />
          )}
        </button>
      </div>
      <SidebarShell collapsed={collapsed}>
        <SidebarNav collapsed={collapsed} />
      </SidebarShell>
    </aside>
  );
}
