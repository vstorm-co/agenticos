"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import { toolEntry } from "@/lib/tool-catalog";
import type { ChatMessage, ChatMessageFile, MessagePart } from "@/types";
import type { Agent } from "@/types/agents";
import { ToolCallCard } from "./tool-call-card";
import { AgentSteps } from "./agent-step";
import { MarkdownContent } from "./markdown-content";
import { CopyButton } from "./copy-button";
import { MessageCost } from "./message-cost";
import { RatingButtons } from "./rating-buttons";
import { useChatStore, useFilePreviewStore } from "@/stores";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { Bot, FileText, Globe, Paperclip, RefreshCw, Sparkles, User } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useAuthStore } from "@/stores";
import { getFileUrl } from "@/lib/file-api";
import { FileCard } from "@/components/files";
import { extractSources } from "@/lib/chat-sources";
import type { SourceItem } from "@/lib/chat-sources";

function ThinkingBlock({
  text,
  open,
  isStreaming,
}: {
  text: string;
  open: boolean;
  isStreaming: boolean;
}) {
  return (
    <details className="group" open={open}>
      {/* A line, not a box. The reasoning is an aside on the way to an answer, and a
          bordered panel around it gives it more weight on the page than the answer
          itself - which is backwards, and was the loudest thing in every turn. */}
      <summary className="text-muted-foreground hover:text-foreground/80 flex cursor-pointer items-center gap-2 text-[13px] select-none">
        <Sparkles className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
        Thought about it
        {isStreaming && (
          <span className="bg-foreground/40 inline-block h-1 w-1 animate-pulse rounded-full" />
        )}
      </summary>
      {/* Markdown, not a `<pre>`. Reasoning is written the way the answer is - the
          models that expose it head each block with `**Analyzing attached files**`
          and use lists inside them - so a monospaced block rendered the asterisks
          and the underscores literally, in a face that says "this is output"
          about the one part of a turn that is prose. Still the muted, smaller,
          scrollable aside it was; only the text is read properly now. */}
      <div className="text-muted-foreground border-foreground/10 mt-2 max-h-72 overflow-y-auto border-l pl-3.5 text-[13px] leading-relaxed">
        <MarkdownContent content={text} />
      </div>
    </details>
  );
}

/**
 * What was said, by whichever side said it.
 *
 * **Only the person gets a bubble.** An assistant turn is prose - headings, lists,
 * code, a table - and a rounded grey box around it makes every answer look like a
 * chat message from 2016: the fill fights the code blocks nested inside it, the
 * padding eats the width a table needs, and a turn made of three parts arrives as
 * three separate boxes with hairlines between them. Unwrapped, the answer is the
 * page, which is what every tool of this kind settled on. The user's message keeps
 * its bubble precisely because it is the short one, and the contrast is what makes a
 * long transcript scannable at all.
 */
function TextBubble({
  text,
  showCursor,
  isUser,
  onCiteClick,
}: {
  text: string;
  showCursor: boolean;
  isUser: boolean;
  onCiteClick?: (index: number) => void;
}) {
  if (isUser) {
    return (
      <div className="bg-foreground text-background relative rounded-2xl rounded-tr-sm px-3 py-2 sm:px-4 sm:py-2.5">
        <p className="text-sm break-words whitespace-pre-wrap">{text}</p>
      </div>
    );
  }

  return (
    <div className="prose-sm max-w-none text-[15px] leading-relaxed">
      <MarkdownContent content={text} onCiteClick={onCiteClick} />
      {showCursor && (
        <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-current" />
      )}
    </div>
  );
}

function SourcesButton({ sources, onClick }: { sources: SourceItem[]; onClick: () => void }) {
  const t = useTranslations("chat");
  const ragCount = sources.filter((s) => s.type === "rag").length;
  const webCount = sources.filter((s) => s.type === "web").length;

  return (
    <button
      type="button"
      onClick={onClick}
      className="border-foreground/15 bg-background hover:border-foreground/30 hover:bg-foreground/5 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors"
    >
      <span className="flex -space-x-1">
        {ragCount > 0 && (
          <span className="bg-muted border-background inline-flex h-4 w-4 items-center justify-center rounded-full border">
            <FileText className="text-foreground/60 h-2.5 w-2.5" />
          </span>
        )}
        {webCount > 0 && (
          <span className="bg-muted border-background inline-flex h-4 w-4 items-center justify-center rounded-full border">
            <Globe className="text-foreground/60 h-2.5 w-2.5" />
          </span>
        )}
      </span>
      <span className="text-foreground/60 text-[11px] font-medium">
        {t("sourceCount", { count: sources.length })}
      </span>
    </button>
  );
}

/**
 * One stretch of a turn: a run of tool steps, or a single part of another kind.
 *
 * The two shapes are separate so the render has nothing to defend against - a run of
 * tools always has a first step, and a part of another kind always has the text that
 * earned it a run.
 */
type PartRun =
  | {
      kind: "tools";
      /** Never empty: the run exists because a call opened it. */
      parts: [MessagePart, ...MessagePart[]];
      /** Whether this run ends the turn, which is what may still be streaming. */
      isLast: boolean;
    }
  | { kind: "other"; part: MessagePart; content: string; isLast: boolean };

/**
 * The turn's parts, with consecutive tool calls gathered into one run.
 *
 * Grouping is what makes the steps read as one thread: the rail they hang from has to
 * be a single element, because a border on each row leaves gaps between them and a
 * dashed line says something this does not mean. A part of any other kind - text, or
 * thinking - closes the run, which is right: the agent said something, so what follows
 * is a new stretch of work.
 *
 * Empty text and thinking parts are dropped rather than rendered as empty bubbles,
 * which is what the flat map did with them.
 */
export function runsOf(parts: MessagePart[]): PartRun[] {
  const runs: PartRun[] = [];
  for (const part of parts) {
    if (part.type === "tool" && part.toolCall) {
      const open = runs.at(-1);
      if (open?.kind === "tools") open.parts.push(part);
      else runs.push({ kind: "tools", parts: [part], isLast: false });
      continue;
    }
    if (
      (part.type === "text" || part.type === "thinking") &&
      part.content !== undefined &&
      part.content !== ""
    ) {
      runs.push({ kind: "other", part, content: part.content, isLast: false });
    }
  }
  const last = runs.at(-1);
  if (last !== undefined) last.isLast = true;
  return runs;
}

/**
 * Whether this run must show every step rather than fold all but the last.
 *
 * Three reasons, and they are all "the reader would otherwise miss something":
 * a call that failed, one parked waiting for their approval, and a step whose
 * result *is* the answer - a chart. The rail's default is right for work nobody
 * asked to watch, and wrong for a turn that drew three charts: two of them
 * became the line "2 earlier steps", so the same turn showed three pictures live
 * and one after a reload.
 *
 * Which steps are payloads comes from `opensOnSight` in `lib/tool-catalog.ts`,
 * the same row the card reads to decide whether to open itself - so a tool is
 * described in one place and the rail and the card cannot disagree about it.
 */
export function mustShowEveryStep(parts: MessagePart[]): boolean {
  return parts.some((part) => {
    const call = part.toolCall;
    if (!call) return false;
    if (call.status === "error" || call.status === "awaiting_approval") return true;
    return toolEntry(call.name)?.opensOnSight === true;
  });
}

interface MessageItemProps {
  message: ChatMessage;
  /**
   * Open this turn's last tool step on mount.
   *
   * Set for the most recent turn that used a tool - see `lastToolTurnIndex`. The last
   * thing the agent did stays open when somebody comes back to the chat, and everything
   * before it is one line. Opening every finished call made a reopened conversation a
   * wall of results; opening none of them hid the thing that was asked for.
   */
  openLastStep?: boolean;
  /** The published agent that answered. Absent for the general assistant. */
  /** The agent that produced this turn, when one did. */
  agent?: Agent;
  groupPosition?: "first" | "middle" | "last" | "single";
  /**
   * This message continues the turn above it rather than starting one.
   *
   * True for the later segments of a run that parked on an approval and was
   * resumed - see `continuesTurn` in `MessageList`. The avatar and the agent's
   * name are drawn once at the top of the turn; a segment that repeated them made
   * one run read as three agents answering the same question. The gutter is kept
   * empty rather than removed, so the whole turn stays in one column.
   */
  continuesTurn?: boolean;
  onRegenerate?: () => void;
}

export function MessageItem({
  message,
  agent,
  groupPosition,
  continuesTurn = false,
  openLastStep = false,
  onRegenerate,
}: MessageItemProps) {
  const t = useTranslations("chat");
  const isUser = message.role === "user";
  const updateMessage = useChatStore((state) => state.updateMessage);
  const openPreview = useFilePreviewStore((s) => s.open);
  const openSources = useSourcesPanelStore((s) => s.open);
  const { user: authUser, avatarVersion } = useAuthStore();
  const isGrouped = groupPosition && groupPosition !== "single";

  const sources = !isUser ? extractSources(message) : [];
  const hasSources = sources.length > 0 && !message.isStreaming;
  const onCiteClick = hasSources ? (index: number) => openSources(sources, index) : undefined;

  return (
    <div
      className={cn(
        "group relative flex gap-2 overflow-visible sm:gap-4",
        isGrouped ? "py-2 sm:py-3" : "py-3 sm:py-4",
        // Tight against the segment above, because it is the same turn: the
        // ordinary gap between messages would read as a pause the run never took.
        continuesTurn && "pt-0",
        isUser && "flex-row-reverse",
      )}
    >
      {" "}
      {isGrouped && !isUser && (
        <div
          className="bg-border absolute left-[15px] w-0.5 sm:left-[17px]"
          style={
            groupPosition === "first"
              ? { top: "24px", bottom: "0" }
              : groupPosition === "last"
                ? { top: "0", height: "24px" }
                : { top: "0", bottom: "0" }
          }
        />
      )}
      <div
        aria-hidden={continuesTurn}
        className={cn(
          "z-10 flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-full sm:h-9 sm:w-9",
          // Empty, not absent: the gutter is what keeps every segment of the turn
          // in one column under the avatar that opened it.
          continuesTurn
            ? "bg-transparent"
            : isUser
              ? "bg-foreground text-background"
              : "bg-muted text-foreground",
          isGrouped && !isUser && !continuesTurn && "ring-background ring-2",
        )}
      >
        {continuesTurn ? null : isUser && authUser?.avatar_url ? (
          <Image
            src={`/api/users/avatar/${authUser.id}?v=${avatarVersion}`}
            alt=""
            width={36}
            height={36}
            className="h-full w-full object-cover"
            unoptimized
          />
        ) : isUser ? (
          <User className="h-4 w-4" />
        ) : agent ? (
          <AgentAvatar
            agentId={agent.id}
            name={agent.name}
            hasAvatar={agent.has_avatar}
            size="md"
            className="h-full w-full border-0"
          />
        ) : (
          <Bot className="h-4 w-4 sm:h-5 sm:w-5" />
        )}
      </div>
      <div
        className={cn(
          "max-w-[88%] flex-1 space-y-2 overflow-hidden sm:max-w-[85%]",
          isUser && "flex flex-col items-end",
        )}
      >
        {/* Which agent answered, on the turn it answered. A conversation that
            switched agents mid-way says so, instead of relabelling the whole
            thread with whatever is selected now. */}
        {!isUser && agent && !continuesTurn && (
          <p className="text-foreground/55 font-mono text-[10px] tracking-wider uppercase">
            {agent.name}
            {/* The version, where the transcript recorded one. An agent gets
                rewritten; this turn was answered by one frozen spec, and that
                is the thing "why did it say that" is a question about. */}
            {message.agentVersion !== undefined && (
              <span className="text-foreground/40"> · v{message.agentVersion}</span>
            )}
          </p>
        )}

        {isUser &&
          (() => {
            const attachments: AttachmentDisplay[] =
              message.files && message.files.length > 0
                ? message.files.map((f) => ({ kind: kindFor(f), file: f }))
                : (message.fileIds ?? []).map((id) => ({ kind: "unknown" as const, id }));
            if (attachments.length === 0) return null;
            return (
              <div className="flex flex-wrap gap-2">
                {attachments.map((att) =>
                  att.kind === "image" ? (
                    <button
                      type="button"
                      key={att.file.id}
                      onClick={() => openPreview(att.file)}
                      className="hover:ring-foreground/30 block overflow-hidden rounded-xl border ring-2 ring-transparent transition-all"
                      title={t("openFile", { name: att.file.filename })}
                    >
                      <Image
                        src={getFileUrl(att.file.id)}
                        alt={att.file.filename}
                        width={320}
                        height={256}
                        className="h-auto max-h-64 w-auto max-w-xs object-contain"
                        unoptimized
                      />
                    </button>
                  ) : "file" in att ? (
                    // The same card the composer showed before it was sent, and the
                    // Files panel shows beside it. It used to be a pill with a generic
                    // document glyph, so one file looked like three things.
                    <FileCard
                      key={att.file.id}
                      name={att.file.filename}
                      mimeType={att.file.mime_type}
                      onOpen={() => openPreview(att.file)}
                    />
                  ) : (
                    /* A legacy attachment, stored without the metadata the panel needs
                       to render it, so the only thing to offer is the file itself. */
                    <FileChip key={att.id} filename={t("attachedFile")} href={getFileUrl(att.id)} />
                  ),
                )}
              </div>
            );
          })()}

        {(() => {
          const parts = message.parts ?? [];
          const useParts = !isUser && parts.length > 0;
          const legacyCalls = message.toolCalls ?? [];

          // "Thinking…" placeholder - shown until anything streams in.
          const showPlaceholder =
            !isUser &&
            message.isStreaming &&
            !message.content &&
            parts.length === 0 &&
            legacyCalls.length === 0;

          return (
            <>
              {showPlaceholder && (
                <div className="flex items-center gap-2 py-1" role="status" aria-live="polite">
                  <div className="flex gap-1" aria-hidden="true">
                    <span className="bg-muted-foreground/40 h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:0ms]" />
                    <span className="bg-muted-foreground/40 h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:150ms]" />
                    <span className="bg-muted-foreground/40 h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:300ms]" />
                  </div>
                  <span className="text-muted-foreground text-xs">{t("thinking")}</span>
                </div>
              )}

              {useParts ? (
                /* Ordered timeline: render each part in arrival order, with runs of
                   tool calls on one rail - see `runsOf`. */
                runsOf(parts).map((run) =>
                  run.kind === "tools" ? (
                    <div key={run.parts[0].id} className="w-full">
                      {/* The rail folds its own earlier steps away, but it cannot see
                          what is in them - so whether this run holds something a person
                          has to answer is decided here, where the statuses and the
                          names are. */}
                      <AgentSteps
                        showAll={mustShowEveryStep(run.parts)}
                        done={run.parts.length > 1 && !message.isStreaming}
                      >
                        {run.parts.map((part, step) => (
                          <ToolCallCard
                            key={part.id}
                            toolCall={part.toolCall!}
                            conversationId={message.conversationId}
                            // The last call of that turn, which is the one whose result
                            // the reader is here for.
                            startOpen={openLastStep && run.isLast && step === run.parts.length - 1}
                          />
                        ))}
                      </AgentSteps>
                    </div>
                  ) : run.part.type === "thinking" ? (
                    <ThinkingBlock
                      key={run.part.id}
                      text={run.content}
                      open={Boolean(message.isStreaming) && run.isLast}
                      isStreaming={Boolean(message.isStreaming)}
                    />
                  ) : (
                    <TextBubble
                      key={run.part.id}
                      text={run.content}
                      showCursor={Boolean(message.isStreaming) && run.isLast}
                      isUser={isUser}
                      onCiteClick={onCiteClick}
                    />
                  ),
                )
              ) : (
                /* Legacy fallback: user / pre-parts messages. */
                <>
                  {!isUser && message.thinking && (
                    <ThinkingBlock
                      text={message.thinking}
                      open={Boolean(message.isStreaming)}
                      isStreaming={Boolean(message.isStreaming)}
                    />
                  )}
                  {message.content && (
                    <TextBubble
                      text={message.content}
                      showCursor={!isUser && Boolean(message.isStreaming)}
                      isUser={isUser}
                      onCiteClick={onCiteClick}
                    />
                  )}
                  {legacyCalls.length > 0 && (
                    <div className="w-full">
                      <AgentSteps>
                        {legacyCalls.map((toolCall, step) => (
                          <ToolCallCard
                            key={toolCall.id}
                            toolCall={toolCall}
                            conversationId={message.conversationId}
                            startOpen={openLastStep && step === legacyCalls.length - 1}
                          />
                        ))}
                      </AgentSteps>
                    </div>
                  )}
                </>
              )}
            </>
          );
        })()}

        {hasSources && !isUser && (
          <div className="mt-1">
            <SourcesButton sources={sources} onClick={() => openSources(sources, null)} />
          </div>
        )}

        {!message.isStreaming && message.content && (
          <div className={cn("flex items-center gap-2", isUser && "flex-row-reverse")}>
            {message.timestamp && (
              <span className="text-muted-foreground text-[10px]">
                {new Date(message.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            {!isUser && message.usage && <MessageCost usage={message.usage} />}
            <CopyButton
              text={message.content}
              className={cn(
                "h-6 w-6 rounded-md sm:opacity-0 sm:group-hover:opacity-100",
                isUser ? "bg-secondary hover:bg-secondary/80" : "bg-muted hover:bg-muted/80",
              )}
            />
            {!isUser && onRegenerate && (
              <button
                type="button"
                onClick={onRegenerate}
                title={t("regenerate")}
                aria-label={t("regenerate")}
                className="bg-muted hover:bg-muted/80 text-foreground/70 hover:text-foreground inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors sm:opacity-0 sm:group-hover:opacity-100"
              >
                <RefreshCw className="h-3 w-3" />
              </button>
            )}
            {!isUser && (
              <RatingButtons
                messageId={message.id}
                conversationId={message.conversationId ?? ""}
                currentRating={message.user_rating ?? null}
                ratingCount={message.rating_count ?? undefined}
                isAssistant={!isUser}
                onRatingChange={(updatedData) => {
                  updateMessage(message.id, (msg) => ({
                    ...msg,
                    user_rating: updatedData.rating,
                    rating_count: updatedData.rating_count,
                  }));
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type AttachmentDisplay =
  | { kind: "image"; file: ChatMessageFile }
  | { kind: "file"; file: ChatMessageFile }
  | { kind: "unknown"; id: string };

function kindFor(file: ChatMessageFile): "image" | "file" {
  if (file.file_type === "image") return "image";
  if (file.mime_type.startsWith("image/")) return "image";
  return "file";
}

/**
 * A legacy attachment: a link, because that is all there is to offer.
 *
 * These rows were stored without the metadata a card or a viewer needs - no name, no
 * type, no size - so the file itself is the only thing that can be shown. Everything
 * written since renders as `FileCard`, which is why the clickable half of this is
 * gone: it opened the preview panel, and the panel needs exactly the metadata these
 * do not have.
 */
function FileChip({ filename, href }: { filename: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={filename}
      className="border-foreground/15 bg-card hover:border-foreground/40 inline-flex max-w-xs items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors"
    >
      <span className="bg-foreground/8 text-foreground/65 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
        <FileText className="h-4 w-4" />
      </span>
      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
        {filename}
      </span>
      <Paperclip className="text-foreground/40 h-3.5 w-3.5 shrink-0" />
    </a>
  );
}
