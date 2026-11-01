"use client";

import Link from "next/link";
import { BellRing } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useConversationOutcomes, useSettleOutcome } from "@/hooks/use-outcomes";
import type { OutcomeAction } from "@/lib/outcomes-api";
import { cn } from "@/lib/utils";

const ACTIONS: readonly OutcomeAction[] = ["acknowledge", "resolve", "mute"];

/**
 * Acknowledge, resolve or mute one outcome from wherever it is shown (#2575).
 *
 * The same three answers in the chat and in the bell: they are one outcome, so
 * answering in either closes both, and cancels what was still to be mailed or pushed.
 */
export function OutcomeActions({
  id,
  via,
  className,
}: {
  id: string;
  via: "inbox" | "chat";
  className?: string;
}) {
  const t = useTranslations("outcomes");
  const { settle, isPending } = useSettleOutcome(via);
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {ACTIONS.map((action) => (
        <Button
          key={action}
          size="sm"
          variant={action === "resolve" ? "default" : "outline"}
          disabled={isPending}
          onClick={() => void settle({ id, action }).catch(() => {})}
        >
          {t(action)}
        </Button>
      ))}
    </div>
  );
}

/**
 * What still needs the person, from this chat: a card above the transcript for each,
 * with the three answers in it. Nothing at all when nothing does.
 */
export function OutcomeCards({
  conversationId,
  className,
}: {
  conversationId: string;
  className?: string;
}) {
  const t = useTranslations("outcomes");
  const outcomes = useConversationOutcomes(conversationId);
  if (outcomes.length === 0) return null;
  return (
    <ul aria-label={t("label")} className={cn("space-y-2", className)}>
      {outcomes.map((outcome) => (
        <li
          key={outcome.id}
          aria-label={outcome.summary}
          className="border-border bg-card flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center"
        >
          <BellRing className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-pretty">{outcome.summary}</p>
            {outcome.context_url && (
              <Link
                href={outcome.context_url}
                prefetch={false}
                className="text-muted-foreground text-xs underline-offset-4 hover:underline"
              >
                {t("open")}
              </Link>
            )}
          </div>
          <OutcomeActions id={outcome.id} via="chat" />
        </li>
      ))}
    </ul>
  );
}
