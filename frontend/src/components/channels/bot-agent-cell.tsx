"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Badge, Button } from "@/components/ui";
import { UnbindSlot, type PublishAnswer } from "./unbind-slot";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { BotAgent, ChannelBot } from "@/types/channels";

interface BotAgentCellProps {
  bot: ChannelBot;
  /** Dims a paused bot's cell, like the row's other cells. */
  className?: string;
  busy: boolean;
  /** Present only for somebody who may bind: `channels:manage` and `agents:view`. */
  onBind?: (bot: ChannelBot) => void;
  onUnbind?: (bot: ChannelBot, agent: BotAgent) => void;
  mayPublish?: PublishAnswer;
}

/**
 * Who a bot answers as, with the controls to change it.
 *
 * A bot answers as one agent, so the cell is either a binding or the way to
 * make one. The unbind control is drawn only for an agent the viewer may
 * publish: the server refuses anyone else, and a button that can only fail is
 * not worth showing.
 */
export function BotAgentCell({
  bot,
  className,
  busy,
  onBind,
  onUnbind,
  mayPublish = "failed",
}: BotAgentCellProps) {
  const t = useTranslations("pages.channels");

  if (bot.agents.length === 0) {
    // The state this column exists for: a bot registered, live, and answering
    // nobody, which from a chat window is indistinguishable from a broken one.
    return (
      <div className={cn("flex flex-wrap items-center gap-2", className)}>
        <span className="text-muted-foreground text-xs">{t("noAgentBound")}</span>
        {onBind && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            data-tour="channels-binding"
            aria-label={t("bindAgentTo", { bot: bot.name })}
            onClick={() => onBind(bot)}
          >
            {t("bindAgent")}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {bot.agents.map((agent) => (
        <span key={agent.exposure_id} className="flex items-center gap-1.5">
          <AgentAvatar
            agentId={agent.id}
            slug={agent.slug}
            hasAvatar={agent.has_avatar}
            size="sm"
          />
          {/* The Availability tab is where its environment, pause, lookups and
              instructions are changed. */}
          <Link
            href={`${ROUTES.AGENT_DETAIL(agent.id)}?tab=availability`}
            className="truncate text-xs hover:underline"
          >
            @{agent.slug}
          </Link>
          {!agent.is_active && <Badge variant="secondary">{t("bindingPaused")}</Badge>}
          {onUnbind && (
            <UnbindSlot
              bot={bot}
              agent={agent}
              busy={busy}
              mayPublish={mayPublish}
              onUnbind={onUnbind}
            />
          )}
        </span>
      ))}
    </div>
  );
}
