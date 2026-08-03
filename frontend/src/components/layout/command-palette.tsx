"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  ArrowRight,
  BookOpen,
  Bot,
  Database,
  LogOut,
  MessageSquare,
  Plus,
  Search,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { ADMIN_TABS } from "@/app/[locale]/(dashboard)/admin/admin-tabs";
import { SETTINGS_TABS } from "@/app/[locale]/(dashboard)/settings/settings-tabs";
import { NAV_GROUPS } from "@/components/layout/app-sidebar";
import type { PageTab } from "@/components/dashboard/page-tabs";
import { useAuth } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import { apiClient } from "@/lib/api-client";
import { BACKEND_URL, ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { isAppAdmin } from "@/lib/utils";
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

/**
 * The `nav` message key for a section page, by the route it leads to.
 *
 * The tab tables carry English labels because that is what they render; the
 * palette is translated, so it needs the key. `command-palette.test.tsx` fails
 * if a tab is ever added without one, which is the only thing keeping this in
 * step with the two tables it annotates.
 */
export const SECTION_LABEL_KEYS: Record<string, string> = {
  [ROUTES.SETTINGS_PROFILE]: "profile",
  [ROUTES.SETTINGS_ACCOUNT]: "account",
  [ROUTES.SETTINGS_NOTIFICATIONS]: "notifications",
  [ROUTES.SETTINGS_SLASH_COMMANDS]: "slashCommands",
  [ROUTES.ADMIN]: "adminOverview",
  [ROUTES.ADMIN_USERS]: "users",
  [ROUTES.ADMIN_CONVERSATIONS]: "conversations",
  [ROUTES.ADMIN_RATINGS]: "ratings",
  [ROUTES.ADMIN_SYSTEM]: "system",
};

export function CommandPalette() {
  const router = useRouter();
  const t = useTranslations("nav");
  const { user, logout } = useAuth();
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const admin = isAppAdmin(user);

  // Global ⌘K / Ctrl+K shortcut + a custom event so UI buttons can open it.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const openHandler = () => setOpen(true);
    document.addEventListener("keydown", handler);
    window.addEventListener("command-palette:open", openHandler);
    return () => {
      document.removeEventListener("keydown", handler);
      window.removeEventListener("command-palette:open", openHandler);
    };
  }, []);

  // Named entities, fetched only once the palette is open - it is mounted on
  // every page, and a closed dialog has no business costing three requests per
  // navigation. The keys are the ones the pages themselves use, so a palette
  // opened after visiting /agents reads the cache instead of the network.
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

  const agentItems = agents.data?.items.slice(0, MAX_ENTITIES) ?? [];
  const kbItems = kbs.data?.slice(0, MAX_ENTITIES) ?? [];
  const conversationItems = conversations.data?.items ?? [];

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  // Every destination the navigation already offers. The section groups below
  // list the pages *inside* a section, and the section's own index is one of
  // them - without this, Admin appears twice.
  const navigated = new Set(NAV_GROUPS.flatMap((group) => group.items).map((item) => item.href));

  const sectionItems = (tabs: readonly PageTab[]) =>
    tabs
      .filter((tab) => !navigated.has(tab.href))
      .map((tab) => {
        const key = SECTION_LABEL_KEYS[tab.href];
        return (
          <PaletteItem
            key={tab.href}
            icon={tab.icon ?? ArrowRight}
            label={key ? t(key) : tab.label}
            onSelect={() => go(tab.href)}
          />
        );
      });

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label={t("commandPalette")}
      shouldFilter
      overlayClassName="bg-background/50 fixed inset-0 z-[60] backdrop-blur-sm"
      contentClassName="border-foreground/15 bg-card text-foreground fixed left-1/2 top-[12vh] z-[61] w-[min(92vw,640px)] -translate-x-1/2 overflow-hidden rounded-2xl border shadow-2xl"
    >
      <div className="border-foreground/10 flex items-center gap-3 border-b px-4 py-3">
        <Search className="text-foreground/45 h-4 w-4" />
        <Command.Input
          autoFocus
          value={search}
          onValueChange={setSearch}
          placeholder={t("searchJump")}
          className="text-foreground placeholder:text-foreground/45 flex-1 bg-transparent text-sm outline-none"
        />
        <kbd className="border-foreground/15 text-foreground/55 hidden rounded-md border px-1.5 py-0.5 font-mono text-[10px] sm:inline-block">
          ESC
        </kbd>
      </div>

      <Command.List className="max-h-[60vh] overflow-y-auto px-2 py-2">
        <Command.Empty className="text-foreground/55 px-4 py-10 text-center text-sm">
          No matches.
        </Command.Empty>

        <Group heading={t("quickActions")}>
          <PaletteItem icon={Plus} label="Start new chat" onSelect={() => go(ROUTES.CHAT)} />
          <PaletteItem
            icon={BookOpen}
            label={t("apiDocs")}
            onSelect={() => {
              setOpen(false);
              // The docs are FastAPI's, served by the backend. The frontend has
              // no /docs route, so the old link opened its 404 page.
              window.open(`${BACKEND_URL}/docs`, "_blank", "noopener,noreferrer");
            }}
          />
        </Group>

        {NAV_GROUPS.map((group) => {
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
                onSelect={() => go(ROUTES.KB_DETAIL(kb.id))}
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
                label={c.title?.trim() || "Untitled conversation"}
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
              setOpen(false);
              logout();
            }}
          />
        </Group>
      </Command.List>

      <div className="border-foreground/10 text-foreground/45 flex items-center justify-between border-t px-4 py-2 font-mono text-[10px] tracking-wider uppercase">
        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">↑↓</kbd>
          Navigate
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className="border-foreground/15 rounded border px-1 py-0.5">↵</kbd>
          Open
        </span>
      </div>
    </Command.Dialog>
  );
}

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:text-foreground/45 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:uppercase"
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
      className="text-foreground/85 hover:bg-foreground/5 data-[selected=true]:bg-foreground/8 data-[selected=true]:text-foreground flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors"
    >
      <Icon className="h-4 w-4 shrink-0 opacity-70" />
      <span className="flex-1 truncate">{label}</span>
      <ArrowRight className="text-foreground/30 h-3.5 w-3.5 opacity-0 transition-opacity data-[selected=true]:opacity-100" />
    </Command.Item>
  );
}
