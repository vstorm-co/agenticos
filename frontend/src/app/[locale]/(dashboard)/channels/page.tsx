"use client";

import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { MessagesSquare, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { AddChannelDialog } from "@/components/channels/add-channel-dialog";
import { ChannelBotsTable } from "@/components/channels/channel-bots-table";
import { DiscordRoleMappingsDialog } from "@/components/channels/discord-role-mappings-dialog";
import type { PublishAnswer } from "@/components/channels/unbind-slot";
import { BindAgentDialog } from "@/components/channels/bind-agent-dialog";
import { EditChannelDialog } from "@/components/channels/edit-channel-dialog";
import { ErrorState } from "@/components/states";
import { Button, ConfirmDialog, ListCard, ListCardEmpty } from "@/components/ui";
import { useAgents, useBotBindings, useChannelBots, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { BotAgent, ChannelBot } from "@/types/channels";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/** The shared list-card, with this page's title and count line filled in. */
function BotsCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.channels");
  return (
    <ListCard
      fill
      className="overflow-hidden"
      data-tour="channels-list"
      namedByPage
      title={t("bots")}
      empty={count === 0}
      contentClassName="p-0"
    >
      {children}
    </ListCard>
  );
}

/**
 * The chat platforms this organization is reachable on.
 *
 * A bot belongs to the organization, not to an agent: it answers as one agent,
 * which is bound here or on that agent's Availability tab, and registering one
 * is something an operator does once.
 * It used to live on each agent's Availability tab, which put a
 * register-a-platform form on a page about building one agent - so it read as a
 * property of that agent, and the same list appeared, identically, on every
 * other agent in the organization.
 *
 * Shaped like the Vault, deliberately: a table of connections the organization
 * owns, each holding a credential sealed at rest, with registration behind a
 * dialog. Two pages that answer the same class of question should not be two
 * different products.
 */
export default function ChannelsPage() {
  const t = useTranslations("pages.channels");
  const tErrors = useTranslations("errors");
  const common = useTranslations("common");
  const {
    can,
    isLoading: permissionsLoading,
    error: permissionsError,
    refetch: retryPermissions,
  } = usePermissions();
  // The backend gates every write here on `channels:manage`, and the listing
  // too - so the hook is told not to fetch at all for somebody without it,
  // rather than putting a 403 in the network log of every member who visits.
  const canManage = can(Perm.channelsManage);
  const { bots, isLoading, error, refetch, create, update, setActive, remove } =
    useChannelBots(canManage);
  // Read for what the viewer may publish, which the server re-checks on every
  // bind and unbind. Archived agents are included so one that is still bound
  // can be unbound. Not asked without the permissions that need it.
  const canBind = canManage && can(Perm.agentsView);
  const {
    agents,
    isLoading: agentsLoading,
    error: agentsError,
    refetch: refetchAgents,
  } = useAgents({ includeArchived: true, enabled: canBind });
  const { bind, unbind } = useBotBindings();
  const [adding, setAdding] = useState(false);
  // The row being edited, which is also what opens the dialog: a bot and an
  // open flag can disagree, and the disagreement renders last row's answers.
  const [editing, setEditing] = useState<ChannelBot | null>(null);
  const [deleting, setDeleting] = useState<ChannelBot | null>(null);
  const [mapping, setMapping] = useState<ChannelBot | null>(null);
  const [binding, setBinding] = useState<ChannelBot | null>(null);
  const [unbinding, setUnbinding] = useState<{ bot: ChannelBot; agent: BotAgent } | null>(null);
  const mayPublish = useMemo<PublishAnswer>(() => {
    if (agentsLoading) return "pending";
    if (agentsError) return "failed";
    const publishable = new Set(
      agents.filter((agent) => agent.can_publish === true).map((agent) => agent.id),
    );
    return (agentId: string) => publishable.has(agentId);
  }, [agents, agentsLoading, agentsError]);
  const startUnbind = useCallback(
    (bot: ChannelBot, agent: BotAgent) => setUnbinding({ bot, agent }),
    [],
  );
  // The same rule the agent page applies to binding: not archived, and not an
  // agent that runs on each person's own key.
  const bindable = agents.filter(
    (agent) =>
      agent.can_publish === true && agent.status !== "archived" && !agent.personal_model_key,
  );

  if (!permissionsLoading && !permissionsError && !canManage) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <PageHeader title={t("channels")} description={t("pageDescription")} />
        <BotsCard count={0}>
          <p className="text-muted-foreground px-6 py-16 text-center text-sm">
            {t("needChannelsManage")}
          </p>
        </BotsCard>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <PageHeader
        title={t("channels")}
        description={t("pageDescription")}
        actions={
          canManage ? (
            <Button data-tour="channels-new" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" />
              {t("addChannel")}
            </Button>
          ) : undefined
        }
      />

      <BotsCard count={error || permissionsError ? null : bots.length}>
        {isLoading || permissionsLoading ? (
          <ChannelBotsTable
            bots={[]}
            busy
            loading
            onEdit={setEditing}
            onToggleActive={(bot) => setActive.mutate({ botId: bot.id, isActive: !bot.is_active })}
            onDelete={setDeleting}
          />
        ) : error || permissionsError ? (
          // A failed read has no rows either, and "No channels yet" over a 502
          // is a refusal dressed as reassurance (#32's shape).
          <ErrorState
            description={getErrorMessage(error ?? permissionsError, tErrors)}
            cta={{
              label: common("retry"),
              onClick: () => {
                if (permissionsError) void retryPermissions();
                else void refetch();
              },
            }}
            className="m-5"
          />
        ) : (
          <ChannelBotsTable
            empty={
              <ListCardEmpty
                icon={MessagesSquare}
                title={t("noChannelsYet")}
                description={t("addOneBecomesBindable")}
                // Its own words, not the header's: two buttons reading "Add
                // channel" is one control a screen reader announces twice.
                cta={{
                  label: (
                    <>
                      <Plus className="h-3.5 w-3.5" />
                      {t("addChannel")}
                    </>
                  ),
                  onClick: () => setAdding(true),
                }}
              />
            }
            bots={bots}
            busy={setActive.isPending || remove.isPending}
            onEdit={setEditing}
            onToggleActive={(bot) => setActive.mutate({ botId: bot.id, isActive: !bot.is_active })}
            onDelete={setDeleting}
            onMapRoles={can(Perm.membersManage) ? setMapping : undefined}
            onBind={canBind ? setBinding : undefined}
            onUnbind={canBind ? startUnbind : undefined}
            mayPublish={mayPublish}
          />
        )}
      </BotsCard>

      {canManage && !permissionsLoading && (
        <AddChannelDialog
          open={adding}
          onOpenChange={setAdding}
          onSubmit={create.mutateAsync}
          isPending={create.isPending}
        />
      )}

      {deleting && canManage && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setDeleting(null)}
          title={t("removeBot", { bot: deleting.name })}
          description={t("removeBotDescription")}
          confirmLabel={t("removeBotConfirm")}
          destructive
          loading={remove.isPending}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        />
      )}

      {binding && canBind && (
        <BindAgentDialog
          bot={binding}
          agents={bindable}
          loading={agentsLoading}
          error={agentsError}
          onRetry={() => void refetchAgents()}
          pending={bind.isPending}
          onBind={(agent) =>
            bind.mutate(
              { agentId: agent.id, botId: binding.id, agentSlug: agent.slug },
              { onSuccess: () => setBinding(null) },
            )
          }
          onClose={() => setBinding(null)}
        />
      )}

      {unbinding && canBind && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setUnbinding(null)}
          title={t("unbindAgent", { agent: unbinding.agent.slug, bot: unbinding.bot.name })}
          description={t("unbindAgentDescription", { bot: unbinding.bot.name })}
          confirmLabel={t("unbindAgentConfirm")}
          destructive
          loading={unbind.isPending}
          onConfirm={() =>
            unbind.mutate(
              {
                agentId: unbinding.agent.id,
                exposureId: unbinding.agent.exposure_id,
                agentSlug: unbinding.agent.slug,
                botName: unbinding.bot.name,
              },
              { onSuccess: () => setUnbinding(null) },
            )
          }
        />
      )}

      <EditChannelDialog
        bot={editing}
        onOpenChange={(open) => !open && setEditing(null)}
        onSubmit={(botId, data) => update.mutateAsync({ botId, data })}
        isPending={update.isPending}
      />

      {mapping && <DiscordRoleMappingsDialog bot={mapping} onClose={() => setMapping(null)} />}
    </div>
  );
}
