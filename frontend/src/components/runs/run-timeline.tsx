"use client";

import { useEffect, useRef } from "react";
import { useLocale, useTranslations } from "next-intl";
import { MessagesSquare, ThumbsDown } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useRunTranscript } from "@/hooks";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { cn, formatDateTime } from "@/lib/utils";
import type { ChatMessage, ToolCall } from "@/types";
import type { RunTranscriptMessage } from "@/types/runs";

/**
 * The whole conversation the run sits in, scrolled to the run - the trace the
 * detail view is for.
 *
 * The thread, not only the run's own turns, because a run is an answer to
 * something: what the agent was asked three turns earlier is usually the
 * explanation for what it did here. The turns this run wrote are marked and the
 * first of them is scrolled into view, so the reader lands on the run and can
 * scroll up for the context.
 *
 * Tool calls render *raw* - the name, the stored status, the input as JSON, the
 * output as it was recorded - deliberately not through the chat's renderers.
 * This is the operator's view: the question here is "what exactly went over the
 * wire", and a chart drawn pretty is an answer to a different question the chat
 * already gives. The *order* of a turn's parts is still the chat's own replay
 * (`conversationMessageToChatMessage`), so the two surfaces cannot disagree
 * about what happened when.
 *
 * A run with no conversation behind it - an API call, a resumed run - has no
 * transcript by construction, and says so rather than drawing an empty page
 * that reads as "the run did nothing".
 */
export function RunTimeline({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const { transcript, isLoading, error } = useRunTranscript(runId, "conversation");

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  if (error || transcript === undefined) {
    return <ErrorState title={t("transcriptCouldNotBeRead")} />;
  }
  if (transcript.conversation_id === null) {
    return (
      <EmptyState
        icon={MessagesSquare}
        title={t("noTranscriptRecorded")}
        description={t("thisRunRanWithNoConversation")}
      />
    );
  }

  const firstOwnTurnId = transcript.items.find((item) => item.run_id === runId)?.id;

  return (
    <ol className="space-y-4">
      {transcript.items.map((item) => (
        <TimelineTurn
          key={item.id}
          item={item}
          ownTurn={item.run_id === runId}
          scrollTarget={item.id === firstOwnTurnId}
          locale={locale}
        />
      ))}
    </ol>
  );
}

function TimelineTurn({
  item,
  ownTurn,
  scrollTarget,
  locale,
}: {
  item: RunTranscriptMessage;
  /** Written by the focused run - marked, where the rest of the thread is context. */
  ownTurn: boolean;
  scrollTarget: boolean;
  locale: string;
}) {
  const t = useTranslations("pages.runs");
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    // Land the reader on the run, not at the top of a thread that may be long.
    // Optional-called: jsdom has no scrollIntoView, and a test must not need one.
    if (scrollTarget) ref.current?.scrollIntoView?.({ block: "start" });
  }, [scrollTarget]);

  // The chat's own replay: stored parts in their stored order, or the
  // reconstructed reasoning → tools → answer for a turn written before the
  // order was recorded. Order logic is shared; only the rendering here is raw.
  const message: ChatMessage = conversationMessageToChatMessage({
    id: item.id,
    conversation_id: "",
    role: item.role as "user" | "assistant" | "system",
    content: item.content,
    created_at: item.created_at ?? "",
    thinking: item.thinking,
    parts: item.parts,
    tool_calls: item.tool_calls,
  });
  const dislikes = item.rating_count?.dislikes ?? 0;
  const roleKey =
    item.role === "user" ? "turnUser" : item.role === "assistant" ? "turnAgent" : "turnSystem";

  return (
    <li
      ref={ref}
      className={cn(
        "relative border-l-2 pl-4",
        ownTurn ? "border-primary" : "border-border opacity-70",
      )}
    >
      <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
        <span className="text-foreground font-medium">{t(roleKey)}</span>
        {item.created_at && <span>{formatDateTime(item.created_at, locale)}</span>}
        {ownTurn && <span className="text-primary font-medium">{t("thisRun")}</span>}
        {dislikes > 0 && (
          <span className="text-destructive inline-flex items-center gap-1">
            <ThumbsDown className="h-3 w-3" aria-hidden />
            {t("ratedDownCount", { count: dislikes })}
          </span>
        )}
      </div>

      {item.role === "user" ? (
        <div className="bg-muted/40 rounded-md p-3 text-sm whitespace-pre-wrap">{item.content}</div>
      ) : (
        <div className="space-y-2">
          {(message.parts ?? []).map((part) =>
            part.type === "tool" && part.toolCall !== undefined ? (
              <RawToolCall key={part.id} toolCall={part.toolCall} />
            ) : part.type === "thinking" ? (
              <details key={part.id} className="text-muted-foreground text-sm">
                <summary className="cursor-pointer select-none">{t("reasoning")}</summary>
                <div className="mt-1 whitespace-pre-wrap">{part.content}</div>
              </details>
            ) : (
              <div key={part.id} className="text-sm whitespace-pre-wrap">
                {part.content}
              </div>
            ),
          )}
        </div>
      )}

      {/* The words somebody left with a thumb down - the complaint, beside the
          answer it judged. */}
      {item.rating_comment && (
        <blockquote className="text-muted-foreground border-destructive/40 mt-2 border-l-2 pl-3 text-sm italic">
          {item.rating_comment}
        </blockquote>
      )}
    </li>
  );
}

/**
 * One tool call, as it went over the wire: the input JSON and the recorded
 * output, under the tool's registered name and stored status. Deliberately no
 * pretty renderer - that is the chat's answer to a different question.
 */
function RawToolCall({ toolCall }: { toolCall: ToolCall }) {
  const t = useTranslations("pages.runs");
  return (
    <details className="rounded-md border">
      <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 font-mono text-xs select-none">
        <span>{toolCall.name}</span>
        <span className="text-muted-foreground">{toolCall.status}</span>
      </summary>
      <div className="space-y-2 border-t p-3">
        <p className="text-muted-foreground text-xs tracking-wide uppercase">{t("toolInput")}</p>
        <pre className="bg-muted/40 overflow-x-auto rounded p-2 text-xs">
          {JSON.stringify(toolCall.args, null, 2)}
        </pre>
        {toolCall.result != null && (
          <>
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              {t("toolOutput")}
            </p>
            <pre className="bg-muted/40 overflow-x-auto rounded p-2 text-xs whitespace-pre-wrap">
              {typeof toolCall.result === "string"
                ? toolCall.result
                : JSON.stringify(toolCall.result, null, 2)}
            </pre>
          </>
        )}
      </div>
    </details>
  );
}
