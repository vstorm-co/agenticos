"use client";

import type { Mentionable } from "@/types/mention";
import { useEffect, useLayoutEffect, useRef, useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import type { ChatMessageFile, ChatPerson } from "@/types";
import type { PublishedModel } from "@/types/agents";
import { useAgents, useChat, useConversationWorkspace, useModelProviders } from "@/hooks";
import type { ChatTesting, SteerDraft } from "@/hooks/use-chat";
import { AgentPicker } from "./agent-picker";
import { ChatControls } from "./chat-controls";
import { ChatEmptyState } from "./chat-empty-state";
import { ChatRoomBar } from "./chat-room-bar";
import { TypingIndicator } from "./typing-indicator";
import { useProjectMentions } from "@/hooks/use-project-mentions";
import type { PageComment } from "./browser-comment";
import { ChatInput, type IncomingFiles } from "./chat-input";
import { ComposerStatus } from "./composer-status";
import { ProjectChip } from "./project-chip";
import { UsageMeter } from "./usage-meter";
import { WorkspaceFiles } from "./workspace-files";
import { FilePreviewDialog } from "./file-preview-dialog";
import type { Browse } from "@/lib/browse";
import { LiveBrowsesProvider } from "./browser-card";
import { ConversationVisualsProvider } from "./visual-panel";
import { BrowserPanel } from "./browser-panel";
import { SourcesPanel } from "./sources-panel";
import { MessageList } from "./message-list";
import { TurnRail } from "./turn-rail";
import { DelegationPanels } from "./delegation-panel";
import { CompactionNotice } from "./compaction-notice";
import { SandboxPreparingNotice } from "./sandbox-preparing-notice";
import { InterruptedNotice } from "./interrupted-notice";
import { ConnectAccountPrompt } from "./connect-account-prompt";
import { ConnectServicesCard } from "./connect-services-card";
import { PendingMessages } from "./pending-messages";
import { PlanStrip } from "./plan-strip";
import { ToolApprovalDialog } from "./tool-approval-dialog";
import { QuestionPrompt } from "@/components/ui";
import type {
  PendingApproval,
  AskUserQuestion,
  AskUserAnswer,
  Compaction,
  ConnectionRequest,
  PersonalServiceGap,
  ConversationCost,
  Decision,
  Delegation,
  TurnUsage,
} from "@/types";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { latestUsage } from "@/lib/message-usage";
import { dockedPlan } from "@/lib/plan-state";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useFilePreviewStore,
  useOrgStore,
} from "@/stores";
import { useInChatScope } from "@/stores/chat-scope-context";
import { cn } from "@/lib/utils";
import { useConversations } from "@/hooks";
import { useSlashCommands } from "@/hooks";
import { useFollowContent } from "@/hooks/use-follow-content";
import { useReaderScrolledUp } from "@/hooks/use-reader-scrolled-up";
import { useFocusAfterCall } from "@/hooks/use-focus-after-call";
import { Beam } from "@/components/ui/beam";
import { useMicrophone } from "@/components/ui/voice-glow";
import {
  useDictation,
  useDictationStatus,
  useOrganizationList,
  usePermissions,
  useVoiceReadiness,
  useVoiceSession,
  type VoiceSession,
} from "@/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { dictate, type DictationSend } from "@/lib/dictation-api";
import { Perm } from "@/types/permissions";
import { BrowserDictationPill, DictationPill } from "./dictation-bar";
import { browserDictationHint, dictationHint, DictationStrip } from "./dictation-strip";
import { useAudioLevel } from "@/hooks/use-audio-level";
import { AGENT_CALLS_ANCHOR, AGENT_DICTATION_ANCHOR } from "@/components/agents/voice-card";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { FloatingPill } from "@/components/voice/floating-pill";
import { MessageItem } from "./message-item";
import { NextSteps, nextStepsOf } from "./next-steps";
import { VoiceCallButton } from "@/components/voice/voice-call-button";
import { voiceFailureHint } from "@/components/voice/voice-call-strip";
import {
  callActive,
  useVoiceCallHint,
  showVoiceApproval,
  VoiceCallBar,
  VoiceCallFeed,
} from "@/components/voice/voice-call-view";
import type { VoiceTransport } from "@/types/voice";

/**
 * The browser's voice processing, on for a recording that is transcribed: echo
 * cancellation, noise suppression and gain control are what a speech model
 * wants. The glow-only capture keeps them off so it sees the voice's real
 * dynamics.
 */
const DICTATION_CONSTRAINTS = {
  constraints: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};
/** The organization's longest dictation when its settings have not loaded. */
const DEFAULT_DICTATION_SECONDS = 300;

/**
 * How many tokens the model that will answer next accepts, or `null`.
 *
 * The denominator of the context gauge, and deliberately not stored with the
 * reading it divides: how much history there is survives a model change, what
 * share of a window that is does not. A history of 500,000 tokens is half of a
 * 1M-context model and 390% of a 128K one, and the second is a request the
 * provider refuses outright — so the figure has to move the moment somebody
 * switches, which it does because this is read from the current selection.
 *
 * The override the picker holds first, then the agent's own published model.
 * `null` where neither can say, and the gauge is then not drawn at all: a share
 * against an assumed window is a guess presented as a measurement, and the guess
 * errs in the direction that lets a run reach the ceiling.
 */
function useContextWindow(modelProfileId: string | null): number | null {
  const { profiles } = useModelProviders();
  const { agents } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);

  if (modelProfileId !== null) {
    return profiles.find((profile) => profile.id === modelProfileId)?.context_length ?? null;
  }
  return agents.find((agent) => agent.id === selectedAgentId)?.context_window_tokens ?? null;
}

/** A prompt to send for the reader, once - the AI Architect widget's bubbles. */
export interface ChatPrompt {
  /** Distinguishes two sends of the same words. */
  id: number;
  text: string;
}

interface ChatContainerProps {
  /** Sent as soon as the socket is up, once per `id` (#2063). */
  prompt?: ChatPrompt | null;
  /** What an empty conversation shows instead of the generic suggestions. */
  emptyState?: (onPick: (prompt: string) => void) => React.ReactNode;
  /** The conversation is with one agent, chosen by the caller: no agent picker. */
  agentFixed?: boolean;
  /** Files to attach to the next message, handed in from outside (#2063). */
  incomingFiles?: IncomingFiles | null;
  /** The Builder's test panel: what answers, and that every turn is a test (#2074). */
  testing?: ChatTesting;
  /** Questions kept to ask again after each change, pinned from the conversation (#2075). */
  pins?: PinnedPrompts;
  /**
   * Hold what is sent until this turns false: the test panel's draft is still
   * saving, and a draft test runs what is stored, not what is on the screen.
   */
  holdSending?: boolean;
}

/** When to read a finished turn's transcript again while its answer is not yet
 *  written: at once, then backing off, about fifteen seconds in all. */
const ANSWER_REREADS_MS = [0, 500, 1000, 2000, 4000, 8000];

/** The test panel's pinned questions, and how one is pinned or taken off. */
export interface PinnedPrompts {
  pinned: readonly string[];
  toggle: (prompt: string) => void;
}

export function ChatContainer({
  prompt = null,
  emptyState,
  agentFixed = false,
  incomingFiles = null,
  testing,
  pins,
  holdSending = false,
}: ChatContainerProps = {}) {
  const {
    currentConversationId,
    currentMessages,
    currentCost,
    isLoading: isConversationLoading,
  } = useConversationStore();
  const { rereadMessages } = useChatStore();
  // The model override the picker holds, mirrored here because the context gauge
  // is a share of *its* window rather than of the agent's default.
  const [modelProfileId, setModelProfileId] = useState<string | null>(null);
  const contextWindow = useContextWindow(modelProfileId);
  const { agents } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const agentModel = agents.find((agent) => agent.id === selectedAgentId)?.published_model ?? null;
  // Deliberately unfiltered, which is what calling this with no arguments
  // means. The sidebar's copy of this list is narrowed by whatever is in its
  // search box, and reading the two facts below off *that* would flip the
  // composer to writable the moment somebody typed a search that excluded the
  // thread they have open.
  const {
    conversations,
    fetchConversations,
    refreshConversations,
    selectConversation,
    rereadConversation,
    hasEarlierMessages,
    isLoadingEarlier,
    loadEarlierMessages,
    markRead,
  } = useConversations();
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

  // Opening a thread addresses the composer to the agent it was had with - in a
  // thread several agents answered, the one that answered last. The selection
  // is global, so without this the next message in a Finance Analyst thread
  // went to whichever agent was last picked somewhere else. Once per thread, so
  // switching agents mid-conversation is not undone. Only this thread's rows are
  // read: the store still holds the previous thread's until the new one loads.
  const lastAnsweredBy = currentMessages.findLast(
    (message) =>
      message.conversation_id === currentConversationId &&
      message.role === "assistant" &&
      Boolean(message.agent_id),
  )?.agent_id;
  const threadAgentId = soleAgentId ?? lastAnsweredBy ?? undefined;
  const selectAgent = useAgentSelectionStore((state) => state.select);
  const addressedRef = useRef<string | null>(null);
  useEffect(() => {
    if (agentFixed || !currentConversationId || !threadAgentId) return;
    if (addressedRef.current === currentConversationId) return;
    addressedRef.current = currentConversationId;
    selectAgent(threadAgentId);
  }, [agentFixed, currentConversationId, threadAgentId, selectAgent]);

  // The open conversation is read: once when it is opened, and again when an
  // answer arrives while it is open and the next listing calls it unread. On
  // opening whether or not it was unread, because a read is also who has seen
  // it - a project chat lists its readers - and a teammate's chat is in nobody's
  // list but its owner's, so it never reads as unread to anyone else.
  const openConversation = conversations.find(
    (conversation) => conversation.id === currentConversationId,
  );
  const meId = useAuthStore((state) => state.user?.id);
  const openIsUnread = openConversation?.unread === true;
  const readOnOpen = useRef<string | null>(null);
  useEffect(() => {
    if (!currentConversationId) return;
    if (!openIsUnread && readOnOpen.current === currentConversationId) return;
    readOnOpen.current = currentConversationId;
    void markRead(currentConversationId);
  }, [currentConversationId, openIsUnread, markRead]);

  const handleConversationCreated = useCallback(() => {
    fetchConversations();
  }, [fetchConversations]);

  // A voice call's turns are saved by the server as it goes (#54), so the
  // transcript is read again, in place, as each lands; a call that started a
  // conversation opens it. Whether this page has a call open is kept apart from
  // which conversation it is in: a call started in a new chat has none until the
  // server names one, and leaving it before then still hangs it up.
  const openCallRef = useRef<{ conversationId: string | null } | null>(null);
  const handleVoiceConversation = useCallback(
    (id: string) => {
      const open = openCallRef.current;
      // The person left the call's conversation before the server named it.
      if (open === null) return;
      open.conversationId = id;
      void selectConversation(id);
      fetchConversations();
    },
    [selectConversation, fetchConversations],
  );
  const handleVoiceTurnSaved = useCallback(() => {
    const id = openCallRef.current?.conversationId ?? null;
    if (id !== null && useConversationStore.getState().currentConversationId === id) {
      void rereadConversation(id);
    }
    void refreshConversations();
  }, [rereadConversation, refreshConversations]);
  const voice = useVoiceSession({
    onTurnSaved: handleVoiceTurnSaved,
    onConversation: handleVoiceConversation,
  });
  const startCall = useCallback(
    (transport: VoiceTransport) => {
      if (selectedAgentId === null) return;
      openCallRef.current = { conversationId: currentConversationId };
      void voice.start({
        kind: "console",
        agentId: selectedAgentId,
        conversationId: currentConversationId,
        transport,
      });
    },
    [selectedAgentId, currentConversationId, voice],
  );
  // A call belongs to its conversation: opening another, or a new chat, hangs
  // it up, and an ended call's summary does not follow anybody elsewhere.
  const { end: endCall, dismiss: dismissCall } = voice;
  // A call that ended has spent minutes, and may have been refused for a key
  // or a setting that has changed since: the next button reads afresh.
  const queryClient = useQueryClient();
  const callPhase = voice.call.phase;
  useEffect(() => {
    if (callPhase === "ended") void queryClient.invalidateQueries({ queryKey: qk.voice.all() });
  }, [callPhase, queryClient]);
  useEffect(() => {
    const open = openCallRef.current;
    if (open === null || open.conversationId === currentConversationId) return;
    openCallRef.current = null;
    endCall();
    dismissCall();
  }, [currentConversationId, endCall, dismissCall]);

  // A listing fetched when the conversation was created cannot say who answered
  // in it, because at that moment nobody had: `agents` is derived from the turns
  // stored in the thread. Nothing else asked again, so the face of the agent you
  // are talking to arrived on the next full page load and not before.
  const handleTurnSaved = useCallback(() => {
    void refreshConversations();
  }, [refreshConversations]);

  // The socket went away mid-answer. The turn is still being written server-side
  // and the transcript is where it lands, so re-read it - once now, and again
  // whenever the reader presses the notice, because the turn finishes when it
  // finishes and there is nothing to be told about it.
  const handleTurnInterrupted = useCallback(() => {
    if (currentConversationId) void rereadConversation(currentConversationId);
  }, [currentConversationId, rereadConversation]);

  const {
    messages,
    present,
    typing,
    notifyTyping,
    isConnected,
    isProcessing,
    isStopping,
    canStopParked,
    compacting,
    compactionImpossible,
    sandboxPreparing,
    interrupted,
    detachedTurnPending,
    leftTurnPending,
    acknowledgeDetachedTurn,
    personalGaps,
    lastUsage,
    delegations,
    browses,
    sendMessage,
    stopGeneration,
    clearMessages,
    queuedMessages,
    cancelQueued,
    sendQueuedNow,
    moveQueued,
    clearQueued,
    steers,
    setModelProfile,
    setApprovalMode,
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
    pendingConnection,
    sendConnectionResponse,
    reportVisual,
  } = useChat({
    conversationId: currentConversationId,
    onConversationCreated: handleConversationCreated,
    onTurnSaved: handleTurnSaved,
    onTurnInterrupted: handleTurnInterrupted,
    testing,
  });

  // The reader pressing the notice's button has gone to look for the answer, so
  // the notice stops saying one is on its way. The re-read is the same one a
  // reconnect does; only the acknowledgement is extra.
  const handleRecheck = useCallback(() => {
    acknowledgeDetachedTurn();
    handleTurnInterrupted();
  }, [acknowledgeDetachedTurn, handleTurnInterrupted]);

  // An answer being written under a session this tab does not hold (#2108): the
  // question was asked, then the tab closed, the app quit or the page reloaded,
  // and the turn goes on on the server. The conversation list says a run is
  // still at work - it is re-read on every run event - and the transcript ends
  // with the question, so say so rather than show a question nobody is answering.
  const runningSince =
    conversations.find((conversation) => conversation.id === currentConversationId)
      ?.running_since ?? null;
  // Not while this tab holds a call: the call is that run, and its last spoken
  // turn is the caller's while the agent thinks - nobody left anything.
  const answeringElsewhere =
    runningSince !== null &&
    !isProcessing &&
    !callActive(voice) &&
    messages.at(-1)?.role === "user";
  // And fetch the answer when that run ends, rather than waiting for a reload:
  // the run's end clears `running_since`, and the transcript is where it landed.
  //
  // Read until it is there, not once. The run's terminal event is published when
  // its row commits, and the session writes the answer after that, so the first
  // read can come back ending in the question - and nothing else would ask again.
  const runningIn = useRef<{ id: string | null; running: boolean }>({ id: null, running: false });
  // The conversation whose run ended without writing an answer.
  const [lostIn, setLostIn] = useState<string | null>(null);
  const answered = messages.at(-1)?.role === "assistant";
  const answeredRef = useRef(answered);
  useEffect(() => {
    answeredRef.current = answered;
  }, [answered]);
  useEffect(() => {
    const was = runningIn.current;
    const running = runningSince !== null;
    runningIn.current = { id: currentConversationId, running };
    if (was.id !== currentConversationId || !was.running || running) return;
    if (currentConversationId === null || answeredRef.current) return;
    const id = currentConversationId;
    let waiting = true;
    void (async () => {
      for (const pause of ANSWER_REREADS_MS) {
        await new Promise((resolve) => setTimeout(resolve, pause));
        if (!waiting) return;
        await selectConversation(id);
        if (useConversationStore.getState().currentMessages.at(-1)?.role === "assistant") return;
      }
      // The run ended and wrote nothing: its process died under it and the
      // stale-run sweep closed it. No answer is coming, so say that instead.
      if (waiting) setLostIn(id);
    })();
    return () => {
      waiting = false;
    };
  }, [runningSince, currentConversationId, selectConversation]);
  // Until something else is asked or answered there: then the transcript no
  // longer ends with the question nobody answered.
  const unanswered = messages.at(-1);
  const lostQuestion =
    lostIn !== null &&
    lostIn === currentConversationId &&
    runningSince === null &&
    !isProcessing &&
    unanswered?.role === "user"
      ? unanswered.content
      : null;
  const askAgain = useCallback(
    (question: string) => {
      setLostIn(null);
      sendMessage(question);
    },
    [sendMessage],
  );

  // What the file panel watches, rather than a timer. Counted from the transcript
  // rather than kept as state: a finished assistant message *is* a finished turn,
  // and a second counter would be a second answer to the same question.
  const turns = messages.filter(
    (message) => message.role === "assistant" && !message.isStreaming,
  ).length;

  // Everything attached to this conversation, deduplicated by id and in the order it
  // arrived. Derived from the messages rather than fetched: they carry their
  // attachments both live and after a reload, so the file panel can list what
  // somebody dragged in without a request for what is already on screen.
  const attachments = useMemo(() => {
    const seen = new Map<string, ChatMessageFile>();
    for (const message of messages) for (const file of message.files ?? []) seen.set(file.id, file);
    return [...seen.values()];
  }, [messages]);

  // Handed to the store as well as to the panel, so the file dialog's carousel
  // pages through the conversation wherever a file was clicked. In an effect
  // rather than during render: writing to a store while rendering is a side
  // effect, and React is entitled to render this twice.
  const setAvailableFiles = useFilePreviewStore((state) => state.setAvailable);
  useEffect(() => {
    setAvailableFiles(attachments);
  }, [attachments, setAvailableFiles]);

  const transcriptRef = useRef<HTMLDivElement>(null);
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
    if (
      currentMessages.length > 0 &&
      currentMessages[0]?.conversation_id === currentConversationId
    ) {
      // Not `clearMessages`: a re-read of this same conversation - a followed
      // turn ending, a teammate's answer landing - must not drop the reply
      // somebody is in the middle of writing. A switch has already cleared it.
      rereadMessages(
        currentMessages.map((msg) => {
          const message = conversationMessageToChatMessage(msg);
          return {
            ...message,
            // The row is what says which agent produced a turn. When it says nothing -
            // every message written before the API recorded it - and the conversation
            // had exactly *one* agent, that agent answered every turn in it, and the
            // transcript can show its face instead of a generic robot. With two the
            // guess would relabel half the thread, so it is not made.
            agentId: message.agentId ?? soleAgentId,
          };
        }),
      );
    }
  }, [currentMessages, currentConversationId, rereadMessages, soleAgentId]);

  // Whether the reader has moved up to read, so the transcript stops following.
  useReaderScrolledUp(scrollContainerRef, userScrolledUpRef);

  // An empty conversation is not followed at all: its welcome reads from the
  // top, and in a narrow window - the Architect's, the test panel - following
  // the foot scrolled the greeting and the face above it out of view. A call is
  // content even before any of its turns is saved: its captions are followed.
  const empty = messages.length === 0 && callPhase === "idle";
  const emptyRef = useRef(empty);
  useEffect(() => {
    emptyRef.current = empty;
    const container = scrollContainerRef.current;
    if (emptyRef.current) {
      container?.scrollTo({ top: 0 });
      return;
    }
  }, [empty]);
  // And on growth the messages do not announce: an answer's last words are
  // revealed over frames after its message has stopped changing.
  const holdFollow = useCallback(() => emptyRef.current || userScrolledUpRef.current, []);
  useFollowContent(scrollContainerRef, transcriptRef, holdFollow);
  // A turn starting here is a thread at work in the list beside it; asked once as
  // it starts, the row shows it at once, and the listing then polls until it ends.
  useEffect(() => {
    if (isProcessing) void refreshConversations();
  }, [isProcessing, refreshConversations]);

  const { commands: slashCommands } = useSlashCommands();

  // A message sent while the draft is still saving goes out once it has landed.
  // A ref, not state: releasing it is a send, not something to render.
  const held = useRef<Parameters<typeof sendMessage> | null>(null);
  const send = useCallback(
    (content: string, fileIds?: string[], files?: ChatMessageFile[], mentions?: Mentionable[]) => {
      // Typing on after a call: its summary has said its piece, and would otherwise
      // sit under the new turn.
      dismissCall();
      if (holdSending) held.current = [content, fileIds, files, mentions];
      else sendMessage(content, fileIds, files, mentions);
    },
    [sendMessage, holdSending, dismissCall],
  );
  useEffect(() => {
    if (held.current === null || holdSending) return;
    const waiting = held.current;
    held.current = null;
    sendMessage(...waiting);
  }, [holdSending, sendMessage]);

  const handleRegenerate = useCallback(
    (assistantMessageId: string) => {
      const idx = messages.findIndex((m) => m.id === assistantMessageId);
      if (idx < 0) return;
      for (let i = idx - 1; i >= 0; i--) {
        const m = messages[i];
        if (m?.role === "user") {
          sendMessage(m.content, m.fileIds, m.files, m.mentions);
          return;
        }
      }
    },
    [messages, sendMessage],
  );

  // A prompt handed in from outside - a bubble the reader clicked in the
  // widget - goes out once the socket can carry it, and only once.
  const sentPromptRef = useRef<number | null>(null);
  useEffect(() => {
    if (prompt === null || !isConnected || holdSending || sentPromptRef.current === prompt.id) {
      return;
    }
    sentPromptRef.current = prompt.id;
    sendMessage(prompt.text);
  }, [prompt, isConnected, holdSending, sendMessage]);

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
      hasEarlierMessages={hasEarlierMessages}
      isLoadingEarlier={isLoadingEarlier}
      loadEarlierMessages={loadEarlierMessages}
      messages={messages}
      present={present}
      typing={typing}
      onTyping={notifyTyping}
      // Not a project's chat: who reads one is the project's to say, so a
      // conversation share would invite nobody - the project's Share does.
      ownsConversation={
        openConversation !== undefined &&
        openConversation.user_id === meId &&
        !openConversation.project_id
      }
      isConnected={isConnected}
      isProcessing={isProcessing}
      compacting={compacting}
      compactionImpossible={compactionImpossible}
      sandboxPreparing={sandboxPreparing}
      interrupted={interrupted}
      detachedTurnPending={detachedTurnPending}
      leftTurnPending={leftTurnPending || answeringElsewhere}
      answerLost={lostQuestion !== null}
      onAskAgain={lostQuestion === null ? undefined : () => askAgain(lostQuestion)}
      onRecheck={handleRecheck}
      personalGaps={personalGaps}
      // The live turn's cost while there is one, and the newest measured answer in
      // the transcript otherwise - which is what makes the strip appear on a
      // conversation somebody has just reopened instead of after their next message.
      lastUsage={lastUsage ?? latestUsage(currentMessages, currentConversationId)}
      contextWindow={contextWindow}
      agentModel={agentModel}
      // Only for the thread that is actually open. The store keeps the transcript
      // it last loaded, so between clicking another conversation and its messages
      // arriving this figure belongs to the one just left - the same reason
      // `latestUsage` is given the id rather than trusting the list.
      conversationCost={currentConversationId === null ? null : currentCost}
      delegations={delegations}
      browses={browses}
      conversationId={currentConversationId}
      turns={turns}
      attachments={attachments}
      isLoadingConversation={
        currentConversationId !== null && isConversationLoading && messages.length === 0
      }
      isArchived={isArchived}
      sendMessage={send}
      steers={steers}
      // Kept here as well as pushed into the hook, because the context gauge is a
      // share of *this* model's window: a switch has to move the figure at once,
      // and one carried over from a 1M-context model reads "50%" for a history
      // that is really at 390% of a 128K one.
      onModelProfileChange={(profileId) => {
        setModelProfile(profileId);
        setModelProfileId(profileId);
      }}
      // Only into the hook: nothing on screen is a share of it, unlike the
      // context gauge the model switch has to move.
      onApprovalModeChange={setApprovalMode}
      onRegenerate={handleRegenerate}
      pins={pins}
      slashContext={slashContext}
      slashCommands={slashCommands}
      queuedMessages={queuedMessages}
      onCancelQueued={cancelQueued}
      onSendQueuedNow={sendQueuedNow}
      onMoveQueued={moveQueued}
      transcriptRef={transcriptRef}
      scrollContainerRef={scrollContainerRef}
      userScrolledUpRef={userScrolledUpRef}
      pendingApproval={pendingApproval}
      onResumeDecisions={sendResumeDecisions}
      pendingQuestions={pendingQuestions}
      onAnswerQuestions={sendAskUserResponses}
      pendingConnection={pendingConnection}
      onConnectionResponse={sendConnectionResponse}
      onStop={stopGeneration}
      isStopping={isStopping}
      canStopParked={canStopParked}
      voice={voice}
      onStartCall={startCall}
      emptyState={emptyState}
      agentFixed={agentFixed}
      testingDraft={testing?.draft ?? false}
      incomingFiles={incomingFiles}
      onVisualReport={reportVisual}
    />
  );
}

interface ChatUIProps {
  hasEarlierMessages: boolean;
  isLoadingEarlier: boolean;
  loadEarlierMessages: () => Promise<void>;
  /** Tell the running turn how one of its drawings rendered. */
  onVisualReport?: (toolCallId: string, errors: string[]) => void;
  /** Replaces the generic empty-conversation suggestions. */
  emptyState?: (onPick: (prompt: string) => void) => React.ReactNode;
  agentFixed: boolean;
  /** The Builder's test panel running the draft, which is what `@` then offers from. */
  testingDraft: boolean;
  incomingFiles: IncomingFiles | null;
  messages: import("@/types").ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
  /** The summary in flight, drawn above the composer. Null when none is. */
  compacting: Compaction | null;
  /** A window with no room for a summary, drawn in its place. Null when there is. */
  compactionImpossible: Compaction | null;
  /** True while the run's sandbox is still being opened. See `SandboxPreparingNotice`. */
  sandboxPreparing?: boolean;
  /** True while a turn whose socket went away is unresolved. See `InterruptedNotice`. */
  interrupted?: boolean;
  /** True while such a turn's answer is still coming and the reader has moved on. */
  detachedTurnPending?: boolean;
  /** True while a turn the reader left running here is still on its way. */
  leftTurnPending?: boolean;
  /** True when the turn ended without an answer - its process died under it. */
  answerLost?: boolean;
  /** Ask the unanswered question again. */
  onAskAgain?: () => void;
  /** Read the transcript again, for the notice above. */
  onRecheck?: () => void;
  /** The agent's personal MCP services this person cannot reach, drawn as a card with the button that connects one. */
  personalGaps: PersonalServiceGap[];
  /** What the last turn cost, drawn under the input. Null until one has run. */
  lastUsage: TurnUsage | null;
  /** What the whole thread has cost, from the server. Null until a transcript loads. */
  conversationCost: ConversationCost | null;
  /** The window the context gauge is a share of, or null when nobody knows it. */
  contextWindow: number | null;
  /** The selected agent's published model, shown as current in the model picker. */
  agentModel: PublishedModel | null;
  /**
   * The turn's delegations, drawn under the transcript.
   *
   * Under it rather than inside the assistant message, and they outlive the turn's
   * `complete` - a background delegation reports after the parent has answered.
   */
  delegations: Delegation[];
  /** The turn's browses, for the live preview panel. See `BrowserPanel`. */
  browses: Browse[];
  /** The conversation the file panel reads, or null before one exists. */
  conversationId: string | null;
  /** Who has the conversation open, the reader included. */
  present: ChatPerson[];
  /** Who else is writing a message in it right now. */
  typing: ChatPerson[];
  /** The reader typed - for the room to hear. */
  onTyping: () => void;
  /** Whether the reader started it, and so may share it. */
  ownsConversation: boolean;
  /**
   * How many turns have finished. Bumped so the file panel re-reads when the
   * files could have changed, rather than polling for a change it can be told
   * about.
   */
  turns: number;
  /** What people attached, for the file panel to list beside the agent's own. */
  attachments: ChatMessageFile[];
  /** True while a saved conversation is being loaded - show a skeleton, not empty state. */
  isLoadingConversation?: boolean;
  /** True for an archived conversation - the composer is closed with a notice. */
  isArchived?: boolean;
  sendMessage: (
    content: string,
    fileIds?: string[],
    files?: import("@/types").ChatMessageFile[],
    mentions?: Mentionable[],
  ) => void;
  onModelProfileChange?: (profileId: string | null) => void;
  onApprovalModeChange?: (mode: import("./chat-controls").ApprovalMode) => void;
  onRegenerate?: (messageId: string) => void;
  pins?: PinnedPrompts;
  slashContext?: import("./slash-commands").SlashCommandContext;
  slashCommands?: import("./slash-commands").SlashCommand[];
  queuedMessages?: import("@/hooks/use-chat").QueuedMessage[];
  onCancelQueued?: (id: string) => void;
  /** Sends one queued message into the running task instead of after it. */
  onSendQueuedNow?: (id: string) => void;
  /** Moves one queued message to another place in the order they are sent. */
  onMoveQueued?: (id: string, to: number) => void;
  /** What a message typed while the agent works does (#2087). */
  steers?: SteerDraft[];
  /** The transcript's content, whose growth the scroller follows. */
  transcriptRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  /** Whether the reader scrolled up, and the scroller should stay where they left it. */
  userScrolledUpRef: React.RefObject<boolean>;
  pendingApproval?: PendingApproval | null;
  onResumeDecisions?: (decisions: Decision[]) => void;
  pendingQuestions?: AskUserQuestion[] | null;
  onAnswerQuestions?: (answers: AskUserAnswer[]) => void;
  /** The service a paused run waits for the person to connect. */
  pendingConnection?: ConnectionRequest | null;
  onConnectionResponse?: (connected: boolean) => void;
  onStop?: () => void;
  isStopping?: boolean;
  canStopParked?: boolean;
  /** The voice call this page holds (#54): its bar stands in for the composer while it is on. */
  voice: VoiceSession;
  /** Start a call to the selected agent, in this conversation. */
  onStartCall: (transport: VoiceTransport) => void;
}

function ChatUI({
  hasEarlierMessages,
  isLoadingEarlier,
  loadEarlierMessages,
  messages,
  present,
  typing,
  onTyping,
  ownsConversation,
  isConnected,
  isProcessing,
  compacting,
  compactionImpossible,
  sandboxPreparing = false,
  interrupted = false,
  detachedTurnPending = false,
  leftTurnPending = false,
  answerLost = false,
  onAskAgain,
  onRecheck,
  personalGaps,
  lastUsage,
  conversationCost,
  contextWindow,
  agentModel,
  delegations,
  browses,
  conversationId,
  turns,
  attachments,
  isLoadingConversation,
  isArchived,
  sendMessage,
  onModelProfileChange,
  onApprovalModeChange,
  onRegenerate,
  pins,
  slashContext,
  slashCommands,
  queuedMessages,
  onCancelQueued,
  onSendQueuedNow,
  onMoveQueued,
  steers = [],
  transcriptRef,
  scrollContainerRef,
  userScrolledUpRef,
  pendingApproval,
  onResumeDecisions,
  pendingQuestions,
  onAnswerQuestions,
  pendingConnection,
  onConnectionResponse,
  onStop,
  isStopping = false,
  canStopParked = false,
  voice,
  onStartCall,
  emptyState,
  agentFixed,
  testingDraft,
  incomingFiles,
  onVisualReport,
}: ChatUIProps) {
  const t = useTranslations("chat");
  const tDictation = useTranslations("chat.dictation");
  // The organization sets the longest recording.
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const activeOrg = orgs?.find((org) => org.id === activeOrgId) ?? null;
  const maxSeconds = activeOrg?.dictation_max_seconds ?? DEFAULT_DICTATION_SECONDS;
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  // The engine and the format are the agent's: its Dictation switch sends the
  // recording to a provider when one resolves, and the backend says what to
  // record for it - WAV, unless the deployment accepts compressed audio and
  // that provider takes WebM. The browser's own recognition until it answers.
  const { status } = useDictationStatus(selectedAgentId);
  const engine = status?.engine ?? "browser";
  // Opened by the composer's microphone button; the glow around the box reads
  // its level. With the browser engine it is a second capture (see
  // `VoiceGlow`); with the server engine it is the one being recorded.
  const mic = useMicrophone(engine === "server" ? DICTATION_CONSTRAINTS : undefined);
  const sendDictation = useMemo<DictationSend | null>(
    () =>
      selectedAgentId === null
        ? null
        : (recording, seconds, signal, onProgress) =>
            dictate(selectedAgentId, recording, seconds, signal, onProgress),
    [selectedAgentId],
  );
  const { state: dictationState, actions: dictationActions } = useDictation({
    mic,
    send: sendDictation,
    maxSeconds,
    format: status?.format ?? "wav",
  });
  // The agent left `server` mid-dictation: the composer draws the
  // browser's microphone now, and a recording with no Stop button would run on
  // to the limit unseen, so it goes.
  const dictationPhase = dictationState.phase;
  const cancelDictation = dictationActions.cancel;
  useEffect(() => {
    if (engine !== "server" && dictationPhase !== "idle") cancelDictation();
  }, [engine, dictationPhase, cancelDictation]);
  const { can } = usePermissions();
  const voiceSettingsHref =
    activeOrgId !== null && can(Perm.orgSettings)
      ? `${ROUTES.ORG_MEMBERS(activeOrgId)}#org-voice`
      : null;
  // The agent's own override is the other way to set it up, for whoever may
  // edit agents - the Voice card sits on the agent's Build tab.
  const agentVoiceHref =
    selectedAgentId !== null && can(Perm.agentsEdit)
      ? `${ROUTES.AGENT_DETAIL(selectedAgentId)}#${AGENT_DICTATION_ANCHOR}`
      : null;
  const agentCallsHref =
    selectedAgentId !== null && can(Perm.agentsEdit)
      ? `${ROUTES.AGENT_DETAIL(selectedAgentId)}#${AGENT_CALLS_ANCHOR}`
      : null;
  const hasAgent = selectedAgentId !== null;
  const dictationStrip =
    engine === "server"
      ? dictationHint(
          {
            state: dictationState,
            actions: dictationActions,
            maxSeconds,
            voiceSettingsHref,
            agentVoiceHref,
            // `ChatInput` says "Inserted N words" in its status region.
            insertAnnounced: true,
          },
          tDictation,
        )
      : null;
  const recordingPhase =
    dictationState.phase === "recording" || dictationState.phase === "transcribing";
  // The pill above the composer while a recording is made and transcribed.
  const serverDictating =
    engine === "server" && (dictationState.phase === "requesting" || recordingPhase);
  // The browser's recognition, while it listens: how to stop it, from the composer.
  const [stopBrowserDictation, setStopBrowserDictation] = useState<(() => void) | null>(null);
  const onListeningChange = useCallback(
    (stop: (() => void) | null) => setStopBrowserDictation(() => stop),
    [],
  );
  const browserLevel = useAudioLevel(stopBrowserDictation ? mic.stream : null);
  const [composerFocused, setComposerFocused] = useState(false);
  // The latest answer's next steps sit on the composer until somebody types
  // their own (#2301).
  const [drafting, setDrafting] = useState(false);
  const nextSteps = drafting ? [] : nextStepsOf(messages, isProcessing);
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  // Offered by `@` only while the chat can still choose its project, as the `+` is.
  const projectMentions = useProjectMentions(!agentFixed && conversationId === null);
  // What the composer is handed from outside it: the caller's files, or a
  // comment pointed at the browser's page. The newer wins, and a caller's new
  // files replace a comment the way a comment replaces them.
  const [incoming, setIncoming] = useState(incomingFiles);
  const [handedIn, setHandedIn] = useState(incomingFiles);
  if (handedIn !== incomingFiles) {
    setHandedIn(incomingFiles);
    setIncoming(incomingFiles);
  }
  const commentOnPage = useCallback(
    ({ file, text }: PageComment) => setIncoming({ id: Date.now(), files: [file], text }),
    [],
  );
  // The Architect's window and the Builder's test panel: a narrow column beside
  // a page, with no room for the rail and no use for the full chat's spacing.
  const compact = useInChatScope();

  // A voice call (#54): offered in Send's place when the selected agent can take
  // one, crossed out with the reason when it cannot - in the narrow windows too.
  // The test panel runs the draft while a call runs what is published, so there
  // the button says so.
  const tVoice = useTranslations("chat.voice");
  const offerCall = hasAgent;
  const { readiness, failed: readinessFailed } = useVoiceReadiness(
    offerCall ? selectedAgentId : null,
  );
  const onCall = callActive(voice);
  const startCall = () => {
    if (dictationState.phase !== "idle") cancelDictation();
    onStartCall(readiness?.transport ?? voice.call.transport ?? "webrtc");
  };
  const voiceHint = voiceFailureHint(
    { call: voice.call, onRetry: startCall, onDismiss: voice.dismiss },
    tVoice,
  );
  const callHint = useVoiceCallHint({
    session: voice,
    canDecide: can(Perm.approvalsDecide),
    onShowApproval: showVoiceApproval,
    active: onCall,
  });
  // Browser recognition works for every agent; while it listens for one whose
  // Dictation switch is off, the strip says so and where to turn it on.
  const browserStrip =
    stopBrowserDictation !== null && status?.requested === false
      ? browserDictationHint(agentVoiceHref, tDictation)
      : null;
  const composerStrip = voiceHint ?? callHint ?? dictationStrip ?? browserStrip;
  // Focus went into the call bar when the call started. When the call is over
  // it goes to the box after "continue in text", and otherwise back to the call
  // button - but only if it was lost with the bar, never taken from where the
  // person has since put it.
  const callButtonRef = useRef<HTMLSpanElement>(null);
  const continueInText = useRef(false);
  useFocusAfterCall(onCall, (lost) => {
    if (continueInText.current) {
      dockRef.current?.querySelector<HTMLElement>('[role="textbox"]')?.focus();
    } else if (lost) callButtonRef.current?.querySelector("button")?.focus();
    continueInText.current = false;
  });
  const endForText = () => {
    continueInText.current = true;
    voice.end();
  };

  // The rail's ticks, built from the transcript already on screen rather than
  // from a query of its own: one list, drawn twice.
  const { agents: knownAgents } = useAgents({ includeArchived: true });
  // The agent this thread is addressed to, which is the one handing work out.
  const delegatingAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { user: authUser } = useAuthStore();
  const callAgent = knownAgents.find((agent) => agent.id === selectedAgentId);
  // A spoken turn's time until its saved message brings its own. Captions
  // arrive only once the call is live, which is when it has a start.
  const callStartedAt = useMemo(() => new Date(voice.call.startedAt ?? 0), [voice.call.startedAt]);
  // The turns the transcript already holds, so a call's live caption is not drawn beside its saved message.
  const savedTurns = useMemo(
    () => new Set(messages.flatMap((message) => (message.turnId ? [message.turnId] : []))),
    [messages],
  );
  const agentNames = useMemo(
    () =>
      new Map(
        knownAgents.map(
          (agent) =>
            [
              agent.id,
              // The slug travels with the name because the face is drawn from it.
              // Without it the rail's card fell back to an empty seed, so every
              // agent wore the same generated face there - and a different one
              // from the avatar beside its own answer in the transcript.
              { name: agent.name, slug: agent.slug, hasAvatar: agent.has_avatar },
            ] as const,
        ),
      ),
    [knownAgents],
  );
  const railEntries = useMemo(
    () =>
      messages.map((message) => ({
        id: message.id,
        author:
          message.role === "user"
            ? message.sender && message.sender.user_id !== authUser?.id
              ? message.sender.name
              : message.senderGone
                ? t("rail.formerMember")
                : t("rail.you")
            : ((message.agentId ? agentNames.get(message.agentId)?.name : undefined) ??
              t("rail.agent")),
        preview: (message.content ?? "").trim(),
        isUser: message.role === "user",
        agentId: message.role === "user" ? undefined : (message.agentId ?? undefined),
        agentSlug:
          message.role === "user" ? undefined : agentNames.get(message.agentId ?? "")?.slug,
        hasAvatar: message.agentId ? agentNames.get(message.agentId)?.hasAvatar : false,
        // A person's face is drawn from their id, an agent's from its own; the
        // rail never has to know which, it just hands over the seed.
        seed:
          message.role === "user"
            ? (message.sender?.user_id ?? authUser?.id ?? message.id)
            : (message.agentId ?? message.id),
      })),
    [messages, agentNames, authUser, t],
  );
  // The same query the file panel beside the transcript makes, so the fill under the
  // input costs nothing extra - and appears when a conversation is *opened* rather than
  // after the next turn reports one.
  const { workspace } = useConversationWorkspace(conversationId);
  // The composer floats over the transcript, which means the scroll area must
  // end where the dock begins or the last message hides behind it. The dock's height is not a constant - attachments,
  // banners and a growing textarea all change it - so it is measured.
  // A callback ref rather than `useRef`, because the portal has to re-render once
  // the node exists: a ref object mutating tells React nothing.
  // The agent's own checklist, folded out of the planning calls the transcript
  // already carries - nothing streams a plan frame. Memoized because the fold walks
  // every message and this component re-renders on every streaming delta.
  const plan = useMemo(() => dockedPlan(messages), [messages]);
  const [attachmentSlot, setAttachmentSlot] = useState<HTMLDivElement | null>(null);
  // Where the files button sits: among the composer's own controls, rather than
  // in a strip of its own down the conversation's right edge.
  const [filesSlot, setFilesSlot] = useState<HTMLSpanElement | null>(null);
  const dockRef = useRef<HTMLDivElement | null>(null);
  const [dockHeight, setDockHeight] = useState(0);
  useLayoutEffect(() => {
    const dock = dockRef.current;
    if (!dock) return;
    const observer = new ResizeObserver(() => setDockHeight(dock.offsetHeight));
    observer.observe(dock);
    setDockHeight(dock.offsetHeight);
    return () => observer.disconnect();
  }, []);
  // A taller dock is more padding under the last message, and padding is not
  // content, so nothing follows it: when the call bar gave way to the composer
  // at the end of a call, the last message was left under the composer. A reader
  // at the bottom stays there; one who scrolled up is left where they are.
  useLayoutEffect(() => {
    const scroller = scrollContainerRef.current;
    const empty = messages.length === 0 && voice.call.phase === "idle";
    if (scroller === null || userScrolledUpRef.current || empty) return;
    scroller.scrollTop = scroller.scrollHeight;
  }, [dockHeight, scrollContainerRef, userScrolledUpRef, messages.length, voice.call.phase]);
  const callReady = offerCall && readiness?.available === true;
  const callShown = offerCall && (readiness !== null || readinessFailed);
  // Hidden, not unmounted, during a call: the pill holds its controls, and focus
  // comes back here when it ends.
  const callButton = (
    <span ref={callButtonRef} className={onCall ? "hidden" : "contents"}>
      <VoiceCallButton
        readiness={readiness}
        failed={readinessFailed}
        disabled={isProcessing || isArchived}
        onStart={startCall}
        setUpHref={agentCallsHref}
        prominent={callReady}
        publishedOnly={testingDraft}
      />
    </span>
  );
  return (
    <div className="relative flex h-full w-full">
      {/* The column no longer carries the width. The scroller does, and the
          content is centred inside it - so the scrollbar sits at the edge of the
          pane where a scrollbar belongs, rather than a hundred pixels to the
          right of the text with white on both sides of it. */}
      {/* `@container/chat`: the turn rail sits in the column's left margin, so it
          shows only while the column is wide enough to have one beside the
          centred transcript - not at a window width, which says nothing about
          a column narrowed by the sidebar and the conversation list. */}
      <div className="@container/chat relative flex h-full min-w-0 flex-1 flex-col">
        {!compact && <TurnRail entries={railEntries} />}
        <div
          ref={scrollContainerRef}
          className="flex-1 scrollbar-thin overflow-y-auto"
          style={{
            paddingBottom: dockHeight,
            // In the page the transcript fades out as it reaches the glass
            // composer, so nothing sharp is ever behind it: a backdrop blur is
            // drawn by the GPU and is not always drawn - a screen capture, a
            // throttled tab - and without it the words under the box read
            // through it, crisp, beside the placeholder.
            ...(compact
              ? {}
              : {
                  maskImage: `linear-gradient(to bottom, #000 calc(100% - ${dockHeight + 8}px), transparent calc(100% - ${Math.max(dockHeight - 32, 0)}px))`,
                }),
          }}
        >
          <div
            ref={transcriptRef}
            className={cn(
              compact ? "px-3 py-3 text-sm" : "mx-auto max-w-5xl px-2 py-4 sm:px-4 sm:py-6",
            )}
          >
            {/* Who else has this chat open, held at the top while the transcript scrolls:
                a project's chat is several people's at once. */}
            {conversationId && !compact && (
              <ChatRoomBar
                conversationId={conversationId}
                present={present}
                meId={authUser?.id}
                canShare={ownsConversation}
                className="sticky top-2 z-20 mb-3"
              />
            )}
            {isLoadingConversation ? (
              <ConversationSkeleton />
            ) : messages.length === 0 && voice.call.phase === "idle" ? (
              <div className="flex h-full items-center">
                {emptyState ? (
                  emptyState((picked) => sendMessage(picked))
                ) : (
                  <ChatEmptyState onPick={(picked) => sendMessage(picked)} />
                )}
              </div>
            ) : (
              <LiveBrowsesProvider value={{ browses, onComment: commentOnPage }}>
                <ConversationVisualsProvider
                  messages={messages}
                  conversationId={conversationId}
                  onReport={onVisualReport}
                  onCompose={(text) => setIncoming({ id: Date.now(), files: [], text })}
                  onSend={isArchived ? undefined : (text) => sendMessage(text)}
                >
                  {hasEarlierMessages && (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground mx-auto block px-4 py-2 text-sm"
                      disabled={isLoadingEarlier}
                      onClick={() => void loadEarlierMessages()}
                    >
                      {t("loadEarlierMessages")}
                    </button>
                  )}
                  <MessageList messages={messages} onRegenerate={onRegenerate} pins={pins} />
                </ConversationVisualsProvider>
              </LiveBrowsesProvider>
            )}
            {/* After the transcript, not inside it: a delegation is a second agent's
                conversation happening inside one turn of this one, and it can still be
                streaming when the turn it belongs to has already answered. */}
            <DelegationPanels
              delegations={delegations}
              agents={knownAgents}
              parent={knownAgents.find((agent) => agent.id === delegatingAgentId)}
              settled={!isProcessing}
              conversation={isProcessing}
            />
            {/* The call, as it happens: live captions inside the turns being
                spoken, the approval card, and the summary when it ends. */}
            <VoiceCallFeed
              session={voice}
              agentName={callAgent?.name ?? t("rail.agent")}
              agent={callAgent}
              canDecide={can(Perm.approvalsDecide)}
              hidden={savedTurns}
              onCallAgain={startCall}
              onContinueInText={endForText}
              // As the message it becomes once saved, so the saved one takes its
              // place without the turn moving, restyling or changing colour.
              renderTurn={(turn) => (
                <MessageItem
                  message={{
                    id: `voice-${turn.turnId}`,
                    role: turn.role === "user" ? "user" : "assistant",
                    content: turn.text,
                    timestamp: callStartedAt,
                    turnId: turn.turnId,
                    agentId: turn.role === "user" ? undefined : callAgent?.id,
                    isStreaming: turn.role !== "user" && turn.live,
                  }}
                  agent={turn.role === "user" ? undefined : callAgent}
                  agents={knownAgents}
                />
              )}
              // The agent's message, thinking - where its spoken answer will be.
              renderThinking={() => (
                <MessageItem
                  message={{
                    id: "voice-thinking",
                    role: "assistant",
                    content: "",
                    timestamp: callStartedAt,
                    agentId: callAgent?.id,
                    isStreaming: true,
                  }}
                  agent={callAgent}
                  agents={knownAgents}
                />
              )}
            />
          </div>
        </div>
        {/* The floating dock: banners, the composer, the caption. Over the
            transcript, not under it. `pointer-events-none` on the wrapper so
            the transparent gutters beside the column do not swallow clicks and
            the scrollbar's bottom stays draggable; each child takes its own
            pointer-events back. */}
        {/* z-20: a message avatar carries z-10 of its own, and without a higher
            index here it rides over the composer instead of passing behind
            it - which, now that the composer is opaque, is the difference
            between a message sliding under the dock and one drawn on top of
            it. */}
        {/* Opaque under the composer: the transcript would otherwise show through
            the gutter under the box, behind the disclaimer, as a line of text cut
            in half. The whole dock in the narrow column; in the page, the
            column the composer sits in, so the gutters beside it stay clear. */}
        <div
          ref={dockRef}
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 z-20",
            compact && "bg-background",
          )}
        >
          {personalGaps.length > 0 && (
            <div className="pointer-events-auto mx-auto w-full max-w-5xl px-2 pb-2 sm:px-4 sm:pb-2">
              <ConnectServicesCard gaps={personalGaps} />
            </div>
          )}
          {pendingApproval && onResumeDecisions && (
            <div className="pointer-events-auto mx-auto w-full max-w-5xl px-2 pb-2 sm:px-4 sm:pb-2">
              <ToolApprovalDialog
                actionRequests={pendingApproval.actionRequests}
                reviewConfigs={pendingApproval.reviewConfigs}
                onDecisions={onResumeDecisions}
                disabled={!isConnected || isStopping}
              />
            </div>
          )}
          {pendingConnection && onConnectionResponse && (
            <div className="pointer-events-auto mx-auto w-full max-w-5xl px-2 pb-2 sm:px-4 sm:pb-2">
              <ConnectAccountPrompt
                request={pendingConnection}
                disabled={!isConnected || isStopping}
                onRespond={onConnectionResponse}
              />
            </div>
          )}
          {pendingQuestions && pendingQuestions.length > 0 && onAnswerQuestions && (
            <div className="pointer-events-auto mx-auto w-full max-w-5xl px-2 pb-2 sm:px-4 sm:pb-2">
              <QuestionPrompt
                questions={pendingQuestions}
                disabled={!isConnected || isStopping}
                onComplete={onAnswerQuestions}
              />
            </div>
          )}
          <div
            className={cn(
              "pointer-events-auto mx-auto w-full",
              // Glass in the page: the answer scrolls on behind the composer,
              // blurred, and the strip fades to the page by the caption under it
              // so no line of text is ever cut in half behind the words.
              compact
                ? "px-3 pt-1 pb-1.5"
                : "max-w-5xl bg-[linear-gradient(to_bottom,transparent_30%,var(--color-background)_62%)] px-2 pb-2 sm:px-4 sm:pb-4",
            )}
          >
            <InterruptedNotice
              interrupted={interrupted}
              detached={detachedTurnPending}
              left={leftTurnPending}
              lost={answerLost}
              onRecheck={onRecheck}
              onAskAgain={onAskAgain}
            />
            <CompactionNotice compacting={compacting} impossible={compactionImpossible} />
            {sandboxPreparing && <SandboxPreparingNotice />}
            {onCancelQueued && (
              <PendingMessages
                messages={queuedMessages ?? []}
                steers={steers}
                onCancel={onCancelQueued}
                onSendNow={isProcessing && isConnected ? onSendQueuedNow : undefined}
                onMove={onMoveQueued}
              />
            )}
            {/* The checklist the agent is working to. Here rather than in the
                transcript because a plan is written in one turn and worked through
                over the next several: as a step it scrolls away under the work it
                describes, and what somebody wants is where the agent is now. */}
            <PlanStrip plan={plan} live={isProcessing} />
            {/* Right over the box the reply is written in, where a messenger says it. */}
            <TypingIndicator people={typing} />
            {/* What is attached, above the composer rather than inside it. The
                slot is here because the box below is drawn here; `ChatInput`
                portals its row into it and keeps the upload state. */}
            <div ref={setAttachmentSlot} />
            {/* `@container`, so the composer and the line under it change shape
                on their own width rather than on the window's. They are not the
                same question: at 900px with the conversation list open this box
                is 360px wide, and a viewport breakpoint showed a reading there
                that had nowhere to go. */}
            <div className="@container">
              {/* While a call is on, the composer does not change: the call is one
                  pill floating above it, so the chat stays the chat and a draft
                  and its attachments are still there when the call ends. */}
              <div className="relative">
                <FloatingPill
                  pill={
                    onCall
                      ? {
                          key: "call",
                          node: (
                            <VoiceCallBar
                              pill
                              session={voice}
                              agentName={callAgent?.name ?? t("rail.agent")}
                              avatar={
                                callAgent ? (
                                  <AgentAvatar
                                    agentId={callAgent.id}
                                    slug={callAgent.slug}
                                    hasAvatar={callAgent.has_avatar}
                                    colorSlot={callAgent.avatar_color}
                                    size="sm"
                                    className="rounded-full"
                                  />
                                ) : undefined
                              }
                              canDecide={can(Perm.approvalsDecide)}
                              onShowApproval={showVoiceApproval}
                            />
                          ),
                        }
                      : serverDictating
                        ? {
                            key: "dictation",
                            node: (
                              <DictationPill state={dictationState} actions={dictationActions} />
                            ),
                          }
                        : stopBrowserDictation
                          ? {
                              key: "browser",
                              node: (
                                <BrowserDictationPill
                                  level={browserLevel}
                                  onDone={stopBrowserDictation}
                                />
                              ),
                            }
                          : null
                  }
                />
                {/* No glow under the box: the pill above it says the microphone is
                    open and how loud, and a second signal below read as a shadow. */}
                <div>
                  {/* All the way around the composer, and only while somebody is in
                  it. A border that glows permanently is decoration; one that
                  lights when the caret arrives is the box saying it is where
                  the typing goes. The glow outside it answers the microphone
                  and the turn; this is the box's own. */}
                  {/* Every hint on top of the box, beside the pill it belongs to. */}
                  {!isArchived && !onCall && (
                    <NextSteps steps={nextSteps} onPick={(step) => sendMessage(step)} />
                  )}
                  <DictationStrip hint={composerStrip} placement="above" />
                  <Beam
                    size="md"
                    borderRadius={16}
                    active={composerFocused}
                    onFocusChange={setComposerFocused}
                  >
                    <div
                      data-tour="chat-composer"
                      className={cn(
                        "panel composer-box focus-within:border-foreground/30 rounded-2xl transition-colors",
                        !compact && "composer-glass",
                        composerStrip !== null && "rounded-t-none",
                      )}
                    >
                      <div className={cn("px-3 pt-3 pb-1", !compact && "sm:px-4 sm:pt-4")}>
                        {isArchived && (
                          <p className="text-muted-foreground pb-2 text-center font-mono text-xs tracking-wider uppercase">
                            {t("conversationArchived")}
                          </p>
                        )}
                        {/* One row of actions under the text, the same at every
                          level of every limit: attach and who answers on the left;
                          usage, the model, the microphone and send on the right. A
                          limit near its end changes an icon's colour and never
                          costs the row a button. */}
                        <ChatInput
                          onSend={sendMessage}
                          // Mentions address the agent the thread is talking to -
                          // in a fixed window (the test panel, the Architect) the
                          // scope's own selection holds it.
                          agentId={delegatingAgentId}
                          mentionsFromDraft={testingDraft}
                          hints={messages.length === 0}
                          disabled={
                            isStopping ||
                            !isConnected ||
                            isArchived ||
                            onCall ||
                            !!pendingApproval ||
                            !!(pendingQuestions && pendingQuestions.length)
                          }
                          isProcessing={isProcessing}
                          canStop={
                            isStopping ||
                            canStopParked ||
                            isProcessing ||
                            !!pendingApproval ||
                            !!pendingQuestions?.length ||
                            !!pendingConnection
                          }
                          onStop={onStop}
                          stopDisabled={isStopping}
                          slashContext={slashContext}
                          commands={slashCommands}
                          attachmentSlot={attachmentSlot}
                          incoming={incoming}
                          onTyping={onTyping}
                          onDraftChange={setDrafting}
                          offline={!isConnected}
                          projects={projectMentions.items}
                          onPickProject={projectMentions.pick}
                          mic={mic}
                          onListeningChange={onListeningChange}
                          dictation={{
                            engine,
                            state: dictationState,
                            actions: dictationActions,
                          }}
                          // Who answers first and largest: it is the most
                          // consequential choice in the composer.
                          controlsSlot={
                            agentFixed ? undefined : (
                              <>
                                <AgentPicker />
                                <ProjectChip
                                  conversationId={conversationId}
                                  pickerOpen={projectPickerOpen}
                                  onPickerOpenChange={setProjectPickerOpen}
                                />
                              </>
                            )
                          }
                          onProject={
                            agentFixed || conversationId
                              ? undefined
                              : () => setProjectPickerOpen(true)
                          }
                          actionsSlot={
                            <>
                              {/* Wide screens only, as is the panel it opens. */}
                              <span ref={setFilesSlot} className="hidden lg:contents" />
                              <UsageMeter
                                usage={lastUsage}
                                workspace={workspace}
                                total={conversationCost}
                                contextWindow={contextWindow}
                              />
                              <div data-tour="chat-model-picker">
                                <ChatControls
                                  onModelProfileChange={onModelProfileChange}
                                  onApprovalModeChange={onApprovalModeChange}
                                  agentModel={agentModel}
                                />
                              </div>
                              {/* The call stands in Send's place, as one that can
                                  start or one that says why it cannot - except
                                  during the call, when it waits here, hidden, for
                                  focus to come back to. */}
                              {onCall && callButton}
                            </>
                          }
                          // Not during a call: the box is closed then, Send with it.
                          // Nor while readiness loads, when the button draws
                          // nothing and the slot would leave no Send at all.
                          idleSlot={callShown && !onCall ? callButton : undefined}
                        />
                      </div>
                    </div>
                  </Beam>
                </div>
              </div>
              <ComposerStatus isConnected={isConnected} />
            </div>
          </div>
        </div>
      </div>
      <FilePreviewDialog />
      <SourcesPanel contained={compact} />
      {/* A browse opened full screen from under its message. Draws nothing
          until somebody does, so a conversation with no browsing costs nothing. */}
      <BrowserPanel browses={browses} onComment={commentOnPage} />
      {/* Beside the transcript rather than under it: what the agent is holding is
          something you glance at while reading, and a list that pushed the input
          down would move the box you are typing in. Closed by default - it is a
          button among the composer's controls until somebody opens it, because a
          permanent third column took space from every conversation including the
          ones where the agent keeps nothing. Hidden on a narrow screen, where there
          is no room for it. */}
      <div className="hidden lg:block">
        <WorkspaceFiles
          conversationId={conversationId}
          revision={turns}
          attachments={attachments}
          buttonSlot={filesSlot}
          overlay={compact}
        />
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
