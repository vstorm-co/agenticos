"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { ChannelBotsPanel } from "@/components/agents/channel-bots-panel";
import { usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * The chat platforms this organization is reachable on.
 *
 * A bot belongs to the organization, not to an agent: one bot serves every
 * agent bound to it, and registering one is something an operator does once.
 * It used to live on each agent's Availability tab, which put a
 * register-a-platform form on a page about building one agent - so it read as a
 * property of that agent, and the same list appeared, identically, on every
 * other agent in the organization.
 *
 * Beside MCP servers and Sandboxes for the same reason all three are here: a
 * connection the organization owns, holding a credential in the vault.
 */
export default function ChannelsPage() {
  const t = useTranslations("pages.channels");
  const { can } = usePermissions();

  return (
    <div className="space-y-6">
      <PageHeader title={t("channels")} description={t("pageDescription")} />
      <ChannelBotsPanel canManage={can(Perm.agentsEdit)} />
    </div>
  );
}
