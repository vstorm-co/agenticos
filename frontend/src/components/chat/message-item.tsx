"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import type { ChatMessage, ChatMessageFile, TurnUsage } from "@/types";
import type { Agent } from "@/types/agents";
import { ToolCallCard } from "./tool-call-card";
import { AgentSteps } from "./agent-step";
import { TextBubble, ThinkingBlock, TurnParts } from "./turn-parts";
import { CopyButton } from "./copy-button";
import { MessageCost } from "./message-cost";
import { RatingButtons } from "./rating-buttons";
import { useChatStore, useFilePreviewStore } from "@/stores";
import { useMcpToolServers } from "@/hooks";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { Bot, FileText, Globe, OctagonPause, Paperclip, RefreshCw, User } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useAuthStore } from "@/stores";
import { getFileUrl } from "@/lib/file-api";
import { FileCard } from "@/components/files";
import { extractSources } from "@/lib/chat-sources";
import type { SourceItem } from "@/lib/chat-sources";

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
  /**
   * The turn ends here, so the time and the cost belong under this message.
   *
   * False for every segment of a grouped turn but the last. A run reports what it
   * has spent when it *parks*, so the footer drawn from the message that carries
   * the figure put the time, the tokens and the cost halfway up the answer, with
   * nothing under the end of it. Defaults to true: a message that is its own turn
   * ends it.
   */
  endsTurn?: boolean;
  /**
   * What the whole turn cost, when that was recorded on an earlier segment of it.
   *
   * Passed rather than read off the message for the reason above - `MessageList`
   * is the only thing that can see the turn. Absent falls back to this message's
   * own figure, which is the same thing for a turn of one message.
   */
  turnUsage?: TurnUsage;
  onRegenerate?: () => void;
}

export function MessageItem({
  message,
  agent,
  groupPosition,
  continuesTurn = false,
  endsTurn = true,
  turnUsage,
  openLastStep = false,
  onRegenerate,
}: MessageItemProps) {
  const t = useTranslations("chat");
  const isUser = message.role === "user";
  const updateMessage = useChatStore((state) => state.updateMessage);
  const openPreview = useFilePreviewStore((s) => s.open);
  const openSources = useSourcesPanelStore((s) => s.open);
  const { user: authUser, avatarVersion } = useAuthStore();
  // Read once per turn and handed to each step, so a public surface can render the
  // same step without a session - see `TurnParts`.
  const mcpServers = useMcpToolServers();
  const isGrouped = groupPosition && groupPosition !== "single";

  // The turn's cost, which a grouped turn recorded on the segment that parked
  // rather than on the one the footer is drawn under.
  const footerUsage = turnUsage ?? message.usage;
  // A turn produced something worth a footer if it wrote content *or* left a
  // timeline part - the latter is the ask-only turn that was stopped after
  // answering a question and before any text (#502), which otherwise loses its
  // stopped indicator, timestamp and cost.
  const hasBody = Boolean(message.content) || (!isUser && (message.parts?.length ?? 0) > 0);
  const sources = !isUser ? extractSources(message, t) : [];
  const hasSources = sources.length > 0 && !message.isStreaming;
  const onCiteClick = hasSources ? (index: number) => openSources(sources, index) : undefined;

  return (
    <div
      className={cn(
        "group relative flex gap-2 overflow-visible sm:gap-4",
        // Each edge decided once, and never as `py-*` with a `pt-0` over it: two
        // utilities of equal specificity leave which one wins to the order of the
        // generated stylesheet, and a segment reading `py-3 pt-0 pb-0` kept its
        // padding. Longhand both ways, so the class list says what it does.
        //
        // Zero against a segment of the same turn, on both edges. The ordinary
        // gap between messages would read as a pause the run never took - and a
        // turn that ran three commands is three segments, each carrying one step,
        // so three steps of one run sat two message-gaps apart and looked like
        // three separate things the agent did.
        continuesTurn ? "pt-0" : isGrouped ? "pt-2 sm:pt-3" : "pt-3 sm:pt-4",
        endsTurn ? (isGrouped ? "pb-2 sm:pb-3" : "pb-3 sm:pb-4") : "pb-0",
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
            // `items-start`, or a flex row stretches every child to the tallest
            // one: a PDF card beside a photograph rendered at 256 px became a
            // 256 px card with its content at the top and a field of empty border
            // under it.
            return (
              <div className="flex flex-wrap items-start gap-2">
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

        <MessageBody
          message={message}
          isUser={isUser}
          mcpServers={mcpServers}
          openLastStep={openLastStep}
          onCiteClick={onCiteClick}
        />

        {hasSources && !isUser && (
          <div className="mt-1">
            <SourcesButton sources={sources} onClick={() => openSources(sources, null)} />
          </div>
        )}

        {!message.isStreaming && hasBody && endsTurn && (
          <div className={cn("flex items-center gap-2", isUser && "flex-row-reverse")}>
            {message.timestamp && (
              <span className="text-muted-foreground text-[10px]">
                {new Date(message.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            {!isUser && message.wasStopped === true && (
              /* A stopped run leaves whatever had been written when the socket
                 closed, and that reads exactly like a finished answer - so a
                 reader takes a truncated one as everything the agent had to say.
                 Beside the cost, because the two together are the whole account
                 of a turn that produced nothing usable and still spent money. */
              <span className="text-muted-foreground flex items-center gap-1 text-[10px]">
                <OctagonPause className="h-3 w-3" aria-hidden />
                {t("turnWasStopped")}
              </span>
            )}
            {!isUser && footerUsage && <MessageCost usage={footerUsage} />}
            {message.content && (
              <CopyButton
                text={message.content}
                className={cn(
                  "h-6 w-6 rounded-md sm:opacity-0 sm:group-hover:opacity-100",
                  isUser ? "bg-secondary hover:bg-secondary/80" : "bg-muted hover:bg-muted/80",
                )}
              />
            )}
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

/**
 * One turn's content: the "Thinking…" placeholder, then either the ordered
 * part timeline or the legacy thinking / text / tool-call fallback.
 *
 * Extracted from `MessageItem` because it was a ~75-line render IIFE inside an
 * already long component - the same body the hosted page renders through
 * `TurnParts`, which is the reason it is a component rather than a branch.
 */
function MessageBody({
  message,
  isUser,
  mcpServers,
  openLastStep,
  onCiteClick,
}: {
  message: ChatMessage;
  isUser: boolean;
  mcpServers: ReturnType<typeof useMcpToolServers>;
  openLastStep: boolean;
  onCiteClick?: (index: number) => void;
}) {
  const t = useTranslations("chat");
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
        /* Ordered timeline: each part in arrival order, with runs of tool
           calls on one rail. The same component the hosted page renders. */
        <TurnParts
          parts={parts}
          isStreaming={Boolean(message.isStreaming)}
          isUser={isUser}
          mcpServers={mcpServers}
          openLastStep={openLastStep}
          conversationId={message.conversationId}
          onCiteClick={onCiteClick}
        />
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
                    mcpServers={mcpServers}
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
