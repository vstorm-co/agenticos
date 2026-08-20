"use client";

import { useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";

import { MessageList } from "@/components/chat/message-list";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "@/components/ui";
import { useRunTranscript } from "@/hooks";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { qk } from "@/lib/query-keys";
import type { ChatMessage } from "@/types";
import type { Trigger } from "@/types/triggers";

const POLL_WHILE_WAITING_MS = 3000;

/**
 * What a trigger has actually done: the run-log conversation every fire appends
 * to, read the way the chat reads a thread.
 *
 * Keyed on `last_run_id` rather than `conversation_id`: the transcript endpoint
 * is gated on run visibility (the same reach a trigger's own controls have),
 * where the conversation endpoint is scoped to its owner, so a manager who did
 * not create the trigger can still read what it ran. `scope: "conversation"`
 * widens that one run to the whole log.
 *
 * A trigger that has never fired has no `last_run_id` and no runs, so the
 * transcript is not asked for at all - "no messages yet" is said plainly rather
 * than drawn as an empty thread, which a failed read would look identical to.
 *
 * `pendingSince` is the moment "Run now" was pressed, or null. Because a fire is
 * dispatched after the request commits, `last_run_id` still names the previous
 * run for a moment; while no reply has been recorded *after* that moment the
 * view shows the prompt just sent and a waiting animation, and polls the log
 * until a fresh assistant turn appears - at which point the placeholder gives
 * way to what the agent actually said. A timestamp rather than a flag so the
 * waiting state is derived, never a second copy of it to keep in sync.
 */
export function TriggerRunsView({
  trigger,
  pendingSince,
}: {
  trigger: Trigger;
  pendingSince: number | null;
}) {
  const t = useTranslations("triggers");
  const runId = trigger.last_run_id;

  const { transcript, isLoading, error } = useRunTranscript(runId ?? "", "conversation", {
    enabled: runId !== null,
    refetchInterval: pendingSince !== null ? POLL_WHILE_WAITING_MS : false,
  });

  // On a trigger that has never fired, "Run now" leaves last_run_id null until
  // the background fire records its run - and the transcript query above is
  // disabled without an id, so nothing else would ever notice it appearing. The
  // trigger itself is what has to be re-read: poll its list queries until the
  // id arrives, at which point the transcript poll takes over.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (pendingSince === null || runId !== null) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: qk.triggers.all() });
    }, POLL_WHILE_WAITING_MS);
    return () => clearInterval(timer);
  }, [pendingSince, runId, queryClient]);

  const repliedAfter =
    pendingSince !== null &&
    (transcript?.items ?? []).some(
      (item) =>
        item.role === "assistant" &&
        item.created_at !== undefined &&
        Date.parse(item.created_at) > pendingSince,
    );
  const waiting = pendingSince !== null && !repliedAfter;

  const messages = useMemo<ChatMessage[]>(
    () =>
      (transcript?.items ?? []).map((item) =>
        conversationMessageToChatMessage({
          id: item.id,
          conversation_id: transcript?.conversation_id ?? "",
          role: item.role as "user" | "assistant" | "system",
          content: item.content,
          created_at: item.created_at ?? "",
          thinking: item.thinking,
          parts: item.parts,
          tool_calls: item.tool_calls,
          run_id: item.run_id,
        }),
      ),
    [transcript],
  );

  if (runId !== null && isLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  // A read that answered with nothing once the wait is over is a failure, not an
  // empty log - said out loud so it is never mistaken for "this trigger is idle".
  if (runId !== null && (error || transcript === undefined)) {
    return <ErrorState title={t("runsCouldNotBeRead")} />;
  }

  if (messages.length === 0 && !waiting) {
    return (
      <EmptyState
        icon={MessagesSquare}
        title={t("noMessagesYet")}
        description={t("noMessagesDescription")}
      />
    );
  }

  const shown: ChatMessage[] = waiting
    ? [
        ...messages,
        { id: "pending-user", role: "user", content: trigger.prompt, timestamp: new Date() },
        {
          id: "pending-agent",
          role: "assistant",
          content: "",
          isStreaming: true,
          timestamp: new Date(),
        },
      ]
    : messages;

  return <MessageList messages={shown} />;
}

/**
 * The runs view in a right-hand drawer, opened from a trigger row.
 *
 * A sheet, mirroring the Activity page's run detail: a row is a door to what it
 * has done, and the drawer keeps the list it opened over visible behind it.
 */
export function TriggerRunsSheet({
  trigger,
  pendingSince,
  open,
  onOpenChange,
}: {
  trigger: Trigger;
  pendingSince: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl">
        <SheetHeader className="px-5">
          <SheetTitle className="text-sm">
            {trigger.name ?? trigger.agent_name ?? t("runsTitle")}
          </SheetTitle>
          <SheetClose onClick={() => onOpenChange(false)} />
        </SheetHeader>
        <div className="flex-1 overflow-y-auto p-5">
          {open && <TriggerRunsView trigger={trigger} pendingSince={pendingSince} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}
