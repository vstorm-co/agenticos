"use client";

import { Pause, Play, Trash2 } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import {
  Badge,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";
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
  return (
    <Table
      className={cn(
        // The card's own gutter on the outer columns, and rows tall enough for
        // the two-line bot cell - the same treatment the vault's table takes.
        "[&_td:first-child]:pl-5 [&_td:last-child]:pr-5 [&_th:first-child]:pl-5 [&_th:last-child]:pr-5",
        "[&_td]:py-3",
        "[&_tr:last-child]:border-0",
      )}
    >
      <TableHeader>
        <TableRow>
          <TableHead>{t("columnBot")}</TableHead>
          <TableHead>{t("columnDelivery")}</TableHead>
          <TableHead>{t("columnAnswering")}</TableHead>
          <TableHead className="w-24 text-right">{t("columnActions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {bots.map((bot) => {
          const missing = missingCredential(bot);
          return (
            <TableRow key={bot.id} className={cn(!bot.is_active && "opacity-60")}>
              <TableCell>
                <div className="flex items-center gap-3">
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
              </TableCell>

              <TableCell>
                <div className="flex flex-col items-start gap-1">
                  <Badge variant="outline">{bot.webhook_mode ? t("webhook") : t("polling")}</Badge>
                  {missing && <Badge variant="secondary">{t(missing)}</Badge>}
                  {!bot.is_active && <Badge variant="secondary">{t("paused")}</Badge>}
                </div>
              </TableCell>

              <TableCell>
                {bot.agents.length === 0 ? (
                  // The state this column exists for: a bot registered, live,
                  // and answering nobody, which from a chat window is
                  // indistinguishable from a broken one.
                  <span className="text-muted-foreground text-xs">{t("noAgentBound")}</span>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
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
                )}
              </TableCell>

              <TableCell>
                <div className="flex justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={busy}
                    aria-label={
                      bot.is_active
                        ? t("pauseBot", { bot: bot.name })
                        : t("resumeBot", { bot: bot.name })
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
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
