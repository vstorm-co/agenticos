"use client";

import { memo } from "react";

import { MentionChip } from "./mention-chip";
import { stillMentioned } from "@/lib/mentions";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ThinkingOrb } from "@/components/ui/thinking-orb";
import { cn } from "@/lib/utils";
import type { ChatMessage, ChatMessageFile, TurnUsage } from "@/types";
import type { Agent } from "@/types/agents";
import { ToolCallCard } from "./tool-call-card";
import { AgentSteps } from "./agent-step";
import { foldWork, runsOf, TextBubble, ThinkingBlock, TurnParts } from "./turn-parts";
import type { PinnedPrompts } from "./chat-container";
import { CopyButton } from "./copy-button";
import { MessageSources } from "./message-sources";
import { TurnDelegations } from "./turn-delegations";
import { RoundedCost } from "./message-cost";
import { PersonFace } from "./person-face";
import { ReplyQuote, replyExcerpt } from "./reply-quote";
import { YouFace } from "./you-face";
import { TURN_ACTION } from "./turn-action";
import { SkillShortcut } from "./skill-shortcut";
import { TurnShortcuts } from "./turn-shortcuts";
import { RatingButtons } from "./rating-buttons";
import { useChatStore, useFilePreviewStore } from "@/stores";
import { useMcpToolServers } from "@/hooks";
import { useInChatScope } from "@/stores/chat-scope-context";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import {
  Bot,
  CornerUpLeft,
  FileText,
  Mic,
  OctagonPause,
  Paperclip,
  Pause,
  Pin,
  PinOff,
  RefreshCw,
  UserRound,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useAuthStore } from "@/stores";
import { getFileUrl } from "@/lib/file-api";
import { isRenderSafeImage } from "@/lib/file-kinds";
import { FileCard } from "@/components/files";
import { extractSources, toolCallsOf } from "@/lib/chat-sources";
import type { DelegateRef } from "@/lib/delegations";
import { publishedApps, PublishedArtifactResult } from "./tool-results/artifact";
import { TurnExtras } from "./turn-extras";

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
  /** In the test panel: a question can be pinned to ask again after each change (#2075). */
  pins?: PinnedPrompts;
  /** The agents the reader can see, which name the one a delegation asked. */
  agents?: readonly DelegateRef[];
  /** What the person asked for, on the answer that ends the turn: a skill can be made of it. */
  request?: string;
}

export const MessageItem = memo(function MessageItem({
  message,
  agent,
  groupPosition,
  continuesTurn = false,
  endsTurn = true,
  turnUsage,
  openLastStep = false,
  onRegenerate,
  pins,
  agents = [],
  request,
}: MessageItemProps) {
  const t = useTranslations("chat");
  const tInput = useTranslations("chat.input");
  const isUser = message.role === "user";
  // A mention sits in the text it was typed into; only one the text does not
  // carry - a turn sent before that was so - is shown as a chip beside it.
  const unplaced = (message.mentions ?? []).filter(
    (item) => stillMentioned(message.content, [item]).length === 0,
  );
  const updateMessage = useChatStore((state) => state.updateMessage);
  const setReplyTo = useChatStore((state) => state.setReplyTo);
  const tReply = useTranslations("chat.reply");
  const openPreview = useFilePreviewStore((s) => s.open);
  const openSources = useSourcesPanelStore((s) => s.open);
  const { user: authUser } = useAuthStore();
  // A teammate's words in a project's chat: theirs, not the reader's "You".
  const teammate =
    isUser && message.sender && message.sender.user_id !== authUser?.id ? message.sender : null;
  // Somebody who has since left: never drawn as the reader.
  const former = isUser && message.senderGone === true;
  // Read once per turn and handed to each step, so a public surface can render the
  // same step without a session - see `TurnParts`.
  const mcpServers = useMcpToolServers();
  const isGrouped = groupPosition && groupPosition !== "single";
  // The Architect's window and the Builder's test panel: a narrow column beside
  // the page, where the full chat's spacing spent most of the width on air.
  const compact = useInChatScope();

  // The turn's cost, which a grouped turn recorded on the segment that parked
  // rather than on the one the footer is drawn under.
  const footerUsage = turnUsage ?? message.usage;
  // A stopped turn with work folds it into "Stopped after 12s", which says it; the
  // footer's own marker is for a turn cut off with nothing to fold.
  const stopFolded =
    message.wasStopped === true && foldWork(runsOf(message.parts ?? []), true) !== null;
  // A turn produced something worth a footer if it wrote content *or* left a
  // timeline part - the latter is the ask-only turn that was stopped after
  // answering a question and before any text (#502), which otherwise loses its
  // stopped indicator, timestamp and cost.
  const hasBody = Boolean(message.content) || (!isUser && (message.parts?.length ?? 0) > 0);
  const sources = !isUser ? extractSources(message, t) : [];
  const hasSources = sources.length > 0 && !message.isStreaming;
  const apps = !isUser ? publishedApps(toolCallsOf(message)) : [];
  const onCiteClick = hasSources ? (index: number) => openSources(sources, index) : undefined;

  const avatar = (
    <div
      className={cn(
        "z-10 flex flex-shrink-0 items-center justify-center overflow-hidden rounded-full",
        compact ? "h-6 w-6" : "h-7 w-7",
        // A fill only behind the fallback icon. A face or a picture brings its
        // own disc, and a dark one behind it showed as a thin ring wherever the
        // two edges did not quite meet.
        isUser && !authUser && "bg-foreground text-background",
        !isUser && !agent && "bg-muted text-foreground",
      )}
    >
      {teammate ? (
        <PersonFace person={teammate} className="h-full w-full text-[10px]" />
      ) : former ? (
        <span className="bg-muted text-muted-foreground grid h-full w-full place-items-center">
          <UserRound className="h-3.5 w-3.5" aria-hidden />
        </span>
      ) : isUser ? (
        <YouFace />
      ) : agent ? (
        <AgentAvatar
          agentId={agent.id}
          slug={agent.slug}
          hasAvatar={agent.has_avatar}
          colorSlot={agent.avatar_color}
          size="md"
          thinking={Boolean(message.isStreaming)}
          className="h-full w-full border-0"
        />
      ) : (
        <Bot className="h-4 w-4 sm:h-5 sm:w-5" />
      )}
    </div>
  );

  return (
    <div
      // The anchor the turn rail scrolls to. On the row rather than on a wrapper
      // of its own, so the rail lands on the top of the turn and not on a box
      // drawn around it.
      data-message-id={message.id}
      className={cn(
        // The face and the name on one line over the message, as in the
        // Architect's window, and the message under them at the column's full
        // width: a column of avatars beside every turn spent a gutter on a face
        // that only needs saying once per turn.
        "group relative flex flex-col overflow-visible",
        compact ? "gap-1.5" : "gap-2",
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
        //
        // 12px a side between messages, not 16: under every message sits its row of
        // time and actions, 36px that is empty until hovered, so 32px on top of it
        // left a 68px hole between a question and its answer (#2302).
        continuesTurn ? "pt-0" : compact || isGrouped ? "pt-2" : "pt-3",
        endsTurn ? (compact || isGrouped ? "pb-2" : "pb-3") : "pb-0",
        isUser && "items-end",
      )}
    >
      {/* Which agent answered, on the turn it answered: a conversation that
          switched agents mid-way says so, instead of relabelling the whole thread
          with whatever is selected now. The version, where the transcript
          recorded one, because this turn was answered by one frozen spec. */}
      {!continuesTurn && (
        <div className={cn("flex items-center gap-2", isUser && "flex-row-reverse")}>
          {avatar}
          <span
            className={cn(
              "truncate font-medium",
              compact ? "text-muted-foreground text-xs" : "text-foreground text-sm",
            )}
          >
            {teammate
              ? teammate.name
              : former
                ? t("rail.formerMember")
                : isUser
                  ? t("rail.you")
                  : (agent?.name ?? t("rail.agent"))}
            {!isUser && message.agentVersion !== undefined && (
              <span className="text-muted-foreground font-normal"> · v{message.agentVersion}</span>
            )}
          </span>
        </div>
      )}
      <div
        className={cn(
          "overflow-hidden",
          compact ? "space-y-1.5" : "space-y-2",
          isUser ? "flex max-w-[85%] flex-col items-end" : "w-full",
        )}
      >
        {isUser && unplaced.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {unplaced.map((item) => (
              <MentionChip key={`${item.kind}:${item.id}`} item={item} />
            ))}
          </div>
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
              // `justify-end`: a person's files sit flush right with their
              // message, also on the second row a wrap starts.
              <div className="flex flex-wrap items-start justify-end gap-2">
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
                    // The chip the composer showed before it was sent: a name, a
                    // type, and a click that opens it. The tile with a preview band
                    // stacked eight pastes into a wall of empty pages above the
                    // question they came with.
                    <FileCard
                      key={att.file.id}
                      name={att.file.filename}
                      mimeType={att.file.mime_type}
                      typeLabel={PASTED.test(att.file.filename) ? tInput("pastedLabel") : undefined}
                      compact
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

        {message.replyTo && (
          <ReplyQuote reply={message.replyTo} agents={agents} align={isUser ? "end" : "start"} />
        )}
        <MessageBody
          message={message}
          isUser={isUser}
          mcpServers={mcpServers}
          agents={agents}
          openLastStep={openLastStep}
          endsTurn={endsTurn}
          onCiteClick={onCiteClick}
        />

        {!isUser && !message.isStreaming && apps.length > 0 && (
          // What the turn made, under what it said: the app is the answer to
          // "build me a dashboard", and it used to be one line inside the folded
          // work above the reply.
          <div className="mt-1 max-w-xl space-y-2">
            {apps.map((app) => (
              <PublishedArtifactResult key={app.artifactId} data={app} />
            ))}
          </div>
        )}

        {!isUser && !message.isStreaming && endsTurn && (
          <TurnDelegations toolCalls={toolCallsOf(message)} parent={agent} agents={agents} />
        )}

        {hasSources && !isUser && (
          <div className="mt-1">
            <MessageSources sources={sources} onOpen={(index) => openSources(sources, index)} />
          </div>
        )}

        {/* Under what the turn said and above its time and actions: a card the
            answer introduces belongs with the answer, not after its receipt. */}
        <TurnExtras message={message} agentName={agent?.name} />

        {!message.isStreaming && hasBody && endsTurn && (
          // The time and the cost surface on hover with the actions beside them:
          // a column of receipts under every turn is noise while reading, and the
          // numbers are one pointer move away when somebody wants them.
          <div className={cn("flex items-center gap-0.5", isUser && "flex-row-reverse")}>
            {!isUser && message.wasStopped === true && !stopFolded && (
              /* A stopped run leaves whatever had been written when the socket
                 closed, and that reads exactly like a finished answer - so a
                 reader takes a truncated one as everything the agent had to say.
                 First in the row, where it is read before the time and the cost;
                 a turn whose work folded says it in that line instead. */
              <span className="text-muted-foreground flex items-center gap-1 text-xs">
                <OctagonPause className="h-3 w-3" aria-hidden />
                {t("turnWasStopped")}
              </span>
            )}
            {/* A turn spoken in a call (#54), and one the caller talked over -
                whose text is cut to roughly what was heard. */}
            {message.turnId !== undefined && (
              <span className="text-muted-foreground flex items-center gap-1 text-[11px]">
                <Mic className="h-3 w-3" aria-hidden />
                {t("voice.view.voice")}
              </span>
            )}
            {message.interrupted && (
              <span
                title={t("voice.view.interruptedTitle")}
                className="text-foreground flex items-center gap-1 text-[11px] font-medium"
              >
                <Pause className="text-warning h-3 w-3" aria-hidden />
                {t("voice.view.interrupted")}
              </span>
            )}
            {/* When and what it cost, as one quiet group before the actions. */}
            {message.timestamp && (
              <span
                className={cn(
                  "hover-reveal text-muted-foreground flex items-center gap-1.5 text-xs tabular-nums",
                  isUser ? "pl-1.5" : "pr-1.5",
                )}
              >
                {new Date(message.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {!isUser && footerUsage && (
                  <>
                    <span aria-hidden>·</span>
                    <RoundedCost usage={footerUsage} />
                  </>
                )}
              </span>
            )}
            {message.content && (
              <CopyButton
                text={message.content}
                className={cn(TURN_ACTION, "p-0 sm:opacity-0 sm:group-hover:opacity-100")}
              />
            )}
            {isUser && pins && message.content && (
              <PinButton pins={pins} prompt={message.content} />
            )}
            {/* What was asked, kept: on a schedule, or as an agent of its own (#2301). */}
            {isUser && !pins && !message.isTemporaryId && message.content && (
              <TurnShortcuts request={message.content} agentId={agent?.id ?? null} />
            )}
            {/* Stored messages only: a reply names the row it answers, and a
                message still on this tab's own id has none yet. */}
            {!message.isTemporaryId && !message.isStreaming && message.content && (
              <button
                type="button"
                onClick={() =>
                  setReplyTo({
                    messageId: message.id,
                    role: message.role,
                    excerpt: replyExcerpt(message.content),
                    sender: isUser ? message.sender : undefined,
                    agentId: isUser ? undefined : agent?.id,
                    agentName: isUser ? undefined : agent?.name,
                  })
                }
                title={tReply("reply")}
                aria-label={tReply("reply")}
                className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
              >
                <CornerUpLeft />
              </button>
            )}
            {!isUser && request && !message.isStreaming && message.content && (
              <SkillShortcut
                request={request}
                answer={message.content}
                conversationId={message.conversationId}
              />
            )}
            {!isUser && onRegenerate && (
              <button
                type="button"
                onClick={onRegenerate}
                title={t("regenerate")}
                aria-label={t("regenerate")}
                className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
              >
                <RefreshCw />
              </button>
            )}
            {/* A rating is stored against the saved message; a turn that failed
                before the server saved it has only a client id, which the
                rating endpoint answers with "Message not found". */}
            {!isUser && !message.isTemporaryId && (
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
});

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
  agents,
  openLastStep,
  endsTurn,
  onCiteClick,
}: {
  message: ChatMessage;
  isUser: boolean;
  mcpServers: ReturnType<typeof useMcpToolServers>;
  agents: readonly DelegateRef[];
  openLastStep: boolean;
  /** The run's span is said once, under the turn's last segment. */
  endsTurn: boolean;
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
      {/* The stretch between asking and the first token, which is the one moment
          in a turn with nothing else on screen to look at. A capsule rather than
          a mark beside loose text: it is one object saying one thing, and it
          holds its shape while the word inside it changes. */}
      {showPlaceholder && (
        <div className="py-1" role="status" aria-live="polite">
          <span className="bg-foreground/[0.04] inline-flex items-center gap-1.5 rounded-full py-1 pr-3.5 pl-1.5">
            <ThinkingOrb state="breathing" size={20} className="h-7 w-7" />
            <span className="text-muted-foreground text-xs">{t("thinking")}</span>
          </span>
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
          agents={agents}
          openLastStep={openLastStep}
          conversationId={message.conversationId}
          onCiteClick={onCiteClick}
          startedAt={message.timestamp}
          durationMs={endsTurn ? message.runDurationMs : undefined}
          stopped={message.wasStopped === true}
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
              mentions={isUser ? message.mentions : undefined}
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
                    agents={agents}
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

/** The name the composer gives a long paste it turned into a file. */
const PASTED = /^pasted-\d{4}-\d{2}-\d{2}\.txt$/;

type AttachmentDisplay =
  | { kind: "image"; file: ChatMessageFile }
  | { kind: "file"; file: ChatMessageFile }
  | { kind: "unknown"; id: string };

function kindFor(file: ChatMessageFile): "image" | "file" {
  // A thumbnail only for a type the browser can draw inline. A TIFF has
  // `file_type: "image"` and `mime_type: "image/tiff"` but neither draws inline, so
  // it takes a file card, not a broken thumbnail whose src is the download URL
  // (#1591).
  if (isRenderSafeImage(file.mime_type)) return "image";
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
      <Paperclip className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
    </a>
  );
}

/** Pin a question to ask again after each change, or take it off (#2075). */
function PinButton({ pins, prompt }: { pins: PinnedPrompts; prompt: string }) {
  const t = useTranslations("chat");
  const pinned = pins.pinned.includes(prompt);
  const label = pinned ? t("unpinQuestion") : t("pinQuestion");
  return (
    <button
      type="button"
      onClick={() => pins.toggle(prompt)}
      title={label}
      aria-label={label}
      aria-pressed={pinned}
      className={cn(
        TURN_ACTION,
        pinned ? "text-foreground" : "sm:opacity-0 sm:group-hover:opacity-100",
      )}
    >
      {pinned ? <PinOff /> : <Pin />}
    </button>
  );
}
