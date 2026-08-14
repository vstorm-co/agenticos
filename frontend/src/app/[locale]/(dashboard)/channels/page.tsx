"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { MessagesSquare, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { AddChannelDialog } from "@/components/channels/add-channel-dialog";
import { ChannelBotsTable } from "@/components/channels/channel-bots-table";
import { ErrorState } from "@/components/states";
import { Button, ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useChannelBots, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/** The shared list-card, with this page's title and count line filled in. */
function BotsCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.channels");
  return (
    <ListCard
      title={t("bots")}
      counted={count === null ? null : t("registeredCount", { count })}
      contentClassName="p-0"
    >
      {children}
    </ListCard>
  );
}

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
 * Shaped like the Vault, deliberately: a table of connections the organization
 * owns, each holding a credential sealed at rest, with registration behind a
 * dialog. Two pages that answer the same class of question should not be two
 * different products.
 */
export default function ChannelsPage() {
  const t = useTranslations("pages.channels");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  // The backend gates every write here on `channels:manage`, and the listing
  // too - so the hook is told not to fetch at all for somebody without it,
  // rather than putting a 403 in the network log of every member who visits.
  const canManage = can(Perm.channelsManage);
  const { bots, isLoading, error, create, setActive, remove } = useChannelBots(canManage);
  const [adding, setAdding] = useState(false);

  if (!canManage) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("channels")} description={t("pageDescription")} />
        <BotsCard count={0}>
          <p className="text-muted-foreground px-6 py-16 text-center text-sm">
            {t("needChannelsManage")}
          </p>
        </BotsCard>
      </div>
    );
  }

  // The same card the page renders, with row skeletons in it. A skeleton that
  // draws a different shape from what follows is a layout jump on every load.
  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("channels")} description={t("pageDescription")} />
        <BotsCard count={null}>
          {[0, 1, 2].map((row) => (
            <div
              key={row}
              className="border-border flex items-center gap-3 border-b px-5 py-4 last:border-b-0"
            >
              <Skeleton className="h-8 w-8 shrink-0 rounded-lg" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-72 max-w-full" />
              </div>
            </div>
          ))}
        </BotsCard>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("channels")}
        description={t("pageDescription")}
        actions={
          <Button onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" />
            {t("addChannel")}
          </Button>
        }
      />

      <BotsCard count={error ? null : bots.length}>
        {error ? (
          // A failed read has no rows either, and "No channels yet" over a 502
          // is a refusal dressed as reassurance (#32's shape).
          <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
        ) : bots.length === 0 ? (
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
                  {t("addFirstChannel")}
                </>
              ),
              onClick: () => setAdding(true),
            }}
          />
        ) : (
          <ChannelBotsTable
            bots={bots}
            busy={setActive.isPending || remove.isPending}
            onToggleActive={(bot) => setActive.mutate({ botId: bot.id, isActive: !bot.is_active })}
            onDelete={(bot) => remove.mutate(bot.id)}
          />
        )}
      </BotsCard>

      <AddChannelDialog
        open={adding}
        onOpenChange={setAdding}
        onSubmit={create.mutateAsync}
        isPending={create.isPending}
      />
    </div>
  );
}
