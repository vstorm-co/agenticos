import {
  MessagesSquare,
  PanelsTopLeft,
  Activity,
  Boxes,
  FileText,
  FolderKanban,
  FolderOpen,
  BookOpen,
  Bot,
  Building2,
  Database,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  Network,
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
  /**
   * The section's page is a set of tabs, each its own path one level down -
   * `/admin/users`, `/admin/system` - so each is still the section's page.
   */
  tabbed?: boolean;
  /** Lit on its own page only - a project's page lights the project's own row instead. */
  exact?: boolean;
};

/** The section hue a group carries - see "Section hues" in `globals.css`. */
export type NavDomain = "use" | "build" | "knowledge" | "workspace" | "admin";

export type NavGroup = {
  /** `null` for the first group, which needs no label above the top item. */
  labelKey: string | null;
  domain: NavDomain;
  items: NavItem[];
  adminOnly?: boolean;
  /**
   * Folded to its heading until somebody opens it, or until the page they are
   * on is inside it. For the groups set up once and visited rarely - the
   * connections an organization holds, its people - so the column a person
   * reads every day is the part they use every day.
   */
  collapsible?: boolean;
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
  // Somebody's ongoing work: the projects they are in, most recent first, drawn
  // above this entry by the sidebar itself (`ProjectRows`) - the list is data,
  // not a table row. The entry is what every project's page belongs to.
  {
    labelKey: "projects",
    domain: "use",
    items: [
      {
        labelKey: "allProjects",
        href: ROUTES.PROJECTS,
        icon: FolderKanban,
        permission: Perm.projectsView,
        dataTour: "nav-projects",
        exact: true,
      },
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
      // The org-wide create-and-manage home for triggers. Gated on `agents:view`,
      // the floor for seeing an agent's schedule; the create controls inside gate
      // further on `agents:run`, so a viewer sees the list without the buttons.
      { labelKey: "routines", href: ROUTES.ROUTINES, icon: Repeat, permission: Perm.agentsView },
      {
        labelKey: "artifacts",
        href: ROUTES.ARTIFACTS,
        icon: PanelsTopLeft,
        permission: Perm.artifactsView,
      },
      { labelKey: "activity", href: ROUTES.RUNS, icon: Activity, permission: Perm.runsView },
    ],
  },
  // What an agent knows: the documents it searches, the files it kept, the
  // how-tos it follows and the standing context it is always given.
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
      {
        // Deliberately ungated. These are the files an agent kept *for the
        // person looking*, and the backend narrows the listing to what they are
        // part of - so a permission here would hide somebody's own files behind
        // an operator's authority.
        labelKey: "documents",
        href: ROUTES.DOCUMENTS,
        icon: FolderOpen,
      },
      { labelKey: "skills", href: ROUTES.SKILLS, icon: BookOpen, permission: Perm.skillsView },
      { labelKey: "context", href: ROUTES.CONTEXT, icon: FileText, permission: Perm.contextView },
    ],
  },
  // What the organization is connected to. Set up once, revisited rarely, so
  // folded until opened.
  {
    labelKey: "connections",
    domain: "workspace",
    collapsible: true,
    items: [
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
        // Another vendor's agent, reached over A2A (#2092): a connection the
        // organization registers once, which its agents then delegate to.
        labelKey: "remoteAgents",
        href: ROUTES.REMOTE_AGENTS,
        icon: Network,
        permission: Perm.agentsView,
      },
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
        // Gated on what the backend gates reading these on. Watching where
        // sandboxes run - the session list, a host's ceilings - is an operator's
        // job and rides on connections:view; only the add-and-edit controls on
        // the page itself need connections:manage.
        labelKey: "sandboxes",
        href: ROUTES.SANDBOXES,
        icon: Boxes,
        permission: Perm.connectionsView,
      },
    ],
  },
  {
    labelKey: "organization",
    domain: "workspace",
    collapsible: true,
    items: [
      { labelKey: "organizations", href: ROUTES.ORGS, icon: Building2 },
      // A company's departments, with their people and what they were given
      // (#2072). Ungated: any member may read the groups, as sharing needs.
      { labelKey: "groups", href: ROUTES.GROUPS, icon: UsersRound },
    ],
  },
  {
    labelKey: "admin",
    domain: "admin",
    adminOnly: true,
    items: [{ labelKey: "adminOverview", href: ROUTES.ADMIN, icon: ShieldCheck, tabbed: true }],
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
        const path = stripLocale(pathname);
        const tab = item.tabbed && /^\/[^/]+$/.test(path.slice(item.href.length));
        return { item, domain: group.domain, isRoot: path === item.href || Boolean(tab) };
      }
    }
  }
  return null;
}
