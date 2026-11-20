"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Boxes,
  KeyRound,
  MessagesSquare,
  Network,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useMcpOAuthOutcome, usePermissions, useUrlState } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { Permission } from "@/types/permissions";
import { Perm } from "@/types/permissions";

import { AppsTab } from "./apps-tab";
import { ManualConnections } from "./manual-connections";

type MoreEntry = {
  labelKey: "channels" | "remoteAgents" | "vault" | "sandboxes";
  descriptionKey:
    "channelsDescription" | "remoteAgentsDescription" | "vaultDescription" | "sandboxesDescription";
  href: string;
  icon: LucideIcon;
  /** Gated on what the target page's backend gates reading on, as the nav was. */
  permission: Permission;
};

/**
 * The other connection settings, one link each. Each card names the page it opens
 * under `/connectors/…`, so the card never depends on a redirect to work.
 */
const MORE: readonly MoreEntry[] = [
  {
    labelKey: "channels",
    descriptionKey: "channelsDescription",
    href: ROUTES.CHANNELS,
    icon: MessagesSquare,
    permission: Perm.agentsView,
  },
  {
    labelKey: "remoteAgents",
    descriptionKey: "remoteAgentsDescription",
    href: ROUTES.REMOTE_AGENTS,
    icon: Network,
    permission: Perm.agentsView,
  },
  {
    labelKey: "vault",
    descriptionKey: "vaultDescription",
    href: ROUTES.VAULT,
    icon: KeyRound,
    permission: Perm.secretsView,
  },
  {
    labelKey: "sandboxes",
    descriptionKey: "sandboxesDescription",
    href: ROUTES.SANDBOXES,
    icon: Boxes,
    permission: Perm.connectionsView,
  },
];

const TABS = ["apps", "mcp", "more"] as const;
type Tab = (typeof TABS)[number];

/**
 * Connections: one place for everything an agent connects to. Apps and MCP
 * are first-class tabs; More links to the other connection settings, and each
 * card appears only for a caller who holds the permission its page reads.
 */
export default function ConnectorsPage() {
  const t = useTranslations("pages.connectors");
  const tNav = useTranslations("nav");
  const { can } = usePermissions();
  useMcpOAuthOutcome();
  const [tabParam, setTab] = useUrlState("tab");
  const search = useSearchParams();
  const manualRequest = search.has("server") || search.has("connect");
  // Existing manual links use `advanced`; keep them pointed at the MCP catalog.
  const normalizedTab = tabParam === "advanced" ? "mcp" : tabParam;
  const tab: Tab = (TABS as readonly string[]).includes(normalizedTab ?? "")
    ? (normalizedTab as Tab)
    : manualRequest
      ? "mcp"
      : "apps";
  const more = MORE.filter((entry) => can(entry.permission));

  return (
    <div className="flex flex-1 flex-col space-y-4">
      <PageHeader title={t("title")} description={t("description")} />

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value === "apps" && !manualRequest ? null : value)}
      >
        <TabsList>
          <TabsTrigger value="apps" data-tour="connectors-apps">
            {t("apps")}
          </TabsTrigger>
          <TabsTrigger value="mcp" data-tour="connectors-advanced">
            {t("mcp")}
          </TabsTrigger>
          <TabsTrigger value="more" data-tour="connectors-more">
            {t("more")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="apps" className="mt-4">
          <AppsTab />
        </TabsContent>

        <TabsContent value="mcp" className="mt-4">
          <ManualConnections />
        </TabsContent>

        <TabsContent value="more" className="mt-4">
          <p className="text-muted-foreground mb-4 text-sm">{t("advancedDescription")}</p>
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {more.map(({ labelKey, descriptionKey, href, icon: Icon }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="border-border hover:bg-muted/50 focus-visible:ring-ring flex items-start gap-3 rounded-xl border p-4 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                >
                  <Icon className="text-muted-foreground mt-0.5 h-5 w-5 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{tNav(labelKey)}</span>
                    <span className="text-muted-foreground block text-sm">{t(descriptionKey)}</span>
                  </span>
                  <ArrowRight
                    className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        </TabsContent>
      </Tabs>
    </div>
  );
}
