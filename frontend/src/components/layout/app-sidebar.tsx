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
import {
  Activity,
  BookOpen,
  Bot,
  Building2,
  Database,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  Plug,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { BrandLink } from "@/components/layout/brand-link";
import { SidebarShell } from "@/components/layout/sidebar-shell";
import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { cn, isAppAdmin } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

type NavItem = {
  labelKey: string;
  href: string;
  icon: LucideIcon;
  /** Hidden unless the caller holds this. Omitted means always shown. */
  permission?: Permission;
};

type NavGroup = {
  /** `null` for the first group, which needs no label above the top item. */
  labelKey: string | null;
  items: NavItem[];
  adminOnly?: boolean;
};

export const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: null,
    items: [
      { labelKey: "dashboard", href: ROUTES.DASHBOARD, icon: LayoutDashboard },
      { labelKey: "chat", href: ROUTES.CHAT, icon: MessageSquare },
    ],
  },
  {
    labelKey: "build",
    items: [
      { labelKey: "agents", href: ROUTES.AGENTS, icon: Bot, permission: Perm.agentsView },
      { labelKey: "skills", href: ROUTES.SKILLS, icon: BookOpen, permission: Perm.skillsView },
      { labelKey: "activity", href: ROUTES.RUNS, icon: Activity, permission: Perm.runsView },
    ],
  },
  {
    labelKey: "knowledge",
    items: [
      {
        labelKey: "knowledgeBases",
        href: ROUTES.RAG,
        icon: Database,
        permission: Perm.collectionsView,
      },
    ],
  },
  {
    labelKey: "workspace",
    items: [
      { labelKey: "organizations", href: ROUTES.ORGS, icon: Building2 },
      {
        // Gated on what the backend gates listing on: a Member holding secrets
        // at OWN scope can use the Vault, so the nav must not hide it behind
        // the broader connections:manage.
        labelKey: "vault",
        href: ROUTES.VAULT,
        icon: KeyRound,
        permission: Perm.secretsView,
      },
      {
        labelKey: "mcpServers",
        href: ROUTES.MCP_SERVERS,
        icon: Plug,
        permission: Perm.agentsView,
      },
    ],
  },
  {
    labelKey: "admin",
    adminOnly: true,
    items: [{ labelKey: "adminOverview", href: ROUTES.ADMIN, icon: ShieldCheck }],
  },
];

/**
 * Every destination the nav declares. What makes one entry's section end is the
 * next entry beginning, so the rule below needs the whole table, not one row.
 */
const NAV_HREFS: readonly string[] = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => item.href),
);

/** Whether `path` is `href` or something below it: `/agents/abc`, never `/agents-archive`. */
function isInside(path: string, href: string): boolean {
  return path === href || path.startsWith(`${href}/`);
}

/**
 * Whether `pathname` belongs to the section `href` names.
 *
 * A sub-page lights its section, and that is the default rather than something
 * an entry opts into - the old opt-in was remembered for five of the eleven
 * entries, so opening a knowledge base left the sidebar claiming you were
 * nowhere. Where two entries both contain the path the longer href wins, which
 * is the whole exception, stated once here instead of per entry: a `/settings`
 * entry would not steal `/settings/providers` from the entry that owns it, and
 * were that entry ever removed `/settings` takes the sub-route back with no
 * flag to remember. Adding a row to `NAV_GROUPS` therefore cannot get this
 * wrong in either direction.
 *
 * Which section a URL falls in is a fact about the route table, so every
 * declared destination counts - including ones the caller's permissions hide.
 *
 * `hrefs` is a parameter only so the rule can be exercised against a nav table
 * this one does not happen to contain today.
 */
export function isActive(
  pathname: string,
  href: string,
  hrefs: readonly string[] = NAV_HREFS,
): boolean {
  const path = stripLocale(pathname);
  if (!isInside(path, href)) return false;
  return !hrefs.some((other) => other.length > href.length && isInside(path, other));
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const pathname = usePathname();
  const t = useTranslations("nav");
  const active = isActive(pathname, item.href);

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors",
        // Selected is a neutral raised pill with a dark label - the register
        // OpenAI's and ElevenLabs' consoles use. The accent stays out of the
        // nav so the one place it appears in content still reads as a signal.
        active
          ? "bg-accent text-foreground font-medium"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      <item.icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="truncate">{t(item.labelKey)}</span>
    </Link>
  );
}

/**
 * The link list on its own, so the desktop column and the mobile slide-over
 * cannot drift into offering different destinations.
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = usePermissions();
  const { user } = useAuthStore();
  const t = useTranslations("nav");
  const admin = isAppAdmin(user);

  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.permission || can(item.permission)),
  })).filter((group) => group.items.length > 0 && (!group.adminOnly || admin));

  return (
    <nav aria-label={t("primary")} className="flex flex-col gap-5 px-3 py-4">
      {groups.map((group) => (
        <div key={group.labelKey ?? "main"} className="flex flex-col gap-0.5">
          {group.labelKey && (
            <div className="text-muted-foreground px-2.5 pb-1.5 text-[11px] font-medium tracking-wide uppercase">
              {t(group.labelKey)}
            </div>
          )}
          {group.items.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
    </nav>
  );
}

export function AppSidebar() {
  return (
    // `bg-card`, not `bg-background`: the column reads as its own light panel
    // (white in light theme, one step above the page in dark) the way
    // Logfire's does, instead of dissolving into the content behind it.
    <aside className="bg-card hidden w-[240px] shrink-0 border-r md:flex md:flex-col">
      {/* The brand heads the column because there is no top bar above `md` for
          it to head instead. */}
      <div className="flex h-14 shrink-0 items-center border-b px-3">
        <BrandLink />
      </div>
      <SidebarShell>
        <SidebarNav />
      </SidebarShell>
    </aside>
  );
}
