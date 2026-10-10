import {
  MessagesSquare,
  PanelsTopLeft,
  Activity,
  Boxes,
  FileText,
  FolderOpen,
  BookOpen,
  Bot,
  Building2,
  Database,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  Plug,
  Repeat,
  ShieldCheck,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * The primary navigation's table - its groups, their entries and the section
 * hue each group carries - and the rules that place a URL in it.
 *
 * Data rather than a component, so the sidebar, the command palette and the
 * page chrome that colours itself by section all read one table without the
 * page chrome pulling in the sidebar's stores and shell.
 */

export type NavItem = {
  labelKey: string;
  href: string;
  icon: LucideIcon;
  /** Hidden unless the caller holds this. Omitted means always shown. */
  permission?: Permission;
  /** A `data-tour` anchor the onboarding coach points at — only where a flow returns here. */
  dataTour?: string;
};

/** The section hue a group carries - see "Section hues" in `globals.css`. */
export type NavDomain = "use" | "build" | "knowledge" | "workspace" | "admin";

export type NavGroup = {
  /** `null` for the first group, which needs no label above the top item. */
  labelKey: string | null;
  domain: NavDomain;
  items: NavItem[];
  adminOnly?: boolean;
};

export const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: null,
    domain: "use",
    items: [
      { labelKey: "dashboard", href: ROUTES.DASHBOARD, icon: LayoutDashboard },
      { labelKey: "chat", href: ROUTES.CHAT, icon: MessageSquare },
    ],
  },
  {
    labelKey: "build",
    domain: "build",
    items: [
      {
        labelKey: "agents",
        href: ROUTES.AGENTS,
        icon: Bot,
        permission: Perm.agentsView,
        dataTour: "nav-agents",
      },
      { labelKey: "skills", href: ROUTES.SKILLS, icon: BookOpen, permission: Perm.skillsView },
      { labelKey: "context", href: ROUTES.CONTEXT, icon: FileText, permission: Perm.contextView },
      {
        labelKey: "artifacts",
        href: ROUTES.ARTIFACTS,
        icon: PanelsTopLeft,
        permission: Perm.artifactsView,
      },
      { labelKey: "activity", href: ROUTES.RUNS, icon: Activity, permission: Perm.runsView },
      // The org-wide create-and-manage home for triggers. Gated on `agents:view`,
      // the floor for seeing an agent's schedule; the create controls inside gate
      // further on `agents:run`, so a viewer sees the list without the buttons.
      { labelKey: "routines", href: ROUTES.ROUTINES, icon: Repeat, permission: Perm.agentsView },
    ],
  },
  {
    labelKey: "knowledge",
    domain: "knowledge",
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
    domain: "workspace",
    items: [
      { labelKey: "organizations", href: ROUTES.ORGS, icon: Building2 },
      // A company's departments, with their people and what they were given
      // (#2072). Ungated: any member may read the groups, as sharing needs.
      { labelKey: "groups", href: ROUTES.GROUPS, icon: UsersRound },
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
      {
        // A chat platform an organization is reachable on. Beside the MCP
        // servers because it is the same kind of thing - a connection the
        // organization owns, holding a credential in the vault - and not on
        // an agent's page, where registering one made it look like a property
        // of that agent rather than something every agent can be bound to.
        labelKey: "channels",
        href: ROUTES.CHANNELS,
        icon: MessagesSquare,
        permission: Perm.agentsView,
      },
      {
        // Gated on what the backend gates reading these on. Watching where
        // sandboxes run - the session list, a host's ceilings - is an operator's
        // job and rides on connections:view; only the add-and-edit controls on
        // the page itself need connections:manage.
        labelKey: "sandboxes",
        href: ROUTES.SANDBOXES,
        icon: Boxes,
        permission: Perm.connectionsView,
      },
      {
        // Deliberately ungated, unlike Sandboxes above. These are the files an
        // agent kept *for the person looking*, and the backend narrows the listing
        // to what they are part of - so a permission here would hide somebody's own
        // workspace behind an operator's authority.
        labelKey: "workspaces",
        href: ROUTES.WORKSPACES,
        icon: FolderOpen,
      },
    ],
  },
  {
    labelKey: "admin",
    domain: "admin",
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

/**
 * The nav entry a path belongs to, with its group's hue, and whether the path is
 * the section's own page rather than something below it. `null` outside every
 * section - settings, a profile page.
 */
export function navSectionFor(
  pathname: string,
): { item: NavItem; domain: NavDomain; isRoot: boolean } | null {
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (isActive(pathname, item.href)) {
        return { item, domain: group.domain, isRoot: stripLocale(pathname) === item.href };
      }
    }
  }
  return null;
}
