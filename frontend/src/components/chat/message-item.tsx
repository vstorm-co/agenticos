"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
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
      <pre className="text-muted-foreground border-foreground/10 mt-2 max-h-72 overflow-y-auto border-l pl-3.5 text-[12px] leading-relaxed whitespace-pre-wrap">
        {text}
      </pre>
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
        {sources.length} source{sources.length !== 1 ? "s" : ""}
      </span>
    </button>
  );
}

/** One stretch of a turn: a run of tool steps, or a single part of another kind. */
interface PartRun {
  kind: "tools" | "other";
  parts: MessagePart[];
  /** Whether this run ends the turn, which is what may still be streaming. */
  isLast: boolean;
}

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
    if ((part.type === "text" || part.type === "thinking") && part.content) {
      runs.push({ kind: "other", parts: [part], isLast: false });
    }
  }
  const last = runs.at(-1);
  if (last !== undefined) last.isLast = true;
  return runs;
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
  onRegenerate?: () => void;
}

export function MessageItem({
  message,
  agent,
  groupPosition,
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
        t("groupRelativeFlexGap"),
        isGrouped ? "py-2 sm:py-3" : "py-3 sm:py-4",
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
        className={cn(
          "z-10 flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-full sm:h-9 sm:w-9",
          isUser ? "bg-foreground text-background" : "bg-muted text-foreground",
          isGrouped && !isUser && "ring-background ring-2",
        )}
      >
        {isUser && authUser?.avatar_url ? (
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
          isUser && t("flexFlexColItems"),
        )}
      >
        {/* Which agent answered, on the turn it answered. A conversation that
            switched agents mid-way says so, instead of relabelling the whole
            thread with whatever is selected now. */}
        {!isUser && agent && (
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
                      title={`Open ${att.file.filename}`}
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
                    <FileChip
                      key={att.file.id}
                      filename={att.file.filename}
                      hint={att.file.mime_type}
                      onClick={() => openPreview(att.file)}
                    />
                  ) : (
                    <FileChip key={att.id} filename={t("attachedFile")} href={getFileUrl(att.id)} />
                  ),
                )}
              </div>
            );
          })()}

        {(() => {
          const rawParts = message.parts ?? [];
          const parts = rawParts;
          const useParts = !isUser && parts.length > 0;

          // "Thinking…" placeholder - shown until anything streams in.
          const showPlaceholder =
            !isUser &&
            message.isStreaming &&
            !message.content &&
            parts.length === 0 &&
            (!message.toolCalls || message.toolCalls.length === 0);

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
                runsOf(parts).map((run, index) =>
                  run.kind === "tools" ? (
                    <div key={run.parts[0]?.id ?? index} className="w-full">
                      {/* The rail folds its own earlier steps away, but it cannot see
                          what is in them - so whether this run holds something a person
                          has to answer is decided here, where the statuses are. */}
                      <AgentSteps
                        showAll={run.parts.some(
                          (part) =>
                            part.toolCall?.status === "error" ||
                            part.toolCall?.status === "awaiting_approval",
                        )}
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
                  ) : run.parts[0]?.type === "thinking" ? (
                    <ThinkingBlock
                      key={run.parts[0].id}
                      text={run.parts[0].content ?? ""}
                      open={Boolean(message.isStreaming) && run.isLast}
                      isStreaming={Boolean(message.isStreaming)}
                    />
                  ) : (
                    <TextBubble
                      key={run.parts[0]?.id ?? index}
                      text={run.parts[0]?.content ?? ""}
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
                  {message.toolCalls && message.toolCalls.length > 0 && (
                    <div className="w-full">
                      <AgentSteps>
                        {message.toolCalls.map((toolCall, step) => (
                          <ToolCallCard
                            key={toolCall.id}
                            toolCall={toolCall}
                            conversationId={message.conversationId}
                            startOpen={
                              openLastStep && step === (message.toolCalls?.length ?? 0) - 1
                            }
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

function FileChip({
  filename,
  hint,
  onClick,
  href,
}: {
  filename: string;
  hint?: string;
  /** When provided, clicking opens the file in the preview panel. */
  onClick?: () => void;
  /** Fallback for legacy attachments without full metadata - opens in new tab. */
  href?: string;
}) {
  const ext = filename.includes(".") ? filename.split(".").pop()!.toLowerCase() : null;
  const className =
    "border-foreground/15 bg-card hover:border-foreground/40 inline-flex max-w-xs items-center gap-2 rounded-xl border px-3 py-2 transition-colors text-left";
  const inner = (
    <>
      <span className="bg-foreground/8 text-foreground/65 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
        <FileText className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-foreground block truncate text-sm font-medium">{filename}</span>
        {ext && (
          <span className="text-foreground/55 font-mono text-[10px] tracking-wider uppercase">
            {ext}
          </span>
        )}
      </span>
      <Paperclip className="text-foreground/40 h-3.5 w-3.5 shrink-0" />
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className} title={hint ?? filename}>
        {inner}
      </button>
    );
  }
  return (
    <a
      href={href ?? "#"}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
      title={hint ?? filename}
    >
      {inner}
    </a>
  );
}
