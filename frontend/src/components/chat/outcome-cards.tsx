"use client";

import Link from "next/link";
import { BellRing } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState } from "@/components/states";
import { getErrorMessage } from "@/lib/api-error";
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
  const tErrors = useTranslations("errors");
  const { settle, isPending } = useSettleOutcome(via);
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {ACTIONS.map((action) => (
        <Button
          key={action}
          size="sm"
          variant={action === "resolve" ? "default" : "outline"}
          disabled={isPending}
          onClick={() =>
            void settle({ id, action }).catch((error: unknown) => {
              toast.error(getErrorMessage(error, tErrors));
            })
          }
        >
          {t(action)}
        </Button>
      ))}
    </div>
  );
}

/**
 * Open outcomes from this chat. Approval notices lead to decisions and disappear
 * while the chat has a decision panel or is working; other outcomes keep their actions.
 */
export function OutcomeCards({
  conversationId,
  className,
  hasApprovalPanel = false,
  isWorking = false,
}: {
  conversationId: string;
  hasApprovalPanel?: boolean;
  isWorking?: boolean;
  className?: string;
}) {
  const t = useTranslations("outcomes");
  const { outcomes, error, retry } = useConversationOutcomes(conversationId);
  if (error)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void retry() }}
        className={className}
      />
    );
  // Several runs can leave notices in the same chat. The decision panel owns
  // approvals here; duplicating older or source-less notices adds no action.
  const visible = outcomes.filter(
    (outcome) => !(outcome.kind === "approval_requested" && (hasApprovalPanel || isWorking)),
  );
  if (visible.length === 0) return null;
  return (
    <ul aria-label={t("label")} className={cn("space-y-2", className)}>
      {visible.map((outcome) => (
        <li
          key={outcome.id}
          aria-label={outcome.summary}
          className="border-border bg-card flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center"
        >
          <BellRing className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-pretty">{outcome.summary}</p>
            {outcome.kind !== "approval_requested" && outcome.context_url && (
              <Link
                href={outcome.context_url}
                prefetch={false}
                className="text-muted-foreground text-xs underline-offset-4 hover:underline"
              >
                {t("open")}
              </Link>
            )}
          </div>
          {outcome.kind === "approval_requested" ? (
            <Link
              href={outcome.context_url ?? "/runs?tab=approvals"}
              prefetch={false}
              className="text-foreground hover:bg-accent rounded-md border px-3 py-2 text-sm font-medium"
            >
              {t("reviewApproval")}
            </Link>
          ) : (
            <OutcomeActions id={outcome.id} via="chat" />
          )}
        </li>
      ))}
    </ul>
  );
}
