"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { MessagesSquare, Paperclip, ThumbsDown } from "lucide-react";

import { CopyButton } from "@/components/chat/copy-button";
import { MessageCost } from "@/components/chat/message-cost";
import { FileCard, FileViewer } from "@/components/files";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useRunTranscript } from "@/hooks";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { attachmentAccess, getFileUrl } from "@/lib/file-api";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import { glideOrJump } from "@/lib/motion";
import { cn, formatDateTime } from "@/lib/utils";
import type { ChatMessage, ChatMessageFile, ToolCall } from "@/types";
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
 * **A turn is rendered from the stored row whole**, not from a hand-copied
 * subset of it. `conversationMessageToChatMessage` has always mapped the files
 * and the per-turn cost; this surface used to rebuild its argument field by
 * field and dropped both on the way, so a question with a document attached to
 * it rendered as a question with nothing attached to it - on the one page whose
 * job is to say what actually reached the model.
 *
 * Tool calls render *raw* - the name, the stored status, the input as JSON, the
 * output as it was recorded - deliberately not through the chat's renderers.
 * This is the operator's view: the question here is "what exactly went over the
 * wire", and a chart drawn pretty is an answer to a different question the chat
 * already gives. The *order* of a turn's parts is still the chat's own replay,
 * so the two surfaces cannot disagree about what happened when.
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

  // The anchor is the answer's own, not the id asked for. Stepping through a
  // thread holds the previous transcript while the next is in flight, and the
  // two are the same turns - so marking them against the run being *requested*
  // would blank the marks for as long as the request took, on a list that was
  // already right. `run_id` moves when the answer does, which is what makes the
  // step read as the anchor gliding rather than the page reloading.
  const anchorRunId = transcript.run_id;
  const firstOwnTurnId = transcript.items.find((item) => item.run_id === anchorRunId)?.id;

  return (
    <ol className="space-y-4">
      {transcript.items.map((item) => (
        <TimelineTurn
          key={item.id}
          item={item}
          ownTurn={item.run_id === anchorRunId}
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
    //
    // Glided rather than jumped, because this fires again on every step through
    // the thread: two runs of one conversation share a transcript, so an arrow
    // press moves only the anchor, and a jump between two turns of a list that
    // did not otherwise change reads as the page having been replaced.
    if (scrollTarget) ref.current?.scrollIntoView?.({ block: "start", behavior: glideOrJump() });
  }, [scrollTarget]);

  // The stored row, handed over whole. `RunTranscriptMessage` is declared
  // structurally compatible with the conversation reader's `RawMessage` for
  // exactly this, so the parts, the files and the cost all come back from one
  // mapping rather than from a list of fields somebody has to remember to grow.
  const message: ChatMessage = conversationMessageToChatMessage({
    ...item,
    conversation_id: "",
    role: item.role as "user" | "assistant" | "system",
    created_at: item.created_at ?? "",
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
      <div className="text-muted-foreground mb-1 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-foreground font-medium">{t(roleKey)}</span>
        {item.created_at && <span>{formatDateTime(item.created_at, locale)}</span>}
        {ownTurn && <span className="text-primary font-medium">{t("thisRun")}</span>}
        {/* Which model wrote this turn, on the turn. A thread can be switched
            between models mid-conversation, so the run header's one label is
            the last answer's rather than every answer's. */}
        {item.model_name != null && <span className="font-mono">{item.model_name}</span>}
        {message.usage && <MessageCost usage={message.usage} />}
        {item.context_used_tokens != null && (
          <span className="font-mono" title={t("contextCarriedHint")}>
            {t("contextCarried", { tokens: item.context_used_tokens })}
          </span>
        )}
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

      {message.files && message.files.length > 0 && <TurnAttachments files={message.files} />}

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
 * What arrived with the turn, openable.
 *
 * Openable and not only named, because "the agent answered badly" and "the
 * agent was handed a scan with no text layer in it" are the same transcript
 * until somebody can look at the file. The card and the viewer are the ones
 * every other surface uses, so a document means the same thing here as it does
 * in the chat it was uploaded to.
 */
function TurnAttachments({ files }: { files: ChatMessageFile[] }) {
  const t = useTranslations("pages.runs");
  const [opened, setOpened] = useState<ChatMessageFile | null>(null);
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-muted-foreground inline-flex items-center gap-1 text-xs tracking-wide uppercase">
        <Paperclip className="h-3 w-3" aria-hidden />
        {t("attachedFiles", { count: files.length })}
      </p>
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <FileCard
            key={file.id}
            name={file.filename}
            mimeType={file.mime_type}
            imageUrl={
              resolveFileKind(file.filename, file.mime_type) === "image"
                ? getFileUrl(file.id)
                : null
            }
            typeLabel={suffixOf(file.filename).toUpperCase() || file.file_type.toUpperCase()}
            onOpen={() => setOpened(file)}
          />
        ))}
      </div>
      {opened !== null && (
        <FileViewer
          file={{ name: opened.filename, mimeType: opened.mime_type }}
          access={attachmentAccess({ id: opened.id, filename: opened.filename })}
          onClose={() => setOpened(null)}
        />
      )}
    </div>
  );
}

/**
 * One tool call, as it went over the wire: the input JSON and the recorded
 * output, under the tool's registered name and stored status. Deliberately no
 * pretty renderer - that is the chat's answer to a different question.
 *
 * Both blocks are copyable, because the next thing somebody does with a tool
 * input that produced a wrong answer is paste it somewhere and run it again.
 */
function RawToolCall({ toolCall }: { toolCall: ToolCall }) {
  const t = useTranslations("pages.runs");
  const args = JSON.stringify(toolCall.args, null, 2);
  const result =
    typeof toolCall.result === "string"
      ? toolCall.result
      : JSON.stringify(toolCall.result, null, 2);
  return (
    <details className="rounded-md border">
      <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 font-mono text-xs select-none">
        <span>{toolCall.name}</span>
        <span className="text-muted-foreground">{toolCall.status}</span>
      </summary>
      <div className="space-y-2 border-t p-3">
        <div className="group flex items-center justify-between gap-2">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">{t("toolInput")}</p>
          <CopyButton text={args} />
        </div>
        <pre className="bg-muted/40 overflow-x-auto rounded p-2 text-xs">{args}</pre>
        {toolCall.result != null && (
          <>
            <div className="group flex items-center justify-between gap-2">
              <p className="text-muted-foreground text-xs tracking-wide uppercase">
                {t("toolOutput")}
              </p>
              <CopyButton text={result} />
            </div>
            <pre className="bg-muted/40 overflow-x-auto rounded p-2 text-xs whitespace-pre-wrap">
              {result}
            </pre>
          </>
        )}
      </div>
    </details>
  );
}
