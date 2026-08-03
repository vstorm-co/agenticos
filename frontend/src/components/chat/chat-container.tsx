"use client";

import { useEffect, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useChat } from "@/hooks";
import { AgentPicker } from "./agent-picker";
import { ChatControls } from "./chat-controls";
import { ChatEmptyState } from "./chat-empty-state";
import { ChatInput } from "./chat-input";
import { UsageStrip } from "./usage-strip";
import { WorkspaceFiles } from "./workspace-files";
import { FilePreviewPanel } from "./file-preview-panel";
import { SourcesPanel } from "./sources-panel";
import { MessageList } from "./message-list";
import { PendingMessages } from "./pending-messages";
import { ToolApprovalDialog } from "./tool-approval-dialog";
import { QuestionPrompt } from "@/components/ui";
import type { PendingApproval, AskUserQuestion, AskUserAnswer, Decision, TurnUsage } from "@/types";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { latestUsage } from "@/lib/message-usage";
import { useConversationStore, useChatStore } from "@/stores";
import { useConversations } from "@/hooks";
import { useSlashCommands } from "@/hooks";

const SCROLL_NEAR_BOTTOM_THRESHOLD_PX = 150;

export function ChatContainer() {
  const {
    currentConversationId,
    currentMessages,
    isLoading: isConversationLoading,
  } = useConversationStore();
  const { addMessage: addChatMessage } = useChatStore();
  const { conversations, fetchConversations } = useConversations();
  const prevConversationIdRef = useRef<string | null | undefined>(undefined);

  // An archived conversation is read-only: the backend refuses new messages on
  // it, so the composer says so instead of letting a send fail server-side.
  const isArchived =
    conversations.find((conversation) => conversation.id === currentConversationId)?.is_archived ??
    false;

  // The one agent a conversation used, when it used exactly one. Recovered from the
  // conversation rather than the message, which is the only source history has left.
  const conversationAgents = conversations.find(
    (conversation) => conversation.id === currentConversationId,
  )?.agents;
  const soleAgentId = conversationAgents?.length === 1 ? conversationAgents[0]?.id : undefined;

  const handleConversationCreated = useCallback(() => {
    fetchConversations();
  }, [fetchConversations]);

  const {
    messages,
    isConnected,
    isProcessing,
    lastUsage,
    sendMessage,
    stopGeneration,
    clearMessages,
    queuedMessages,
    cancelQueued,
    clearQueued,
    setModelProfile,
    setTemperature,
    setThinkingEffort,
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
  } = useChat({
    conversationId: currentConversationId,
    onConversationCreated: handleConversationCreated,
  });

  // What the file panel watches, rather than a timer. Counted from the transcript
  // rather than kept as state: a finished assistant message *is* a finished turn,
  // and a second counter would be a second answer to the same question.
  const turns = messages.filter(
    (message) => message.role === "assistant" && !message.isStreaming,
  ).length;

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // true = user deliberately scrolled up; suppress auto-scroll until they return to bottom
  const userScrolledUpRef = useRef(false);

  // Clear messages when conversation changes, but NOT when going from null to a new ID
  // (that happens when a new chat is saved - we want to keep the messages)
  useEffect(() => {
    const prevId = prevConversationIdRef.current;
    const currId = currentConversationId;

    // Skip initial mount
    if (prevId === undefined) {
      prevConversationIdRef.current = currId;
      return;
    }

    // Clear messages when:
    // 1. Going from a conversation to null (new chat)
    // 2. Switching between two different conversations
    // Do NOT clear when going from null to a conversation (new chat being saved)
    const shouldClear =
      currId === null || // Going to new chat
      (prevId !== null && prevId !== currId); // Switching between conversations

    if (shouldClear) {
      clearMessages();
      // Drop any pending queue when switching threads - those messages were
      // typed in the previous conversation's context, sending them into a
      // different conversation would surprise the user.
      clearQueued();
    }

    prevConversationIdRef.current = currId;
  }, [currentConversationId, clearMessages, clearQueued]);

  useEffect(() => {
    if (currentMessages.length > 0) {
      clearMessages();
      currentMessages.forEach((msg) => {
        const message = conversationMessageToChatMessage(msg);
        addChatMessage({
          ...message,
          // The row is what says which agent produced a turn. When it says nothing -
          // every message written before the API recorded it - and the conversation
          // had exactly *one* agent, that agent answered every turn in it, and the
          // transcript can show its face instead of a generic robot. With two the
          // guess would relabel half the thread, so it is not made.
          agentId: message.agentId ?? soleAgentId,
        });
      });
    }
  }, [currentMessages, addChatMessage, clearMessages]);

  // Track whether the user has manually scrolled up so we don't hijack their position
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const handleScroll = () => {
      const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      userScrolledUpRef.current = distFromBottom > SCROLL_NEAR_BOTTOM_THRESHOLD_PX;
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll on every messages update unless user has scrolled up
  useEffect(() => {
    if (userScrolledUpRef.current) return;
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  const { commands: slashCommands } = useSlashCommands();

  const handleRegenerate = useCallback(
    (assistantMessageId: string) => {
      const idx = messages.findIndex((m) => m.id === assistantMessageId);
      if (idx < 0) return;
      for (let i = idx - 1; i >= 0; i--) {
        const m = messages[i];
        if (m?.role === "user") {
          sendMessage(m.content, m.fileIds, m.files);
          return;
        }
      }
    },
    [messages, sendMessage],
  );

  // Slash command handlers - passed down to ChatInput so the / palette can
  // run them locally without going through the agent.
  const slashContext = {
    clearChat: clearMessages,
    regenerateLast: () => {
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m && m.role === "assistant") {
          handleRegenerate(m.id);
          return;
        }
      }
    },
    openSettings: () => {
      document.querySelector<HTMLButtonElement>("[data-chat-settings-trigger]")?.click();
    },
  };

  return (
    <ChatUI
      messages={messages}
      isConnected={isConnected}
      isProcessing={isProcessing}
      // The live turn's cost while there is one, and the newest measured answer in
      // the transcript otherwise - which is what makes the strip appear on a
      // conversation somebody has just reopened instead of after their next message.
      lastUsage={lastUsage ?? latestUsage(currentMessages)}
      conversationId={currentConversationId}
      turns={turns}
      isLoadingConversation={
        currentConversationId !== null && isConversationLoading && messages.length === 0
      }
      isArchived={isArchived}
      sendMessage={sendMessage}
      onModelProfileChange={setModelProfile}
      onTemperatureChange={setTemperature}
      onThinkingEffortChange={setThinkingEffort}
      onRegenerate={handleRegenerate}
      slashContext={slashContext}
      slashCommands={slashCommands}
      queuedMessages={queuedMessages}
      onCancelQueued={cancelQueued}
      messagesEndRef={messagesEndRef}
      scrollContainerRef={scrollContainerRef}
      pendingApproval={pendingApproval}
      onResumeDecisions={sendResumeDecisions}
      pendingQuestions={pendingQuestions}
      onAnswerQuestions={sendAskUserResponses}
      onStop={stopGeneration}
    />
  );
}

interface ChatUIProps {
  messages: import("@/types").ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
  /** What the last turn cost, drawn under the input. Null until one has run. */
  lastUsage: TurnUsage | null;
  /** The conversation the file panel reads, or null before one exists. */
  conversationId: string | null;
  /**
   * How many turns have finished. Bumped so the file panel re-reads when the
   * files could have changed, rather than polling for a change it can be told
   * about.
   */
  turns: number;
  /** True while a saved conversation is being loaded - show a skeleton, not empty state. */
  isLoadingConversation?: boolean;
  /** True for an archived conversation - the composer is closed with a notice. */
  isArchived?: boolean;
  sendMessage: (
    content: string,
    fileIds?: string[],
    files?: import("@/types").ChatMessageFile[],
  ) => void;
  onModelProfileChange?: (profileId: string | null) => void;
  onTemperatureChange?: (temperature: number | null) => void;
  onThinkingEffortChange?: (effort: "low" | "medium" | "high" | null) => void;
  onRegenerate?: (messageId: string) => void;
  slashContext?: import("./slash-commands").SlashCommandContext;
  slashCommands?: import("./slash-commands").SlashCommand[];
  queuedMessages?: import("@/hooks/use-chat").QueuedMessage[];
  onCancelQueued?: (id: string) => void;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  pendingApproval?: PendingApproval | null;
  onResumeDecisions?: (decisions: Decision[]) => void;
  pendingQuestions?: AskUserQuestion[] | null;
  onAnswerQuestions?: (answers: AskUserAnswer[]) => void;
  onStop?: () => void;
}

function ChatUI({
  messages,
  isConnected,
  isProcessing,
  lastUsage,
  conversationId,
  turns,
  isLoadingConversation,
  isArchived,
  sendMessage,
  onModelProfileChange,
  onTemperatureChange,
  onThinkingEffortChange,
  onRegenerate,
  slashContext,
  slashCommands,
  queuedMessages,
  onCancelQueued,
  messagesEndRef,
  scrollContainerRef,
  pendingApproval,
  onResumeDecisions,
  pendingQuestions,
  onAnswerQuestions,
  onStop,
}: ChatUIProps) {
  const tc = useTranslations("common");
  return (
    <div className="flex h-full w-full">
      <div className="mx-auto flex h-full max-w-5xl min-w-0 flex-1 flex-col">
        <div
          ref={scrollContainerRef}
          className="flex-1 scrollbar-thin overflow-y-auto px-2 py-4 sm:px-4 sm:py-6"
        >
          {isLoadingConversation ? (
            <ConversationSkeleton />
          ) : messages.length === 0 ? (
            <div className="flex h-full items-center">
              <ChatEmptyState onPick={(prompt) => sendMessage(prompt)} />
            </div>
          ) : (
            <MessageList messages={messages} onRegenerate={onRegenerate} />
          )}
          <div ref={messagesEndRef} />
        </div>{" "}
        {pendingApproval && onResumeDecisions && (
          <div className="px-2 pb-2 sm:px-4 sm:pb-2">
            <ToolApprovalDialog
              actionRequests={pendingApproval.actionRequests}
              reviewConfigs={pendingApproval.reviewConfigs}
              onDecisions={onResumeDecisions}
              disabled={!isConnected}
            />
          </div>
        )}
        {pendingQuestions && pendingQuestions.length > 0 && onAnswerQuestions && (
          <div className="px-2 pb-2 sm:px-4 sm:pb-2">
            <QuestionPrompt
              questions={pendingQuestions}
              disabled={!isConnected}
              onComplete={onAnswerQuestions}
            />
          </div>
        )}
        <div className="px-2 pb-2 sm:px-4 sm:pb-4">
          {queuedMessages && queuedMessages.length > 0 && onCancelQueued && (
            <PendingMessages messages={queuedMessages} onCancel={onCancelQueued} />
          )}
          <div className="bg-card border-border focus-within:border-foreground/30 rounded-2xl border transition-colors">
            <div className="px-3 pt-3 sm:px-4 sm:pt-4">
              {isArchived && (
                <p className="text-muted-foreground pb-2 text-center font-mono text-[11px] tracking-wider uppercase">
                  This conversation is archived
                </p>
              )}
              {/* Under the input rather than over the transcript: it is about
                  the turn that just finished, and a strip above the messages
                  would move the conversation every time a number changed. */}
              <UsageStrip usage={lastUsage} />
              <ChatInput
                onSend={sendMessage}
                disabled={
                  !isConnected ||
                  isArchived ||
                  !!pendingApproval ||
                  !!(pendingQuestions && pendingQuestions.length)
                }
                isProcessing={isProcessing}
                onStop={onStop}
                slashContext={slashContext}
                commands={slashCommands}
              />
            </div>
            <div className="border-foreground/8 flex items-center justify-between border-t px-3 py-2 sm:px-4">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase ${isConnected ? "text-muted-foreground" : "text-destructive"}`}
                >
                  <span
                    className={`inline-block h-1.5 w-1.5 rounded-full ${
                      isConnected ? "bg-success" : "bg-destructive"
                    }`}
                  />
                  {isConnected ? tc("live") : tc("offline")}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {/* Who answers, first and largest: it is the most consequential
                    choice in the composer and it was a tab inside a popover. */}
                <AgentPicker />
                <ChatControls
                  onModelProfileChange={onModelProfileChange}
                  onTemperatureChange={onTemperatureChange}
                  onThinkingEffortChange={onThinkingEffortChange}
                />
              </div>
            </div>
          </div>
          <p className="text-foreground/40 mt-2 text-center font-mono text-[10px] tracking-wider uppercase">
            AI can make mistakes. Verify important information.
          </p>
        </div>
      </div>
      <FilePreviewPanel />
      <SourcesPanel />
      {/* Beside the transcript rather than under it: what the agent is holding is
          something you glance at while reading, and a list that pushed the input
          down would move the box you are typing in. Closed by default - it is a
          button in the corner until somebody opens it, because a permanent third
          column took space from every conversation including the ones where the
          agent keeps nothing, so closed it is a strip holding one icon. Hidden on a
          narrow screen, where there is no room for either, and absent entirely for
          an agent with no workspace. */}
      <div className="hidden lg:block">
        <WorkspaceFiles conversationId={conversationId} revision={turns} />
      </div>
    </div>
  );
}

function ConversationSkeleton() {
  // Two faux message bubbles - left (assistant) and right (user) - at the rough
  // proportions a real exchange has, so the layout doesn't pop when messages
  // arrive. Just enough motion to signal "loading", no shimmer chrome.
  return (
    <div className="space-y-6 py-4 sm:py-6">
      <div className="flex gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />
        <div className="flex max-w-[85%] flex-1 flex-col gap-2">
          <div className="bg-foreground/10 h-4 w-1/3 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-4/5 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-2/3 animate-pulse rounded-md" />
        </div>
      </div>
      <div className="flex flex-row-reverse gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />
        <div className="flex max-w-[85%] flex-1 flex-col items-end gap-2">
          <div className="bg-foreground/10 h-4 w-1/4 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-3/5 animate-pulse rounded-md" />
        </div>
      </div>
      <div className="flex gap-2 sm:gap-4">
        <div className="bg-foreground/10 h-8 w-8 shrink-0 animate-pulse rounded-full sm:h-9 sm:w-9" />
        <div className="flex max-w-[85%] flex-1 flex-col gap-2">
          <div className="bg-foreground/8 h-4 w-3/4 animate-pulse rounded-md" />
          <div className="bg-foreground/8 h-4 w-1/2 animate-pulse rounded-md" />
        </div>
      </div>
    </div>
  );
}
