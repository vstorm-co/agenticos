"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { MessagesSquare, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { AddChannelDialog } from "@/components/channels/add-channel-dialog";
import { ChannelBotsTable } from "@/components/channels/channel-bots-table";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { useChannelBots, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * The list's frame, drawn whether or not there is anything in it.
 *
 * Same header, same border, in every state - what changes is what is inside it.
 * A card that appears only once a bot exists reads as the panel disappearing
 * the moment you use it.
 */
function BotsCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.channels");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("bots")}</CardTitle>
          <CardDescription className="text-xs">
            {/* `null` is "the request has not answered". Rendering "0 channels"
                there would state something about the organization that nothing
                has said yet. */}
            {count === null ? <Skeleton className="h-3 w-24" /> : t("registeredCount", { count })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">{children}</CardContent>
    </Card>
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
  const { can } = usePermissions();
  // The backend gates every write here on `channels:manage`, and the listing
  // too - so the hook is told not to fetch at all for somebody without it,
  // rather than putting a 403 in the network log of every member who visits.
  const canManage = can(Perm.channelsManage);
  const { bots, isLoading, create, setActive, remove } = useChannelBots(canManage);
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

      <BotsCard count={bots.length}>
        {bots.length === 0 ? (
          // Inline rather than an `EmptyState`: that component draws its own
          // bordered box, which inside a card is two frames around one message.
          <div className="px-6 py-16 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <MessagesSquare className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">{t("noChannelsYet")}</p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
              {t("addOneBecomesBindable")}
            </p>
            {/* Its own words, not the header's: two buttons reading "Add
                channel" is one control a screen reader announces twice. */}
            <Button variant="outline" size="sm" className="mt-5" onClick={() => setAdding(true)}>
              <Plus className="h-3.5 w-3.5" />
              {t("addFirstChannel")}
            </Button>
          </div>
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
