"use client";

import { useMemo } from "react";
import { Pause, Play, Trash2 } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import { Badge, Button, DataTable, type Column } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { ChannelBot, ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

const PLATFORM_LABEL: Record<ChannelPlatform, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
};

interface ChannelBotsTableProps {
  bots: readonly ChannelBot[];
  busy: boolean;
  onToggleActive: (bot: ChannelBot) => void;
  onDelete: (bot: ChannelBot) => void;
}

/**
 * What a bot is missing before it can answer anything.
 *
 * Said in the listing rather than discovered by messaging a silent bot, which
 * is how each of these was found the first time. Mattermost does not sign
 * bodies, so the token in the payload is the whole check and a webhook without
 * one refuses every call; Slack signs, and without the signing secret nothing
 * inbound can be verified.
 */
function missingCredential(bot: ChannelBot): "webhookToken" | "signingSecret" | null {
  if (bot.platform === "mattermost" && bot.webhook_mode && !bot.has_webhook_secret) {
    return "webhookToken";
  }
  if (bot.platform === "slack" && !bot.has_slack_signing_secret) return "signingSecret";
  return null;
}

/** Dims a paused bot's row, cell by cell, since the table styles rows itself. */
function paused(bot: ChannelBot): string | false {
  return !bot.is_active && "opacity-60";
}

/**
 * The organization's channel bots, one row each.
 *
 * A table for the reason the vault is one: every question asked here is a
 * comparison across rows - which of these is live, which has nobody answering
 * on it, which is about to shout a cost footer into a busy channel - and cards
 * put those answers in a different place on every row.
 */
export function ChannelBotsTable({ bots, busy, onToggleActive, onDelete }: ChannelBotsTableProps) {
  const t = useTranslations("pages.channels");

  const rows = useMemo(() => [...bots], [bots]);

  const columns = useMemo<Column<ChannelBot>[]>(
    () => [
      {
        key: "bot",
        header: t("columnBot"),
        className: "pl-5",
        cell: (bot) => (
          <div className={cn("flex items-center gap-3", paused(bot))}>
            <ChannelPlatformIcon platform={bot.platform} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{bot.name}</p>
              <p className="text-muted-foreground truncate text-xs">
                {/* The server, where a platform has one of its own.
                    Mattermost is self-hosted, so "Mattermost" alone does
                    not say which of them this row is about. */}
                {bot.api_base_url
                  ? `${PLATFORM_LABEL[bot.platform] ?? bot.platform} · ${bot.api_base_url}`
                  : (PLATFORM_LABEL[bot.platform] ?? bot.platform)}
              </p>
            </div>
          </div>
        ),
      },
      {
        key: "delivery",
        header: t("columnDelivery"),
        cell: (bot) => {
          const missing = missingCredential(bot);
          return (
            <div className={cn("flex flex-col items-start gap-1", paused(bot))}>
              <Badge variant="outline">{bot.webhook_mode ? t("webhook") : t("polling")}</Badge>
              {missing && <Badge variant="secondary">{t(missing)}</Badge>}
              {!bot.is_active && <Badge variant="secondary">{t("paused")}</Badge>}
            </div>
          );
        },
      },
      {
        key: "answering",
        header: t("columnAnswering"),
        cell: (bot) =>
          bot.agents.length === 0 ? (
            // The state this column exists for: a bot registered, live,
            // and answering nobody, which from a chat window is
            // indistinguishable from a broken one.
            <span className={cn("text-muted-foreground text-xs", paused(bot))}>
              {t("noAgentBound")}
            </span>
          ) : (
            <div className={cn("flex flex-wrap items-center gap-2", paused(bot))}>
              {bot.agents.map((agent) => (
                <span key={agent.id} className="flex items-center gap-1.5">
                  <AgentAvatar
                    agentId={agent.id}
                    name={agent.name}
                    hasAvatar={agent.has_avatar}
                    size="sm"
                  />
                  <span className="truncate text-xs">@{agent.slug}</span>
                </span>
              ))}
            </div>
          ),
      },
      {
        key: "actions",
        header: t("columnActions"),
        align: "right",
        className: "w-24 pr-5",
        cell: (bot) => (
          <div className={cn("flex justify-end gap-1", paused(bot))}>
            <Button
              variant="ghost"
              size="icon"
              disabled={busy}
              aria-label={
                bot.is_active ? t("pauseBot", { bot: bot.name }) : t("resumeBot", { bot: bot.name })
              }
              onClick={() => onToggleActive(bot)}
            >
              {bot.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={busy}
              aria-label={t("removeBot", { bot: bot.name })}
              onClick={() => onDelete(bot)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ),
      },
    ],
    [busy, onToggleActive, onDelete, t],
  );

  return (
    <DataTable
      columns={columns}
      rows={rows}
      getRowKey={(bot) => bot.id}
      className="rounded-none border-0 bg-transparent"
    />
  );
}
