"use client";

import { Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { ActionTooltip, Button, TooltipProvider } from "@/components/ui";
import type { BotAgent, ChannelBot } from "@/types/channels";

/** What the viewer may publish, as the agents read answered it. */
export type PublishAnswer = "pending" | "failed" | ((agentId: string) => boolean);

/**
 * The unbind control for one bound agent, drawn only when the viewer may
 * publish that agent. While the answer is pending it reserves the button's
 * slot, so the row does not shift when the button appears.
 */
export function UnbindSlot({
  bot,
  agent,
  busy,
  mayPublish,
  onUnbind,
}: {
  bot: ChannelBot;
  agent: BotAgent;
  busy: boolean;
  mayPublish: PublishAnswer;
  onUnbind: (bot: ChannelBot, agent: BotAgent) => void;
}) {
  const t = useTranslations("pages.channels");
  if (mayPublish === "pending") {
    return <span aria-hidden data-testid="unbind-slot" className="size-8" />;
  }
  if (typeof mayPublish !== "function" || !mayPublish(agent.id)) return null;
  return (
    <TooltipProvider>
      <ActionTooltip label={t("unbindAgent", { agent: agent.slug, bot: bot.name })} disabled={busy}>
        <Button
          variant="ghost"
          size="icon-sm"
          disabled={busy}
          data-tour="channels-binding"
          aria-label={t("unbindAgent", { agent: agent.slug, bot: bot.name })}
          onClick={() => onUnbind(bot, agent)}
        >
          <Unlink className="h-4 w-4" />
        </Button>
      </ActionTooltip>
    </TooltipProvider>
  );
}
