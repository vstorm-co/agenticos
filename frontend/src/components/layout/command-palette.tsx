"use client";

import { useConsolePresentation } from "@/components/settings/console-experience-provider";
import { presentedNavigation } from "@/lib/nav-sections";
import { COMMAND_ITEM_FOCUS, MENU_ROW, SEARCH_FIELD_FOCUS } from "@/components/ui/control-styles";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useConsoleRouter as useRouter } from "@/hooks/use-console-router";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  ArrowRight,
  BookOpen,
  Bot,
  Database,
  FolderKanban,
  LogOut,
  Plus,
  Search,
  X,
} from "lucide-react";
import { ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import type { LucideIcon } from "lucide-react";

import { ADMIN_TABS } from "@/app/[locale]/(dashboard)/admin/admin-tabs";
import { SETTINGS_TABS } from "@/app/[locale]/(dashboard)/settings/settings-tabs";
import { NAV_GROUPS } from "@/components/layout/app-sidebar";
import type { PageTab } from "@/components/dashboard/page-tabs";
import { useAuth } from "@/hooks";
import { useProjects } from "@/hooks/use-projects";
import { useDebounced } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { apiClient } from "@/lib/api-client";
import { DIALOG_COMMAND } from "@/lib/dialog-sizes";
import { ROUTES } from "@/lib/constants";
import { useSidebarStore } from "@/stores/sidebar-store";
import { qk } from "@/lib/query-keys";
import { cn, isAppAdmin } from "@/lib/utils";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { Perm } from "@/types/permissions";
import type { AgentList } from "@/types/agents";
import type { KnowledgeBaseList } from "@/types";

/**
 * ⌘K: every destination the product has, plus the things you would name rather
 * than navigate to - an agent, a knowledge base, a conversation.
 *
 * The navigation half is *derived* from the tables that define it - the
 * sidebar's `NAV_GROUPS`, `SETTINGS_TABS`, `ADMIN_TABS` - and not restated
 * here. Restating it is what had happened, and the palette lost the argument
 * with the product: it still offered a Profile page that only redirects
 * elsewhere and a `/docs` URL the frontend does not serve, while Agents,
 * Skills, Activity, Vault and MCP servers - five of the platform's primary
 * destinations - could not be reached from it at all. A list written twice is a
 * list that is wrong once.
 *
 * What it shows is filtered by permission, exactly as the sidebar filters: the
 * palette is the other way into the same pages, so offering a Viewer a jump to
 * a page that will refuse them would undo the filtering next to it.
 */

/** Enough recent conversations to be useful; the input narrows them from there. */
const RECENT_CONVERSATIONS = 8;
/** Named entities are search fodder, not a listing - the pages hold the rest. */
const MAX_ENTITIES = 6;

interface ConversationItem {
  id: string;
  title: string | null;
  updated_at?: string | null;
}

export function CommandPalette() {
  const { navigation } = useConsolePresentation();
  const router = useRouter();
  const t = useTranslations("nav");
  const common = useTranslations("common");
  const { user, logout } = useAuth();
  const { can } = usePermissions();
  const { apiUrl } = usePublicConfig();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const admin = isAppAdmin(user);
  const invoker = useRef<HTMLElement | null>(null);
  const openRef = useRef(false);
  const restoreTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const changeOpen = useCallback((next: boolean, restoreFocus = true) => {
    if (restoreTimer.current !== null) clearTimeout(restoreTimer.current);
    if (next && !openRef.current)
      invoker.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    openRef.current = next;
    setOpen(next);
    // cmdk's Radix dialog has no Trigger; its default close handler therefore
    // cannot restore the sidebar/shortcut invoker. Navigation owns its own focus.
    if (!next && restoreFocus)
      restoreTimer.current = setTimeout(() => {
        if (!openRef.current && invoker.current?.isConnected)
          invoker.current.focus({ preventScroll: true });
        restoreTimer.current = null;
      }, 0);
  }, []);

  // Global ⌘K / Ctrl+K shortcut + a custom event so UI buttons can open it.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        changeOpen(!openRef.current);
      }
    };
    const openHandler = () => changeOpen(true);
    document.addEventListener("keydown", handler);
    window.addEventListener("command-palette:open", openHandler);
    return () => {
      document.removeEventListener("keydown", handler);
      window.removeEventListener("command-palette:open", openHandler);
      if (restoreTimer.current !== null) clearTimeout(restoreTimer.current);
    };
  }, [changeOpen]);

  // Named entities, fetched only once the palette is open - it is mounted on
  // every page, and a closed dialog has no business costing three requests per
  // navigation. The keys are the ones the pages themselves use, so a palette
  // opened after visiting /agents reads the cache instead of the network.
  const projectSearch = useDebounced(search);
  const projects = useProjects({
    search: projectSearch,
    limit: MAX_ENTITIES,
    enabled: open && can(Perm.projectsView),
  });
  const agents = useQuery({
    queryKey: qk.agents.list(),
    queryFn: () => apiClient.get<AgentList>("/agents"),
    enabled: open && can(Perm.agentsView),
  });
  const kbs = useQuery({
    queryKey: qk.kb.list(),
    queryFn: async () => (await apiClient.get<KnowledgeBaseList>("/kb")).items,
    enabled: open && can(Perm.collectionsView),
  });
  const conversations = useQuery({
    queryKey: qk.conversations.recent(RECENT_CONVERSATIONS),
    queryFn: () =>
      apiClient.get<{ items: ConversationItem[] }>("/conversations", {
        params: { limit: String(RECENT_CONVERSATIONS) },
      }),
    enabled: open,
  });

  const agentItems = can(Perm.agentsView) ? (agents.data?.items.slice(0, MAX_ENTITIES) ?? []) : [];
  const kbItems = can(Perm.collectionsView) ? (kbs.data?.slice(0, MAX_ENTITIES) ?? []) : [];
  const conversationItems = conversations.data?.items ?? [];
  const failedQueries = [
    ...(can(Perm.projectsView)
      ? [{ isError: projects.error !== null, refetch: projects.refetch }]
      : []),
    ...(can(Perm.agentsView) ? [agents] : []),
    ...(can(Perm.collectionsView) ? [kbs] : []),
    conversations,
  ].filter((query) => query.isError);

  const go = (href: string) => {
    useSidebarStore.getState().close();
    changeOpen(false, false);
    useUnsavedChangesStore.getState().leave(() => router.push(href));
  };

  // Every destination the navigation already offers. The section groups below
  // list the pages *inside* a section, and the section's own index is one of
  // them - without this, Admin appears twice.
  const navigated = new Set(NAV_GROUPS.flatMap((group) => group.items).map((item) => item.href));

  // A tab's own key, in this palette's own namespace: both tables name a `nav`
  // message, which is what `useTranslations("nav")` above is scoped to. The
  // palette used to keep a second table mapping each route to a key, because the
  // tabs held English - see `PageTab.labelKey` for why they no longer do.
  const sectionItems = (tabs: readonly PageTab[]) =>
    tabs
      .filter((tab) => !navigated.has(tab.href))
      .map((tab) => (
        <PaletteItem
          key={tab.href}
          icon={tab.icon ?? ArrowRight}
          label={t(tab.labelKey)}
          onSelect={() => go(tab.href)}
        />
      ));

  return (
    <Command.Dialog
      open={open}
      onOpenChange={changeOpen}
      className="flex min-h-0 min-w-0 flex-1 flex-col"
      label={t("commandPalette")}
      shouldFilter
      overlayClassName="fixed inset-0 z-[60] bg-black/40"
      contentClassName={cn(
        "panel bg-card text-foreground z-[61] flex shadow-[var(--shadow-dialog)]",
        DIALOG_COMMAND,
      )}
    >
      <div
        className={cn(
          SEARCH_FIELD_FOCUS,
          "border-border flex shrink-0 items-center gap-2 border-b px-3 py-2 sm:gap-3 sm:px-4",
        )}
      >
        <Search className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
        <Command.Input
          autoFocus
          value={search}
          onValueChange={setSearch}
          placeholder={t("searchJump")}
          aria-label={t("searchJump")}
          className="text-foreground placeholder:text-muted-foreground min-h-11 min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm"
        />
        <button
          type="button"
          aria-label={common("close")}
          onClick={() => changeOpen(false)}
          onKeyDown={keepButtonActivation}
          className="text-muted-foreground hover:bg-control hover:text-foreground focus-visible:outline-ring inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 md:hidden"
        >
          <X className="size-4" aria-hidden />
        </button>
        <kbd className="border-foreground/15 text-muted-foreground hidden rounded-md border px-1.5 py-0.5 font-mono text-xs md:inline-block">
          {t("esc")}
        </kbd>
      </div>

      {failedQueries.length > 0 && (
        <div
          role="alert"
          className="border-border flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2 text-sm"
        >
          <p className="text-muted-foreground">{t("searchUnavailable")}</p>
          <button
            type="button"
            onKeyDown={keepButtonActivation}
            className="hover:bg-control min-h-10 shrink-0 rounded-md px-3 pointer-coarse:min-h-11"
            onClick={() => {
              for (const query of failedQueries) void query.refetch();
            }}
          >
            {common("retry")}
          </button>
        </div>
      )}

      <Command.List className="min-h-0 flex-1 scrollbar-thin [scrollbar-gutter:stable] overflow-y-auto overscroll-contain px-2 py-2">
        <Command.Empty className="text-muted-foreground px-4 py-10 text-center text-sm">
          {t("noMatches")}
        </Command.Empty>

        <Group heading={t("quickActions")}>
          <PaletteItem icon={Plus} label={t("startNewChat")} onSelect={() => go(ROUTES.CHAT)} />
          <PaletteItem
            icon={BookOpen}
            label={t("apiDocs")}
            onSelect={() => {
              changeOpen(false, false);
              // The docs are FastAPI's, served by the backend. The frontend has
              // no /docs route, so the old link opened its 404 page.
              window.open(`${apiUrl}/docs`, "_blank", "noopener,noreferrer");
            }}
          />
        </Group>

        {presentedNavigation(NAV_GROUPS, navigation).map((group) => {
          if (group.adminOnly && !admin) return null;
          const items = group.items.filter((item) => !item.permission || can(item.permission));
          if (items.length === 0) return null;
          return (
            <Group key={group.labelKey ?? "main"} heading={t(group.labelKey ?? "navigate")}>
              {items.map((item) => (
                <PaletteItem
                  key={item.href}
                  icon={item.icon}
                  label={t(item.labelKey)}
                  onSelect={() => go(item.href)}
                />
              ))}
            </Group>
          );
        })}

        {can(Perm.projectsView) && projects.projects.length > 0 && (
          <Group heading={t("projects")}>
            {projects.projects.map((project) => (
              <PaletteItem
                key={project.id}
                icon={FolderKanban}
                label={project.name}
                onSelect={() => go(ROUTES.PROJECT_DETAIL(project.id))}
              />
            ))}
          </Group>
        )}
        {agentItems.length > 0 && (
          <Group heading={t("agents")}>
            {agentItems.map((agent) => (
              <PaletteItem
                key={agent.id}
                icon={Bot}
                label={agent.name}
                onSelect={() => go(ROUTES.AGENT_DETAIL(agent.id))}
              />
            ))}
          </Group>
        )}

        {kbItems.length > 0 && (
          <Group heading={t("knowledgeBases")}>
            {kbItems.map((kb) => (
              <PaletteItem
                key={kb.id}
                icon={Database}
                label={kb.name}
                onSelect={() => go(ROUTES.RAG_DETAIL(kb.id))}
              />
            ))}
          </Group>
        )}

        {conversationItems.length > 0 && (
          <Group heading={t("conversations")}>
            {conversationItems.map((c) => (
              <PaletteItem
                key={c.id}
                icon={MessageSquare}
                label={c.title?.trim() || t("untitledConversation")}
                onSelect={() => go(`${ROUTES.CHAT}?id=${c.id}`)}
              />
            ))}
          </Group>
        )}

        <Group heading={t("settingsSection")}>{sectionItems(SETTINGS_TABS)}</Group>
        {admin && <Group heading={t("admin")}>{sectionItems(ADMIN_TABS)}</Group>}

        <Group heading={t("account")}>
          <PaletteItem
            icon={LogOut}
            label={t("logout")}
            onSelect={() => {
              changeOpen(false, false);
              useUnsavedChangesStore.getState().leave(() => void logout());
            }}
          />
        </Group>
      </Command.List>

      <div className="border-border text-muted-foreground flex shrink-0 items-center justify-between border-t px-4 py-2.5 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">↑↓</kbd>
          {t("navigate")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">↵</kbd>
          {t("open")}
        </span>
      </div>
    </Command.Dialog>
  );
}

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold"
    >
      {children}
    </Command.Group>
  );
}

function PaletteItem({
  icon: Icon,
  label,
  onSelect,
}: {
  icon: LucideIcon;
  label: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className={cn(COMMAND_ITEM_FOCUS, MENU_ROW, "group cursor-pointer")}
    >
      <Icon className="h-4 w-4 shrink-0 opacity-70" />
      <span className="flex-1 truncate">{label}</span>
      <ArrowRight className="text-muted-foreground h-3.5 w-3.5 opacity-0 transition-opacity group-data-[selected=true]:opacity-100" />
    </Command.Item>
  );
}

/** cmdk's root handles Enter as result selection; native controls keep their own activation. */
function keepButtonActivation(event: ReactKeyboardEvent<HTMLButtonElement>) {
  if (event.key === "Enter") event.stopPropagation();
}
