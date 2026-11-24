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

import { useEffect, useRef } from "react";
import { scrollWithin } from "@/lib/scroll-within";
import Link, { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChevronRight, Loader2, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { ProjectRows } from "@/components/layout/project-rows";

import { BrandLink } from "@/components/layout/brand-link";
import { stripLocale } from "@/lib/active-route";
import { SIDEBAR_NAV_LINK } from "@/components/ui/control-styles";
import { SidebarSearch } from "@/components/layout/sidebar-search";
import { SidebarShell } from "@/components/layout/sidebar-shell";
import { useMounted } from "@/hooks/use-mounted";
import { useSuggestions } from "@/hooks/use-suggestions";
import { usePendingApprovals } from "@/hooks/use-pending-approvals";
import { useWaitingChatQuestions } from "@/hooks/use-waiting-chat-questions";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/stores";
import { NAV_GROUPS, isActive, type NavGroup, type NavItem } from "@/lib/nav-sections";

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
  const active = item.exact ? stripLocale(pathname) === item.href : isActive(pathname, item.href);
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
        SIDEBAR_NAV_LINK,
        // One row height in both states, so collapsing the column moves no icon
        // up or down - the rail is the same list with its words taken away.
        collapsed ? "touch:min-w-11 w-9 justify-center" : "gap-2.5 px-2.5",
      )}
    >
      <NavIcon icon={item.icon} />
      {collapsed ? null : <span className="truncate">{label}</span>}
      {item.count === "inbox" && <InboxCount collapsed={collapsed} />}
    </Link>
  );
}

/** How many open items wait in the inbox: a number in the column, a dot on the rail. */
function InboxCount({ collapsed }: { collapsed: boolean }) {
  const t = useTranslations("nav");
  const { suggestions } = useSuggestions();
  const approvals = usePendingApprovals();
  const questions = useWaitingChatQuestions();
  const waiting = suggestions.length + approvals.count + questions.count;
  if (waiting === 0) return null;
  const label = t("inboxCount", { count: waiting });
  return collapsed ? (
    <span
      className="bg-muted-foreground absolute top-1 right-1 h-1.5 w-1.5 rounded-full"
      aria-label={label}
    />
  ) : (
    <span
      className="text-muted-foreground ml-auto px-1 text-xs font-medium tabular-nums"
      aria-label={label}
    >
      {waiting}
    </span>
  );
}

/**
 * The entry's icon, turning while the page it opens is on its way: the click
 * answers where it was made, beside the bar along the top edge.
 */
function NavIcon({ icon: Icon }: { icon: NavItem["icon"] }) {
  const { pending } = useLinkStatus();
  return pending ? (
    <Loader2 className="size-[18px] shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
  ) : (
    <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
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
  const nav = useRef<HTMLElement>(null);
  const pathname = usePathname();
  useEffect(() => {
    const active = nav.current?.querySelector<HTMLElement>('[aria-current="page"]');
    if (active) scrollWithin(active, "nearest", "instant");
  }, [collapsed, pathname]);
  const { can } = usePermissions();
  const t = useTranslations("nav");

  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.permission || can(item.permission)),
  })).filter((group) => !group.switcherOnly && !group.adminOnly && group.items.length > 0);

  return (
    <nav
      ref={nav}
      aria-label={t("primary")}
      className={cn("flex flex-col gap-3 py-3", collapsed ? "items-center px-2" : "px-3")}
    >
      {groups.map((group) => (
        <NavGroupBlock
          key={group.labelKey ?? "main"}
          group={group}
          onNavigate={onNavigate}
          collapsed={collapsed}
        />
      ))}
    </nav>
  );
}

function NavGroupBlock({
  group,
  onNavigate,
  collapsed,
}: {
  group: NavGroup;
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const mounted = useMounted();
  const openGroups = useSidebarStore((state) => state.openGroups);
  const toggleGroup = useSidebarStore((state) => state.toggleGroup);
  const key = group.labelKey ?? "main";
  // The page you are on is never hidden behind a folded heading. The stored
  // choice is read only after mount, for the same hydration reason as the rail.
  const holdsActive = group.items.some((item) => isActive(pathname, item.href));
  // The rail folds too: a group closed in the column is closed on the rail, so
  // the two show the same destinations rather than the rail every one of them.
  const folds = !!group.collapsible;
  const open = !folds || holdsActive || (mounted && openGroups.includes(key));

  return (
    <div className={cn("flex flex-col gap-0.5", collapsed && "w-full items-center")}>
      {group.labelKey &&
        // The heading is what tells the groups apart, and on the rail there is
        // no room for the word. A rule does the same job: it says "a different
        // kind of thing starts here" without claiming to say which, which an
        // abbreviation would do badly. A folding group's rule is its fold
        // control, at the height the heading has in the column.
        (collapsed ? (
          folds ? (
            <button
              type="button"
              onClick={() => toggleGroup(key)}
              disabled={holdsActive}
              aria-expanded={open}
              aria-label={t(group.labelKey)}
              title={t(group.labelKey)}
              className="text-muted-foreground hover:text-foreground touch:min-h-11 touch:min-w-11 flex h-6 w-8 items-center justify-center gap-0.5 rounded-md disabled:cursor-default"
            >
              <span aria-hidden className="bg-border h-px w-3" />
              <ChevronRight
                className={cn(
                  "size-3 transition-transform duration-[var(--duration-fast)]",
                  open && "rotate-90",
                )}
                aria-hidden
              />
            </button>
          ) : (
            <div aria-hidden className="flex h-6 items-center">
              <span className="bg-border h-px w-5" />
            </div>
          )
        ) : folds ? (
          <button
            type="button"
            onClick={() => toggleGroup(key)}
            disabled={holdsActive}
            aria-expanded={open}
            className="text-muted-foreground hover:text-foreground disabled:hover:text-muted-foreground touch:min-h-11 flex h-7 items-center gap-1 rounded-md px-2.5 text-left text-xs font-medium transition-colors disabled:cursor-default"
          >
            <span className="flex-1">{t(group.labelKey)}</span>
            <ChevronRight
              className={cn(
                "size-3.5 transition-transform duration-[var(--duration-fast)]",
                open && "rotate-90",
              )}
              aria-hidden
            />
          </button>
        ) : (
          <div className="text-muted-foreground flex h-7 items-center px-2.5 text-xs font-medium">
            {t(group.labelKey)}
          </div>
        ))}
      {key === "projects" && <ProjectRows onNavigate={onNavigate} collapsed={collapsed} />}
      <div
        className="sidebar-group-content"
        data-open={open || undefined}
        inert={!open}
        aria-hidden={!open || undefined}
      >
        <div
          className={cn(
            "sidebar-group-links flex min-h-0 flex-col gap-0.5",
            collapsed && "items-center",
          )}
        >
          {group.items.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
          ))}
        </div>
      </div>
    </div>
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
  const collapseControl = (
    <button
      type="button"
      onClick={toggleCollapsed}
      aria-label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
      aria-expanded={!collapsed}
      title={collapsed ? t("expandSidebar") : t("collapseSidebar")}
      className="pressable-icon text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-2"
    >
      {collapsed ? (
        <PanelLeftOpen className="size-[18px]" strokeWidth={1.75} aria-hidden />
      ) : (
        <PanelLeftClose className="size-[18px]" strokeWidth={1.75} aria-hidden />
      )}
    </button>
  );

  return (
    // `bg-sidebar`, a surface of its own, where this used to be `bg-card/55`
    // over a blur. Translucency put the column's apparent depth at the mercy of
    // whatever was behind it - it read as one shade over the page and another
    // over a card scrolled underneath - and the blur cost a compositor layer
    // the width of the window on every scroll. A token is one colour, it is the
    // navigation surface in both themes, and a deployment can
    // retheme it.
    <aside
      data-collapsed={collapsed ? "" : undefined}
      className={cn(
        "bg-sidebar hidden shrink-0 md:flex md:flex-col",
        mounted && "sidebar-width-motion",
        collapsed ? "w-14" : "w-[240px]",
      )}
    >
      {/* Native macOS window controls need their own draggable row, including
          when the navigation is collapsed. Hidden on every other surface. */}
      <div aria-hidden className="macos-window-controls" data-tauri-drag-region />
      {/* The brand heads the column because there is no top bar above `md` for
          it to head instead, and the collapse control sits beside it: the one
          control that is about the column rather than about anything in it,
          on the column's own title bar - where every editor and console with a
          collapsible panel puts one. Search shares this title bar; notifications stay by the account. */}
      {/* In the desktop app this row also drags the window. "deep", so its
          empty space drags and its controls still click -
          Tauri's drag script skips buttons and links on its own. */}
      <div
        data-titlebar
        data-tauri-drag-region="deep"
        className={cn(
          "flex shrink-0 items-center",
          collapsed ? "flex-col gap-1 px-2 py-2" : "h-14 gap-1 px-3",
        )}
      >
        {collapsed ? null : (
          <div className="min-w-0 flex-1">
            <BrandLink />
          </div>
        )}
        {collapsed ? (
          <>
            {collapseControl}
            <SidebarSearch />
          </>
        ) : (
          <>
            <SidebarSearch />
            {collapseControl}
          </>
        )}
      </div>
      <SidebarShell collapsed={collapsed}>
        <SidebarNav collapsed={collapsed} />
      </SidebarShell>
    </aside>
  );
}
