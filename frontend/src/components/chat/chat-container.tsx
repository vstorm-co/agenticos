"use client";

import { useWorkingStore } from "@/stores/working-store";

import { onRemoteChange } from "@/lib/live-updates";
import type { Mentionable } from "@/types/mention";
import { useChatSendModePreference } from "@/stores/chat-send-mode-store";
import { useMessageJump, type MessageJumpState } from "@/hooks/use-message-jump";
import { MessageJumpNotice } from "./message-jump-notice";
import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useCallback,
  useMemo,
  useState,
} from "react";
import { Bot, Gauge, PhoneCall, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ChatMessageFile, ChatPerson, Conversation } from "@/types";
import type { PublishedModel } from "@/types/agents";
import type { ParkedSecretRequest } from "@/types/runs";
import {
  useAgents,
  useChat,
  useConversationWorkspace,
  useModelProviders,
  useWorkflowChat,
  useWorkflows,
} from "@/hooks";
import type { ChatTesting, SteerDraft } from "@/hooks/use-chat";
import type { AssistantPageContext } from "@/lib/assistant-page-context";
import { AgentPicker, isChattable } from "./agent-picker";
import { ChatApprovalSelector } from "./chat-approval-selector";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { ChatControls } from "./chat-controls";
import { PersonalModelConnection } from "./personal-model-connection";
import { ChatModelHeader } from "./chat-model-header";
import { ChatCompactionControl, ChatCompactionNotice } from "./chat-compaction-control";
import { SheetRow } from "./composer-sheet";
import { ChatEmptyState } from "./chat-empty-state";
import { ChatRoomBar } from "./chat-room-bar";
import { TeamRoomHeader, TeamRoomEmpty } from "./team-room-header";
import { RoomRoutingPanel } from "./room-routing-panel";
import { TeamRoomComposer } from "./team-room-composer";
import { RoomThreadPanel } from "./room-thread-panel";
import { useRoomRequests, useRoomSync } from "@/hooks/use-room";
import { TypingIndicator } from "./typing-indicator";
import { useProjectMentions } from "@/hooks/use-project-mentions";
import type { PageComment } from "./browser-comment";
import { ChatInput, type IncomingFiles } from "./chat-input";
import { ComposerStatus } from "./composer-status";
import { OutcomeCards } from "./outcome-cards";
import { ProjectChip } from "./project-chip";
import { UsageMeter } from "./usage-meter";
import { FilePreviewDialog } from "./file-preview-dialog";
import type { Browse, BrowserProtection } from "@/lib/browse";
import { LiveBrowsesProvider } from "./browser-card";
import { ConversationVisualsProvider } from "./visual-panel";
import { WorkspacePanels } from "./workspace-panels";
import { browseSurfaces } from "@/lib/workspace-panels";
import { SourcesPanel } from "./sources-panel";
import { MessageList, coalesceActivity, type MessagePinActions } from "./message-list";
import { PinnedMessages, type PinnedMessageTarget } from "./pinned-messages";
import { TurnRail } from "./turn-rail";
import { DelegationPanels } from "./delegation-panel";
import { LocalAccessDialog } from "./local-access-dialog";
import { useComputerAccessOnUse, useLocalAccessGate } from "@/hooks/use-local-access-gate";
import { CompactionNotice } from "./compaction-notice";
import { ForkedFrom } from "./forked-from";
import { type ConversationSideThreadActions } from "./conversation-side-threads";
import { PersonalSideThreadPanel } from "./personal-side-thread-panel";
import { ConversationAccessNotice } from "./conversation-access-notice";
import { useConversationAccess, useSharedConversation } from "@/hooks/use-conversation-shares";
import { SandboxPreparingNotice } from "./sandbox-preparing-notice";
import { InterruptedNotice } from "./interrupted-notice";
import { ConnectAccountPrompt } from "./connect-account-prompt";
import { ConnectServicesCard } from "./connect-services-card";
import { PendingMessages } from "./pending-messages";
import { PlanStrip } from "./plan-strip";
import { BackgroundTasks } from "./background-tasks";
import { ToolApprovalDialog } from "./tool-approval-dialog";
import { QuestionPrompt } from "@/components/ui";
import { SecretRequestCard } from "./secret-request-card";
import type {
  PendingApproval,
  AskUserQuestion,
  AskUserAnswer,
  Compaction,
  ChatCompactionStatus,
  ConnectionRequest,
  PersonalServiceGap,
  ConversationCost,
  ConversationForkOrigin,
  Decision,
  Delegation,
  TurnUsage,
} from "@/types";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { latestUsage } from "@/lib/message-usage";
import {
  createConversationSideThread,
  type ConversationForkRead,
} from "@/lib/conversation-forks-api";
import { dockedPlan } from "@/lib/plan-state";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useFilePreviewStore,
  useOrgStore,
} from "@/stores";
import { useLiveCallStore } from "@/stores/live-call-store";
import { useInChatScope } from "@/stores/chat-scope-context";
import { useComposerIntentStore } from "@/stores/composer-intent-store";
import { cn } from "@/lib/utils";
import { useConversations } from "@/hooks";
import { useTenantId } from "@/hooks/use-organizations";
import { useMessagePins } from "@/hooks/use-message-pins";
import type { ConversationMessageSearchTarget } from "@/lib/conversation-message-search-api";
import { useMounted } from "@/hooks/use-mounted";
import { useOnline } from "@/hooks/use-online";
import { offlineAvailable } from "@/lib/offline/device-cache";
import { useSlashCommands } from "@/hooks";
import { useFollowContent } from "@/hooks/use-follow-content";
import { useSentTurnAnchor } from "@/hooks/use-sent-turn-anchor";
import { useReaderScrolledUp } from "@/hooks/use-reader-scrolled-up";
import { useFocusAfterCall } from "@/hooks/use-focus-after-call";
import { useAgentDictation } from "@/hooks/use-agent-dictation";
import { usePermissions, useVoiceReadiness, useVoiceSession, type VoiceSession } from "@/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
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
  /** Optional page reference for the floating assistant; captured on submission. */
  pageContext?: () => AssistantPageContext | null;
  /** The selected agent is unavailable; keep the composer visibly disabled. */
  sendDisabled?: boolean;
  /** Keep the welcome screen out of a saved conversation's initial load. */
  requestedConversationId?: string | null;
  requestedThreadRootId?: string | null;
  requestedMessageId?: string | null;
  messageJumpRevision?: number;
  onOpenParent?: (target: { conversationId: string; messageId: string | null }) => void;
  onOpenMessage?: (target: ConversationMessageSearchTarget) => void;
  onOpenThread?: (rootId: string) => void;
  onCloseThread?: () => void;
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
  requestedConversationId = null,
  requestedThreadRootId = null,
  requestedMessageId = null,
  messageJumpRevision = 0,
  onOpenParent,
  onOpenMessage,
  onOpenThread,
  onCloseThread,
  prompt = null,
  emptyState,
  agentFixed = false,
  incomingFiles = null,
  testing,
  pins,
  holdSending = false,
  pageContext,
  sendDisabled = false,
}: ChatContainerProps = {}) {
  // What another app shared with the phone app (#2097): held here once the
  // store hands it over, so leaving the chat and coming back does not attach
  // it twice. A caller's own files win.
  const shared = useComposerIntentStore((state) => state.shared);
  const clearShared = useComposerIntentStore((state) => state.clearShared);
  const [sharedHere, setSharedHere] = useState<IncomingFiles | null>(null);
  if (shared !== null && shared !== sharedHere) setSharedHere(shared);
  useEffect(() => {
    if (shared !== null) clearShared();
  }, [shared, clearShared]);
  const {
    currentConversationId,
    createdConversationId,
    pendingProjectId,
    currentMessages,
    loadedTranscript,
    selectionVersion,
    currentCost,
    isLoading: isConversationLoading,
  } = useConversationStore();
  const rereadMessages = useChatStore((state) => state.rereadMessages);
  const committedTranscript = useChatStore((state) => state.loadedTranscript);
  const unresolvedTranscript = loadedTranscript ?? committedTranscript;
  const chatApi = useChatStore.useApi();
  // The model override the picker holds, mirrored here because the context gauge
  // is a share of *its* window rather than of the agent's default.
  const { modelProfileId } = useSavedChatControls();
  const contextWindow = useContextWindow(modelProfileId);
  const { agents, isLoading: agentsLoading } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  const agentModel = selectedAgent?.published_model ?? null;
  const agentCapabilities = selectedAgent?.published_capabilities ?? null;
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
    createConversation,
    rereadConversation,
    hasEarlierMessages,
    isLoadingEarlier,
    loadEarlierMessages,
    error: conversationError,
    markRead,
    forkConversation,
  } = useConversations();
  const prevConversationIdRef = useRef<string | null | undefined>(undefined);

  // Read access for non-owned threads even when channel participation lists them.
  const listed = conversations.find((conversation) => conversation.id === currentConversationId);
  const openConversation = listed;
  const notListed = currentConversationId !== null && listed === undefined;
  const meId = useAuthStore((state) => state.user?.id);
  // Naming the first turn is not opening an unknown thread: the socket has
  // just confirmed creation, before its row reaches the sidebar's query.
  const newlyCreated = notListed && createdConversationId === currentConversationId;
  const tenantId = useTenantId();
  const needsAccess =
    currentConversationId !== null && !newlyCreated && (notListed || listed?.user_id !== meId);
  const access = useConversationAccess(currentConversationId, needsAccess);
  const sharedConversation = useSharedConversation(currentConversationId);
  const isArchived = listed?.is_archived ?? access.archived;
  const viewOnly = access.viewOnly;
  const readOnly = isArchived || viewOnly || !access.known;
  // Somebody else's thread: its project is read-only until the access result says
  // otherwise. Owned threads need no access read, so they are never read-only here.
  const projectReadOnly = needsAccess && (!access.known || access.conversation?.user_id !== meId);
  const scoped = useInChatScope();
  // Project access defines the audience; a floating assistant keeps its own composer.
  const roomProjectId =
    scoped || agentFixed
      ? null
      : currentConversationId === null
        ? pendingProjectId
        : (listed?.project_id ??
          access.conversation?.project_id ??
          sharedConversation?.project_id ??
          null);
  const roomVisibility =
    listed?.room_visibility ??
    access.conversation?.room_visibility ??
    sharedConversation?.room_visibility ??
    null;
  const isRoom = !scoped && !agentFixed && (roomProjectId !== null || roomVisibility != null);
  useRoomSync(isRoom ? currentConversationId : null, rereadConversation);
  const roomRequests = useRoomRequests(isRoom ? currentConversationId : null);
  const canStartThread =
    isRoom &&
    !isArchived &&
    access.known &&
    !roomRequests.isError &&
    roomRequests.data?.can_post === true;
  const threadRootId =
    requestedConversationId === currentConversationId ? requestedThreadRootId : null;

  // The one agent a conversation used, when it used exactly one. Recovered from the
  // conversation rather than the message, which is the only source history has left.
  const conversationAgents = [
    listed?.agents,
    sharedConversation?.agents,
    access.conversation?.agents,
  ].find((agents) => agents !== undefined && agents.length > 0);
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
  const openIsUnread = openConversation?.unread === true || sharedConversation?.unread === true;
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

  // The network back: what is on screen may be the copy kept on the device
  // (#2097), so the open conversation is read again from the server, in place.
  const online = useOnline();
  const wasOnline = useRef(online);
  useEffect(() => {
    const returned = online && !wasOnline.current;
    wasOnline.current = online;
    if (returned && currentConversationId) void rereadConversation(currentConversationId);
  }, [online, currentConversationId, rereadConversation]);

  // A voice call's turns are saved by the server as it goes (#54), so the
  // transcript is read again, in place, as each lands; a call that started a
  // conversation opens it. Whether this page has a call open is kept apart from
  // which conversation it is in: a call started in a new chat has none until the
  // server names one, and leaving it before then still hangs it up.
  const openCallRef = useRef<{ conversationId: string | null; agentId?: string } | null>(null);
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
  // What the phone app draws as a live activity while this page holds a call.
  const setLiveCall = useLiveCallStore((state) => state.set);
  const {
    phase,
    callId,
    runId: callRun,
    startedAt,
    conversationId: callConversation,
    questions,
  } = voice.call;
  useEffect(() => {
    const agentId = openCallRef.current?.agentId ?? null;
    const live = phase === "live" || phase === "reconnecting";
    setLiveCall(
      live && callId !== null && agentId !== null && startedAt !== null
        ? {
            callId,
            runId: callRun,
            agentId,
            conversationId: callConversation,
            startedAt,
            asking: questions !== null,
          }
        : null,
    );
  }, [phase, callId, callRun, startedAt, callConversation, questions, setLiveCall]);
  useEffect(() => () => setLiveCall(null), [setLiveCall]);
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

  useEffect(() => {
    let refresh: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = onRemoteChange((event) => {
      if (!currentConversationId || event.organization_id !== useOrgStore.getState().activeOrgId)
        return;
      const transcript = chatApi.getState().messages;
      const changedThread = event.resource === "conversation" && event.id === currentConversationId;
      const changedRun =
        event.resource === "run" &&
        event.id !== null &&
        transcript.some((message) => message.runId === event.id);
      if (!changedThread && !changedRun) return;
      // The live socket owns its current draft. Worker continuations and parked
      // runs arrive through persisted updates, not that foreground socket.
      if (transcript.some((message) => message.isStreaming)) return;
      clearTimeout(refresh);
      refresh = setTimeout(() => void rereadConversation(currentConversationId), 150);
    });
    return () => {
      unsubscribe();
      clearTimeout(refresh);
    };
  }, [currentConversationId, rereadConversation, chatApi]);

  // The socket went away mid-answer. The turn is still being written server-side
  // and the transcript is where it lands, so re-read it - once now, and again
  // whenever the reader presses the notice, because the turn finishes when it
  // finishes and there is nothing to be told about it.
  const handleTurnInterrupted = useCallback(() => {
    if (currentConversationId) void rereadConversation(currentConversationId);
  }, [currentConversationId, rereadConversation]);

  const {
    messages: rawMessages,
    activeThreadRootId = null,
    actionThreadRoots = {
      approval: null,
      questions: null,
      secrets: null,
      connection: null,
      computer: null,
    },
    present,
    typing,
    notifyTyping,
    isConnected,
    isProcessing,
    isStopping,
    canStopParked,
    compacting,
    compactionImpossible,
    compactionAvailable = false,
    compactionReady = false,
    compactionStatus = "idle",
    compactionProgress = null,
    compactConversation,
    sandboxPreparing,
    interrupted,
    detachedTurnPending,
    leftTurnPending,
    acknowledgeDetachedTurn,
    personalGaps,
    lastUsage,
    delegations,
    browses,
    protectBrowser,
    sendMessage: sendChatMessage,
    sendSteerMessage: sendSteerText,
    captureSubmission,
    stopGeneration,
    clearMessages,
    queuedMessages,
    sentTurnId,
    cancelQueued,
    retryQueued,
    sendQueuedNow,
    moveQueued,
    clearQueued,
    steers,
    setModelProfile,
    setApprovalMode,
    pendingApproval,
    continuingApproval,
    mayRememberApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
    pendingSecretRequests,
    submitSecretRequest,
    declineSecretRequest,
    pendingConnection,
    sendConnectionResponse,
    pendingComputerAccess,
    sendComputerAccessResponse,
    reportVisual,
  } = useChat({
    conversationId: currentConversationId,
    onConversationCreated: handleConversationCreated,
    onTurnSaved: handleTurnSaved,
    onTurnInterrupted: handleTurnInterrupted,
    testing,
    pageContext,
  });
  const startCall = useCallback(
    (transport: VoiceTransport) => {
      if (selectedAgentId === null || compactionStatus === "running") return;
      openCallRef.current = { conversationId: currentConversationId, agentId: selectedAgentId };
      void voice.start({
        kind: "console",
        agentId: selectedAgentId,
        conversationId: currentConversationId,
        transport,
      });
    },
    [selectedAgentId, currentConversationId, voice, compactionStatus],
  );
  // Scope before any rendered-list upsert: a thread delta never flashes in the room.
  const messages = useMemo(
    () => rawMessages.filter((message) => message.threadRootMessageId === undefined),
    [rawMessages],
  );
  // An agent that works on this computer is sent to with the folder this chat or
  // the agent was given; with none, it asks when it needs the files.
  const sendMessage = useLocalAccessGate(sendChatMessage, selectedAgent, {
    selectedAgentId,
    metadataPending: agentsLoading,
    projectId: openConversation?.project_id,
  });
  useComputerAccessOnUse({
    pending:
      readOnly ||
      actionThreadRoots.computer !== threadRootId ||
      (actionThreadRoots.computer !== null && !isRoom)
        ? null
        : pendingComputerAccess,
    respond: sendComputerAccessResponse,
    agent:
      pendingComputerAccess?.agent_id === undefined
        ? selectedAgent
        : agents.find((agent) => agent.id === pendingComputerAccess.agent_id),
  });

  // A message addressed to a workflow goes to it instead of the agent: the
  // picker's choice, read from the same cached list the picker shows.
  const { can } = usePermissions();
  const { workflows } = useWorkflows({ enabled: can(Perm.workflowsRun) });
  const selectedWorkflowId = useAgentSelectionStore((state) => state.selectedWorkflowId);
  const selectedWorkflow =
    workflows.find((workflow) => workflow.id === selectedWorkflowId && isChattable(workflow)) ??
    null;
  const workflowChat = useWorkflowChat({
    createConversation,
    onConversationCreated: handleConversationCreated,
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
  // The same listing row's latest heartbeat for that run: the fold reads it
  // from the working store, beside the start the effect below already records.
  const runningHeartbeatAt =
    conversations.find((conversation) => conversation.id === currentConversationId)
      ?.running_heartbeat_at ?? null;
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
  const hasForegroundTurn = isProcessing || callActive(voice);
  useEffect(() => {
    if (!isProcessing || !runningSince || !currentConversationId) return;
    const working = useWorkingStore.getState();
    const finished = working.finishedAt[currentConversationId];
    if (finished && Date.parse(runningSince) <= Date.parse(finished)) return;
    // Both the sidebar and the transcript measure the same persisted run,
    // including when its stream resumes after a human decision.
    working.start(currentConversationId, runningSince);
    if (runningHeartbeatAt) working.setHeartbeat(currentConversationId, runningHeartbeatAt);
  }, [isProcessing, runningSince, runningHeartbeatAt, currentConversationId]);

  const answeredRef = useRef(answered);
  useEffect(() => {
    answeredRef.current = answered;
  }, [answered]);
  useEffect(() => {
    const was = runningIn.current;
    const running = runningSince !== null;
    runningIn.current = { id: currentConversationId, running };
    if (was.id !== currentConversationId || !was.running || running) return;
    if (currentConversationId === null || answeredRef.current || hasForegroundTurn) return;
    const id = currentConversationId;
    let waiting = true;
    void (async () => {
      for (const pause of ANSWER_REREADS_MS) {
        await new Promise((resolve) => setTimeout(resolve, pause));
        if (!waiting) return;
        // This is an update to the open thread, not a navigation. Selecting it
        // clears every message and briefly replaces the transcript with a loader.
        await rereadConversation(id);
        if (!waiting) return;
        if (useConversationStore.getState().currentMessages.at(-1)?.role === "assistant") return;
      }
      // The run ended and wrote nothing: its process died under it and the
      // stale-run sweep closed it. No answer is coming, so say that instead.
      if (waiting) setLostIn(id);
    })();
    return () => {
      waiting = false;
    };
  }, [runningSince, currentConversationId, rereadConversation, hasForegroundTurn]);
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
      if (sendDisabled || isRoom || compactionStatus === "running") return;
      const submission = pageContext ? captureSubmission() : undefined;
      setLostIn(null);
      if (submission) sendMessage(question, undefined, undefined, undefined, submission);
      else sendMessage(question);
    },
    [sendMessage, sendDisabled, pageContext, captureSubmission, isRoom],
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
  const sentTurnAnchoredRef = useRef(false);
  const sentTurnSpacerRef = useRef<HTMLDivElement>(null);
  const holdMessageJump = useCallback(() => {
    userScrolledUpRef.current = true;
    sentTurnAnchoredRef.current = false;
  }, []);
  const jumpReady =
    meId !== undefined &&
    tenantId !== null &&
    access.known &&
    !isConversationLoading &&
    committedTranscript?.conversationId === currentConversationId &&
    committedTranscript?.selectionVersion === selectionVersion &&
    committedTranscript?.accountId === meId &&
    committedTranscript?.tenantId === tenantId;
  const messageJump = useMessageJump({
    messageId:
      currentConversationId !== null &&
      requestedConversationId === currentConversationId &&
      threadRootId === null
        ? requestedMessageId
        : null,
    scope: JSON.stringify([meId, tenantId, currentConversationId, selectionVersion]),
    revision: messageJumpRevision,
    ready: jumpReady,
    messageIds: messages
      .filter((message) => !message.threadRootMessageId)
      .flatMap((message) => [message.id, ...(message.persistedId ? [message.persistedId] : [])]),
    firstMessageId: currentMessages[0]?.id ?? null,
    hasEarlier: hasEarlierMessages,
    loadingEarlier: isLoadingEarlier,
    loadEarlier: loadEarlierMessages,
    container: scrollContainerRef,
    beforeJump: holdMessageJump,
  });
  const canUseMessagePins =
    jumpReady &&
    currentConversationId !== null &&
    !testing &&
    onOpenMessage !== undefined &&
    (requestedConversationId === null || requestedConversationId === currentConversationId);
  // Transcript rows already carry pin state; fetch the paged list only when opened.
  const messagePins = useMessagePins(canUseMessagePins ? currentConversationId : null, false);
  useSentTurnAnchor(
    messages,
    scrollContainerRef,
    transcriptRef,
    sentTurnSpacerRef,
    sentTurnAnchoredRef,
    sentTurnId,
    userScrolledUpRef,
  );

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
      // different conversation would surprise the user. The apps keep it on
      // the device for that conversation, which brings it back (`useChat`).
      clearQueued();
    }

    prevConversationIdRef.current = currId;
  }, [currentConversationId, clearMessages, clearQueued]);

  useEffect(() => {
    // A request made before the organization list resolved has no concrete
    // tenant proof. Read it once under the resolved tenant instead of rebinding
    // that history to whichever organization happens to be selected now.
    if (
      unresolvedTranscript?.conversationId === currentConversationId &&
      unresolvedTranscript.selectionVersion === selectionVersion &&
      unresolvedTranscript.accountId === (meId ?? null) &&
      unresolvedTranscript.tenantId === null &&
      tenantId !== null
    ) {
      void rereadConversation(unresolvedTranscript.conversationId);
    }
  }, [
    unresolvedTranscript,
    currentConversationId,
    selectionVersion,
    meId,
    tenantId,
    rereadConversation,
  ]);

  useEffect(() => {
    if (
      loadedTranscript?.conversationId === currentConversationId &&
      loadedTranscript.selectionVersion === selectionVersion &&
      loadedTranscript.accountId === (meId ?? null) &&
      loadedTranscript.tenantId === tenantId &&
      currentMessages.every((message) => message.conversation_id === currentConversationId)
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
        loadedTranscript,
      );
    }
  }, [
    currentMessages,
    currentConversationId,
    loadedTranscript,
    selectionVersion,
    meId,
    tenantId,
    rereadMessages,
    soleAgentId,
  ]);

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
  const holdFollow = useCallback(
    () => emptyRef.current || userScrolledUpRef.current || sentTurnAnchoredRef.current,
    [],
  );
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
      if (sendDisabled || isRoom) return;
      dismissCall();
      const submission = pageContext ? captureSubmission() : undefined;
      if (selectedWorkflow) void workflowChat.send(selectedWorkflow, content);
      else if (holdSending)
        held.current = submission
          ? [content, fileIds, files, mentions, submission]
          : [content, fileIds, files, mentions];
      else if (submission) sendMessage(content, fileIds, files, mentions, submission);
      else sendMessage(content, fileIds, files, mentions);
    },
    [
      sendMessage,
      holdSending,
      dismissCall,
      selectedWorkflow,
      workflowChat,
      pageContext,
      captureSubmission,
      sendDisabled,
      isRoom,
      compactionStatus,
    ],
  );
  const sendSteer = useCallback(
    (content: string) => {
      if (
        !content.trim() ||
        !isProcessing ||
        !isConnected ||
        sendDisabled ||
        readOnly ||
        isRoom ||
        pageContext !== undefined ||
        selectedWorkflow !== null ||
        holdSending ||
        isStopping ||
        pendingApproval != null ||
        !!pendingQuestions?.length
      )
        return false;
      return sendSteerText(content);
    },
    [
      isProcessing,
      isConnected,
      sendDisabled,
      readOnly,
      isRoom,
      pageContext,
      selectedWorkflow,
      holdSending,
      isStopping,
      pendingApproval,
      pendingQuestions,
      sendSteerText,
    ],
  );
  useEffect(() => {
    if (
      held.current === null ||
      holdSending ||
      sendDisabled ||
      isRoom ||
      compactionStatus === "running"
    )
      return;
    const waiting = held.current;
    // A held contextual question must pass the gate for its chosen agent.
    if (waiting[4] && waiting[4].agentId !== selectedAgentId) return;
    held.current = null;
    sendMessage(...waiting);
  }, [holdSending, sendMessage, sendDisabled, selectedAgentId, isRoom, compactionStatus]);

  const handleRegenerate = useCallback(
    (assistantMessageId: string) => {
      if (sendDisabled) return;
      const idx = messages.findIndex((m) => m.id === assistantMessageId);
      if (idx < 0) return;
      for (let i = idx - 1; i >= 0; i--) {
        const m = messages[i];
        if (m?.role === "user") {
          // Regeneration is a new request to the selected agent and current page.
          send(m.content, m.fileIds, m.files, m.mentions);
          return;
        }
      }
    },
    [messages, send, sendDisabled],
  );

  const forkableConversation = openConversation ?? access.conversation;
  const ownsOpenConversation =
    forkableConversation?.user_id != null && forkableConversation.user_id === meId;
  const openId = forkableConversation?.id;
  const forking = useRef(false);
  const [forkingMessageId, setForkingMessageId] = useState<string | null>(null);
  const [activeSideThread, setActiveSideThread] = useState<{
    scopeKey: string;
    sourceConversationId: string;
    fork: ConversationForkRead;
  } | null>(null);
  const [creatingSideThread, setCreatingSideThread] = useState<{
    scopeKey: string;
    messageId: string;
  } | null>(null);
  const sideThreadScopeKey = JSON.stringify([tenantId, meId ?? null, openId ?? null]);
  const sideThreadScopeRef = useRef(sideThreadScopeKey);
  const sideThreadRequestRef = useRef<object | null>(null);
  const [sideThreadScopeState, setSideThreadScopeState] = useState(sideThreadScopeKey);
  if (sideThreadScopeState !== sideThreadScopeKey) {
    setSideThreadScopeState(sideThreadScopeKey);
    setCreatingSideThread(null);
    setActiveSideThread(null);
  }
  useLayoutEffect(() => {
    sideThreadScopeRef.current = sideThreadScopeKey;
    sideThreadRequestRef.current = null;
    return () => {
      sideThreadScopeRef.current = "";
      sideThreadRequestRef.current = null;
    };
  }, [sideThreadScopeKey]);
  const creatingSideThreadMessageId =
    creatingSideThread?.scopeKey === sideThreadScopeKey ? creatingSideThread.messageId : null;
  const canUsePersonalSideThreads = Boolean(
    openId &&
    tenantId &&
    meId &&
    ownsOpenConversation &&
    access.known &&
    !isArchived &&
    !isRoom &&
    forkableConversation?.project_id == null,
  );
  const visibleSideThread =
    canUsePersonalSideThreads && activeSideThread?.scopeKey === sideThreadScopeKey
      ? activeSideThread
      : null;

  const handleFork = useCallback(
    async (messageId: string) => {
      if (openId === undefined || forking.current) return;
      forking.current = true;
      setForkingMessageId(messageId);
      try {
        await forkConversation(openId, messageId);
      } finally {
        forking.current = false;
        setForkingMessageId(null);
      }
    },
    [forkConversation, openId],
  );
  const handleCreateSideThread = useCallback(
    async (messageId: string) => {
      if (
        !canUsePersonalSideThreads ||
        openId === undefined ||
        sideThreadRequestRef.current !== null
      ) {
        // i18n-exempt: Internal invariant; the catch shows the localized createFailed alert.
        throw new Error("Side thread cannot be created in this conversation");
      }
      const request = {};
      const scopeKey = sideThreadScopeKey;
      sideThreadRequestRef.current = request;
      setCreatingSideThread({ scopeKey, messageId });
      try {
        const fork = await createConversationSideThread(openId, messageId);
        if (sideThreadRequestRef.current !== request || sideThreadScopeRef.current !== scopeKey) {
          return;
        }
        if (
          fork.forked_from.conversation_id !== openId ||
          fork.forked_from.message_id !== messageId
        ) {
          // i18n-exempt: Internal response check; the catch shows the localized createFailed alert.
          throw new Error("Side thread response does not match its source answer");
        }
        setActiveSideThread({ scopeKey, sourceConversationId: openId, fork });
      } finally {
        if (sideThreadRequestRef.current === request) {
          sideThreadRequestRef.current = null;
          setCreatingSideThread((previous) => (previous?.scopeKey === scopeKey ? null : previous));
        }
      }
    },
    [canUsePersonalSideThreads, openId, sideThreadScopeKey],
  );
  const handleOpenSideThread = useCallback(
    (messageId: string, fork: ConversationForkRead) => {
      if (
        !canUsePersonalSideThreads ||
        openId === undefined ||
        sideThreadScopeRef.current !== sideThreadScopeKey ||
        fork.forked_from.conversation_id !== openId ||
        fork.forked_from.message_id !== messageId
      ) {
        return;
      }
      setActiveSideThread({ scopeKey: sideThreadScopeKey, sourceConversationId: openId, fork });
    },
    [canUsePersonalSideThreads, openId, sideThreadScopeKey],
  );
  const sideThreadActions: ConversationSideThreadActions | undefined =
    canUsePersonalSideThreads && openId
      ? {
          sourceConversationId: openId,
          creatingMessageId: creatingSideThreadMessageId,
          onCreate: handleCreateSideThread,
          onOpen: handleOpenSideThread,
        }
      : undefined;

  // A prompt handed in from outside - a bubble the reader clicked in the
  // widget - goes out once the socket can carry it, and only once.
  const sentPromptRef = useRef<number | null>(null);
  useEffect(() => {
    if (
      prompt === null ||
      !isConnected ||
      holdSending ||
      sendDisabled ||
      compactionStatus === "running" ||
      sentPromptRef.current === prompt.id
    ) {
      return;
    }
    sentPromptRef.current = prompt.id;
    send(prompt.text);
  }, [prompt, isConnected, holdSending, send, sendDisabled, compactionStatus]);

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
    <>
      <LocalAccessDialog />
      <ChatUI
        manualCompaction={
          ownsOpenConversation &&
          !testing &&
          !readOnly &&
          !isRoom &&
          threadRootId === null &&
          selectedWorkflow === null &&
          pageContext === undefined
            ? {
                available: compactionAvailable,
                status: compactionStatus,
                progress: compactionProgress,
                onCompact: compactConversation,
                disabled:
                  !compactionReady ||
                  !jumpReady ||
                  sendDisabled ||
                  holdSending ||
                  !isConnected ||
                  isProcessing ||
                  isStopping ||
                  canStopParked ||
                  interrupted ||
                  detachedTurnPending ||
                  leftTurnPending ||
                  runningSince !== null ||
                  queuedMessages.length > 0 ||
                  pendingApproval != null ||
                  !!pendingQuestions?.length ||
                  !!pendingSecretRequests?.length ||
                  pendingConnection != null ||
                  pendingComputerAccess != null ||
                  callActive(voice),
              }
            : undefined
        }
        sideThreadActions={sideThreadActions}
        messagePinActions={
          canUseMessagePins
            ? {
                pendingMessageId: messagePins.pendingMessageId,
                togglePin: messagePins.togglePin,
              }
            : undefined
        }
        onOpenPinnedMessage={
          canUseMessagePins
            ? (target) => {
                if (currentConversationId !== null)
                  onOpenMessage?.({
                    ...target,
                    conversationId: currentConversationId,
                    threadRootMessageId: target.threadRootMessageId ?? undefined,
                  });
              }
            : undefined
        }
        roomProjectId={roomProjectId}
        isRoom={isRoom}
        conversation={openConversation ?? null}
        roomReadOnly={isArchived || !access.known}
        threadRootId={threadRootId}
        requestedMessageId={
          requestedConversationId === currentConversationId ? requestedMessageId : null
        }
        messageJumpRevision={messageJumpRevision}
        messageJump={
          messageJump.status !== "idle" && !jumpReady && (conversationError || access.failed)
            ? {
                ...messageJump,
                status: "failed",
                retry: () => {
                  messageJump.retry();
                  if (currentConversationId !== null)
                    void rereadConversation(currentConversationId);
                },
              }
            : messageJump
        }
        onOpenThread={onOpenThread}
        onCloseThread={onCloseThread}
        canStartThread={canStartThread}
        activeThreadRootId={activeThreadRootId}
        actionThreadRoots={actionThreadRoots}
        hasPendingComputerAccess={pendingComputerAccess !== null}
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
        onAskAgain={lostQuestion === null || isRoom ? undefined : () => askAgain(lostQuestion)}
        onRecheck={handleRecheck}
        personalGaps={personalGaps}
        // The live turn's cost while there is one, and the newest measured answer in
        // the transcript otherwise - which is what makes the strip appear on a
        // conversation somebody has just reopened instead of after their next message.
        lastUsage={lastUsage ?? latestUsage(currentMessages, currentConversationId)}
        contextWindow={contextWindow}
        agentCapabilities={agentCapabilities}
        agentHostedCapabilities={selectedAgent?.published_hosted_capabilities ?? null}
        workspaceCanRun={
          selectedAgent?.can_run === true && !selectedWorkflow && !testing && !holdSending
        }
        agentUsesLocalTools={Boolean(
          selectedAgent?.local_workspace || selectedAgent?.local_coding_agent,
        )}
        agentModel={agentModel}
        // Only for the thread that is actually open. The store keeps the transcript
        // it last loaded, so between clicking another conversation and its messages
        // arriving this figure belongs to the one just left - the same reason
        // `latestUsage` is given the id rather than trusting the list.
        conversationCost={currentConversationId === null ? null : currentCost}
        delegations={delegations}
        browses={browses}
        onBrowserProtected={protectBrowser}
        conversationId={currentConversationId}
        turns={turns}
        attachments={attachments}
        isLoadingConversation={
          (requestedConversationId !== null && requestedConversationId !== currentConversationId) ||
          (currentConversationId !== null && isConversationLoading && messages.length === 0)
        }
        isArchived={isArchived}
        readOnly={readOnly}
        projectReadOnly={projectReadOnly}
        viewOnly={viewOnly}
        accessState={access.failed ? "error" : !access.known ? "checking" : undefined}
        onRetryAccess={access.retry}
        sendMessage={send}
        onSteer={sendSteer}
        showSendMode={selectedWorkflow === null && !holdSending}
        steerContextAvailable={
          pageContext === undefined && selectedWorkflow === null && !holdSending
        }
        sendDisabled={sendDisabled}
        steers={steers}
        // Kept here as well as pushed into the hook, because the context gauge is a
        // share of *this* model's window: a switch has to move the figure at once,
        // and one carried over from a 1M-context model reads "50%" for a history
        // that is really at 390% of a 128K one.
        onModelProfileChange={(profileId) => {
          setModelProfile(profileId);
        }}
        // Only into the hook: nothing on screen is a share of it, unlike the
        // context gauge the model switch has to move.
        onApprovalModeChange={setApprovalMode}
        onRegenerate={
          readOnly || isRoom || compactionStatus === "running" ? undefined : handleRegenerate
        }
        onFork={ownsOpenConversation && access.known ? handleFork : undefined}
        forkingMessageId={forkingMessageId}
        forkedFrom={forkableConversation?.forked_from ?? null}
        onOpenForkSource={(id) => {
          if (onOpenParent)
            onOpenParent({
              conversationId: id,
              messageId: forkableConversation?.forked_from?.message_id ?? null,
            });
          else void selectConversation(id);
        }}
        pins={pins}
        slashContext={slashContext}
        slashCommands={slashCommands}
        queuedMessages={queuedMessages}
        onCancelQueued={cancelQueued}
        onRetryQueued={retryQueued}
        onSendQueuedNow={sendQueuedNow}
        onMoveQueued={moveQueued}
        transcriptRef={transcriptRef}
        scrollContainerRef={scrollContainerRef}
        userScrolledUpRef={userScrolledUpRef}
        sentTurnAnchoredRef={sentTurnAnchoredRef}
        sentTurnSpacerRef={sentTurnSpacerRef}
        pendingApproval={pendingApproval}
        continuingApproval={continuingApproval}
        onResumeDecisions={sendResumeDecisions}
        mayRememberApproval={mayRememberApproval}
        pendingQuestions={pendingQuestions}
        onAnswerQuestions={sendAskUserResponses}
        pendingSecretRequests={pendingSecretRequests}
        onSubmitSecretRequest={submitSecretRequest}
        onDeclineSecretRequest={declineSecretRequest}
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
        incomingFiles={incomingFiles ?? sharedHere}
        onVisualReport={reportVisual}
      />
      {visibleSideThread && (
        <PersonalSideThreadPanel
          key={`${visibleSideThread.scopeKey}:${visibleSideThread.fork.id}`}
          sourceConversationId={visibleSideThread.sourceConversationId}
          fork={visibleSideThread.fork}
          onClose={() => setActiveSideThread(null)}
          onOpenParent={(target) => {
            setActiveSideThread(null);
            if (onOpenParent) onOpenParent(target);
            else if (target.conversationId !== currentConversationId)
              void selectConversation(target.conversationId);
          }}
        />
      )}
    </>
  );
}

interface ChatUIProps {
  manualCompaction?: {
    available: boolean;
    status: ChatCompactionStatus;
    progress: Compaction | null;
    disabled: boolean;
    onCompact: () => boolean;
  };
  sideThreadActions?: ConversationSideThreadActions;
  messagePinActions?: MessagePinActions;
  onOpenPinnedMessage?: (target: PinnedMessageTarget) => void;
  roomProjectId: string | null;
  isRoom: boolean;
  conversation: Conversation | null;
  roomReadOnly: boolean;
  threadRootId: string | null;
  requestedMessageId: string | null;
  messageJumpRevision: number;
  messageJump: MessageJumpState;
  onOpenThread?: (rootId: string) => void;
  onCloseThread?: () => void;
  canStartThread: boolean;
  activeThreadRootId: string | null;
  actionThreadRoots: ReturnType<typeof useChat>["actionThreadRoots"];
  hasPendingComputerAccess: boolean;
  sendDisabled?: boolean;
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
  agentCapabilities: string[] | null;
  agentHostedCapabilities?: string[] | null;
  workspaceCanRun?: boolean;
  agentUsesLocalTools?: boolean;
  /**
   * The turn's delegations, drawn under the transcript.
   *
   * Under it rather than inside the assistant message, and they outlive the turn's
   * `complete` - a background delegation reports after the parent has answered.
   */
  delegations: Delegation[];
  /** The turn's browses, for the live preview panel. See `BrowserPanel`. */
  browses: Browse[];
  onBrowserProtected?: (protection: BrowserProtection) => void;
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
  viewOnly?: boolean;
  readOnly: boolean;
  /** Somebody else's thread, or its access is unknown: its project chip is read-only. */
  projectReadOnly: boolean;
  accessState?: "checking" | "error";
  onRetryAccess: () => void;
  sendMessage: (
    content: string,
    fileIds?: string[],
    files?: import("@/types").ChatMessageFile[],
    mentions?: Mentionable[],
  ) => void;
  onSteer?: (content: string) => boolean;
  showSendMode?: boolean;
  steerContextAvailable?: boolean;
  onModelProfileChange?: (profileId: string | null) => void;
  onApprovalModeChange?: (mode: import("./chat-controls").ApprovalMode) => void;
  onRegenerate?: (messageId: string) => void;
  onFork?: (messageId: string) => void;
  forkingMessageId?: string | null;
  forkedFrom?: ConversationForkOrigin | null;
  onOpenForkSource?: (conversationId: string) => void;
  pins?: PinnedPrompts;
  slashContext?: import("./slash-commands").SlashCommandContext;
  slashCommands?: import("./slash-commands").SlashCommand[];
  queuedMessages?: import("@/hooks/use-chat").QueuedMessage[];
  onCancelQueued?: (id: string) => void;
  /** Sends a message the server refused again, in its place in the queue. */
  onRetryQueued?: (id: string) => void;
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
  sentTurnAnchoredRef: React.RefObject<boolean>;
  sentTurnSpacerRef: React.RefObject<HTMLDivElement | null>;
  pendingApproval?: PendingApproval | null;
  continuingApproval?: boolean;
  onResumeDecisions?: (decisions: Decision[]) => void;
  mayRememberApproval?: boolean;
  pendingQuestions?: AskUserQuestion[] | null;
  onAnswerQuestions?: (answers: AskUserAnswer[]) => void;
  /** The secrets a parked run asked its person for. See `SecretRequestCard`. */
  pendingSecretRequests?: ParkedSecretRequest[] | null;
  onSubmitSecretRequest?: (requestId: string, value: string) => void;
  onDeclineSecretRequest?: (requestId: string) => void;
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

interface DirectChatDraft {
  content: string;
  accountId: string | null;
  organizationId: string | null;
  conversationId: string | null;
  selectionVersion: number;
}

interface CreatedRoomDraftHandoff {
  roomId: string;
  projectId: string;
  accountId: string;
  organizationId: string;
  selectionVersion: number;
}

function ChatUI({
  manualCompaction,
  sideThreadActions,
  messagePinActions,
  onOpenPinnedMessage,
  roomProjectId,
  isRoom,
  conversation,
  roomReadOnly,
  threadRootId,
  requestedMessageId,
  messageJumpRevision,
  messageJump,
  onOpenThread,
  onCloseThread,
  canStartThread,
  activeThreadRootId,
  actionThreadRoots,
  hasPendingComputerAccess,
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
  agentCapabilities,
  agentHostedCapabilities = null,
  workspaceCanRun = false,
  agentUsesLocalTools = false,
  delegations,
  browses,
  onBrowserProtected,
  conversationId,
  turns,
  attachments,
  isLoadingConversation,
  isArchived,
  viewOnly = false,
  readOnly,
  projectReadOnly,
  accessState,
  onRetryAccess,
  sendMessage,
  onSteer,
  showSendMode = true,
  steerContextAvailable = true,
  onModelProfileChange,
  onApprovalModeChange,
  onRegenerate,
  onFork,
  forkingMessageId,
  forkedFrom,
  onOpenForkSource,
  pins,
  slashContext,
  slashCommands,
  queuedMessages,
  onCancelQueued,
  onRetryQueued,
  onSendQueuedNow,
  onMoveQueued,
  steers = [],
  transcriptRef,
  scrollContainerRef,
  userScrolledUpRef,
  sentTurnAnchoredRef,
  sentTurnSpacerRef,
  pendingApproval,
  continuingApproval = false,
  onResumeDecisions,
  mayRememberApproval,
  pendingQuestions,
  onAnswerQuestions,
  pendingSecretRequests,
  onSubmitSecretRequest,
  onDeclineSecretRequest,
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
  sendDisabled = false,
}: ChatUIProps) {
  const manualCompacting = manualCompaction?.status === "running";
  const directDraftRef = useRef<DirectChatDraft | null>(null);
  const createdRoomDraftHandoffRef = useRef<CreatedRoomDraftHandoff | null>(null);
  const conversationApi = useConversationStore.useApi();
  const selectionVersion = useConversationStore((state) => state.selectionVersion);
  const composerFocusRequest = useConversationStore((state) => state.composerFocusRequest);
  const t = useTranslations("chat");
  const tThread = useTranslations("chat.roomThread");
  const tDictation = useTranslations("chat.dictation");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const accountId = useAuthStore((state) => state.user?.id ?? null);
  const recordDirectDraft = useCallback(
    (content: string) => {
      directDraftRef.current = {
        content,
        accountId,
        organizationId: activeOrgId,
        conversationId,
        selectionVersion,
      };
    },
    [accountId, activeOrgId, conversationId, selectionVersion],
  );
  const authorizeCreatedRoomDraft = useCallback(
    (roomId: string, projectId: string) => {
      const current = conversationApi.getState();
      if (
        accountId === null ||
        activeOrgId === null ||
        conversationId !== null ||
        roomProjectId !== projectId ||
        useAuthStore.getState().user?.id !== accountId ||
        useOrgStore.getState().activeOrgId !== activeOrgId ||
        current.currentConversationId !== null ||
        current.pendingProjectId !== projectId ||
        current.selectionVersion !== selectionVersion
      ) {
        createdRoomDraftHandoffRef.current = null;
        return false;
      }

      const draft = directDraftRef.current;
      if (
        draft !== null &&
        draft.content.length > 0 &&
        draft.accountId === accountId &&
        draft.organizationId === activeOrgId &&
        draft.conversationId === null &&
        draft.selectionVersion === selectionVersion
      ) {
        createdRoomDraftHandoffRef.current = {
          roomId,
          projectId,
          accountId,
          organizationId: activeOrgId,
          selectionVersion,
        };
      } else {
        createdRoomDraftHandoffRef.current = null;
      }
      return true;
    },
    [accountId, activeOrgId, conversationApi, conversationId, roomProjectId, selectionVersion],
  );
  const consumeDirectDraft = useCallback(() => {
    const draft = directDraftRef.current;
    if (draft === null) return "";

    const current = conversationApi.getState();
    const sameIdentity =
      useAuthStore.getState().user?.id === accountId &&
      useOrgStore.getState().activeOrgId === activeOrgId;
    const sameSelection =
      current.currentConversationId === conversationId &&
      current.selectionVersion === selectionVersion;
    if (!sameIdentity || !sameSelection) return "";

    const belongsToCurrentConversation =
      draft.accountId === accountId &&
      draft.organizationId === activeOrgId &&
      draft.conversationId === conversationId &&
      draft.selectionVersion === selectionVersion;
    if (belongsToCurrentConversation) {
      directDraftRef.current = null;
      createdRoomDraftHandoffRef.current = null;
      return draft.content;
    }

    const handoff = createdRoomDraftHandoffRef.current;
    if (handoff?.roomId === conversationId) createdRoomDraftHandoffRef.current = null;
    const belongsToCreatedRoom =
      handoff !== null &&
      handoff.roomId === conversationId &&
      handoff.projectId === roomProjectId &&
      handoff.accountId === accountId &&
      handoff.organizationId === activeOrgId &&
      handoff.selectionVersion === draft.selectionVersion &&
      current.selectionVersion === handoff.selectionVersion + 1 &&
      draft.accountId === accountId &&
      draft.organizationId === activeOrgId &&
      draft.conversationId === null;
    if (belongsToCreatedRoom) {
      directDraftRef.current = null;
      return draft.content;
    }

    directDraftRef.current = null;
    return "";
  }, [accountId, activeOrgId, conversationApi, conversationId, roomProjectId, selectionVersion]);
  const roomRequests = useRoomRequests(isRoom ? conversationId : null);
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { mode: sendMode, setMode: setSendMode } = useChatSendModePreference(
    accountId,
    activeOrgId,
    selectedAgentId,
  );
  const {
    status,
    failed: dictationStatusFailed,
    engine,
    mic,
    maxSeconds,
    state: dictationState,
    actions: dictationActions,
  } = useAgentDictation(selectedAgentId);
  const cancelDictation = dictationActions.cancel;
  const { can } = usePermissions();
  const voiceSettingsHref =
    activeOrgId !== null && can(Perm.orgSettings)
      ? `${ROUTES.ORG_MEMBERS(activeOrgId)}?tab=voice`
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
  // The apps keep what is written without a connection in the outbox and send
  // it when one comes back (#2097), so their composer stays open; a browser
  // tab keeps nothing, and waits for the socket.
  const keepsOutbox = useMounted() && offlineAvailable();
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
  const messagePinsControl =
    conversationId !== null && messagePinActions && onOpenPinnedMessage ? (
      <PinnedMessages
        key={`${accountId}:${activeOrgId}:${conversationId}`}
        conversationId={conversationId}
        onJumpToMessage={onOpenPinnedMessage}
      />
    ) : null;

  // A voice call (#54): offered in Send's place when the selected agent can take
  // one, crossed out with the reason when it cannot - in the narrow windows too.
  // The test panel runs the draft while a call runs what is published, so there
  // the button says so.
  const tVoice = useTranslations("chat.voice");
  const offerCall = hasAgent && !isRoom;
  const { readiness, failed: readinessFailed } = useVoiceReadiness(
    offerCall ? selectedAgentId : null,
  );
  const onCall = callActive(voice);
  const startCall = () => {
    if (manualCompacting) return;
    if (dictationState.phase !== "idle") cancelDictation();
    onStartCall(readiness?.transport ?? voice.call.transport ?? "webrtc");
  };
  // A phone shortcut's "Voice call" or "Dictate" (#2097), acted on once this
  // agent's readiness is known: started as its button would be, or dropped
  // where the button is crossed out - which then says why.
  const intent = useComposerIntentStore((state) => state.intent);
  const clearIntent = useComposerIntentStore((state) => state.clear);
  const callRequested = intent === "call" && offerCall && (readiness !== null || readinessFailed);
  const callOnRequest = useEffectEvent(() => {
    clearIntent();
    if (readiness?.available && !onCall && !isProcessing && !readOnly && !manualCompacting)
      startCall();
  });
  useEffect(() => {
    if (callRequested) callOnRequest();
  }, [callRequested]);
  const conversationActions =
    messagePinsControl || manualCompaction?.available || manualCompacting ? (
      <>
        {messagePinsControl}
        {manualCompaction && (
          <ChatCompactionControl
            available={manualCompaction.available}
            status={manualCompaction.status}
            disabled={manualCompaction.disabled || onCall || dictationState.phase !== "idle"}
            onCompact={manualCompaction.onCompact}
          />
        )}
      </>
    ) : null;
  const dictateNow = intent === "dictate" && hasAgent && (status !== null || dictationStatusFailed);
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
      coalesceActivity(messages).map((message) => ({
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
  const [homeHintsSlot, setHomeHintsSlot] = useState<HTMLDivElement | null>(null);
  const [attachmentSlot, setAttachmentSlot] = useState<HTMLDivElement | null>(null);
  // Real tool identities keep desktop frames separate from browser pages.
  const surfaces = useMemo(() => browseSurfaces(messages), [messages]);
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
    if (scroller === null || userScrolledUpRef.current || sentTurnAnchoredRef.current || empty)
      return;
    scroller.scrollTop = scroller.scrollHeight;
  }, [
    dockHeight,
    scrollContainerRef,
    userScrolledUpRef,
    sentTurnAnchoredRef,
    messages.length,
    voice.call.phase,
  ]);
  const callReady = offerCall && readiness?.available === true;
  const callShown = offerCall && (readiness !== null || readinessFailed);
  // Hidden, not unmounted, during a call: the pill holds its controls, and focus
  // comes back here when it ends.
  const callButton = (
    <span ref={callButtonRef} className={onCall ? "hidden" : "contents"}>
      <VoiceCallButton
        readiness={readiness}
        failed={readinessFailed}
        disabled={isProcessing || readOnly || manualCompacting}
        onStart={startCall}
        setUpHref={agentCallsHref}
        prominent={callReady}
        publishedOnly={testingDraft}
      />
    </span>
  );

  const matchesAction = (scope: string | null, root: string | null) => scope === root;
  const actionsDisabled = (isRoom ? !canStartThread : readOnly) || !isConnected || isStopping;
  const otherActions = [
    ...new Set([
      ...(pendingApproval ? [actionThreadRoots.approval] : []),
      ...(pendingQuestions?.length ? [actionThreadRoots.questions] : []),
      ...(pendingSecretRequests?.length ? [actionThreadRoots.secrets] : []),
      ...(pendingConnection ? [actionThreadRoots.connection] : []),
      ...(hasPendingComputerAccess ? [actionThreadRoots.computer] : []),
    ]),
  ].filter((root) => root !== threadRootId);
  const renderActions = (root: string | null, scopeReadOnly = false) => (
    <>
      {pendingApproval && onResumeDecisions && matchesAction(actionThreadRoots.approval, root) && (
        <div className="pointer-events-auto mx-auto w-full max-w-4xl min-w-0 px-4 pb-2 sm:px-6">
          <ToolApprovalDialog
            actionRequests={pendingApproval.actionRequests}
            reviewConfigs={pendingApproval.reviewConfigs}
            onDecisions={onResumeDecisions}
            mayRemember={mayRememberApproval}
            disabled={scopeReadOnly || actionsDisabled || (root !== null && !isRoom)}
          />
        </div>
      )}
      {pendingConnection &&
        onConnectionResponse &&
        matchesAction(actionThreadRoots.connection, root) && (
          <div className="pointer-events-auto mx-auto w-full max-w-4xl min-w-0 px-4 pb-2 sm:px-6">
            <ConnectAccountPrompt
              request={pendingConnection}
              disabled={scopeReadOnly || actionsDisabled || (root !== null && !isRoom)}
              onRespond={onConnectionResponse}
            />
          </div>
        )}
      {pendingQuestions &&
        pendingQuestions.length > 0 &&
        onAnswerQuestions &&
        matchesAction(actionThreadRoots.questions, root) && (
          <div className="pointer-events-auto mx-auto w-full max-w-4xl min-w-0 px-4 pb-2 sm:px-6">
            <QuestionPrompt
              questions={pendingQuestions}
              disabled={scopeReadOnly || actionsDisabled || (root !== null && !isRoom)}
              onComplete={onAnswerQuestions}
            />
          </div>
        )}
      {pendingSecretRequests &&
        matchesAction(actionThreadRoots.secrets, root) &&
        pendingSecretRequests.length > 0 &&
        onSubmitSecretRequest &&
        onDeclineSecretRequest && (
          <div className="pointer-events-auto mx-auto w-full max-w-4xl min-w-0 px-4 pb-2 sm:px-6">
            <SecretRequestCard
              requests={pendingSecretRequests}
              disabled={scopeReadOnly || actionsDisabled || (root !== null && !isRoom)}
              onSubmit={onSubmitSecretRequest}
              onDecline={onDeclineSecretRequest}
            />
          </div>
        )}
    </>
  );
  const threadNotices =
    isRoom && otherActions.length > 0 ? (
      <div className="pointer-events-auto mx-auto max-w-4xl space-y-2 px-4 pb-2 text-xs sm:px-6">
        {otherActions.map((root) => (
          <button
            key={root ?? "main"}
            type="button"
            aria-label={root === null ? tThread("main") : tThread("open")}
            className="text-primary block underline underline-offset-2"
            onClick={() => (root === null ? onCloseThread?.() : onOpenThread?.(root))}
          >
            {root === null ? tThread("mainPending") : tThread("pending")}{" "}
            {root === null ? tThread("main") : tThread("open")}
          </button>
        ))}
      </div>
    ) : null;
  const showWorkspaceHome =
    !compact &&
    !isRoom &&
    messages.length === 0 &&
    voice.call.phase === "idle" &&
    !isLoadingConversation;
  return (
    <div className="chat-surface @container/sources-layout relative flex h-full min-h-0 w-full min-w-0 overflow-hidden">
      <div className="@container/browser-layout relative flex h-full min-h-0 min-w-0 flex-1">
        {/* The column no longer carries the width. The scroller does, and the
          content is centred inside it - so the scrollbar sits at the edge of the
          pane where a scrollbar belongs, rather than a hundred pixels to the
          right of the text with white on both sides of it. */}
        {/* `@container/chat`: the turn rail sits in the column's left margin, so it
          shows only while the column is wide enough to have one beside the
          centred transcript - not at a window width, which says nothing about
          a column narrowed by the sidebar and the conversation list. */}
        <div
          className={cn(
            "@container/chat relative flex h-full min-h-0 min-w-0 flex-1 flex-col",
            showWorkspaceHome && "chat-home-column justify-center-safe overflow-y-auto",
            threadRootId !== null && "max-lg:invisible",
          )}
        >
          {!compact && <TurnRail entries={railEntries} />}
          {!compact && !isRoom && hasAgent && (
            <ChatModelHeader
              key={`${authUser?.id}:${activeOrgId}:${selectedAgentId}`}
              name={callAgent?.name ?? t("rail.agent")}
              agentModel={agentModel}
              readOnly={
                readOnly ||
                isArchived === true ||
                isLoadingConversation === true ||
                manualCompacting
              }
              isProcessing={isProcessing || manualCompacting}
              canEditAgent={Boolean(
                callAgent?.can_edit &&
                !readOnly &&
                isArchived !== true &&
                !isLoadingConversation &&
                !manualCompacting,
              )}
              home={showWorkspaceHome}
              onChange={(profileId) => onModelProfileChange?.(profileId)}
              actions={conversationActions}
            />
          )}
          {(compact || isRoom || !hasAgent) && conversationActions && (
            <div
              data-chat-model-header
              className={cn(
                "flex shrink-0 items-center justify-end border-b px-3 py-1",
                !compact && "max-lg:pt-14",
              )}
            >
              {conversationActions}
            </div>
          )}
          <MessageJumpNotice jump={messageJump} />
          <div
            ref={scrollContainerRef}
            data-chat-scroller
            className={cn(
              "min-h-0 min-w-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain",
              showWorkspaceHome && "flex-none overflow-visible pb-0!",
            )}
            style={{
              paddingBottom: dockHeight,
              // In the page the transcript fades out as it reaches the glass
              // composer, so nothing sharp is ever behind it: a backdrop blur is
              // drawn by the GPU and is not always drawn - a screen capture, a
              // throttled tab - and without it the words under the box read
              // through it, crisp, beside the placeholder.
              ...(compact || messages.length === 0
                ? {}
                : {
                    maskImage: `linear-gradient(to bottom, #000 calc(100% - ${dockHeight + 8}px), transparent calc(100% - ${Math.max(dockHeight - 32, 0)}px))`,
                  }),
            }}
          >
            <div
              ref={transcriptRef}
              data-transcript
              className={cn(
                "w-full min-w-0",
                compact ? "px-3 py-3 text-sm" : "mx-auto max-w-4xl px-4 py-4 sm:px-6 sm:py-6",
              )}
            >
              {/* Who else has this chat open, held at the top while the transcript scrolls:
                a project's chat is several people's at once. */}
              {roomProjectId !== null && (
                <TeamRoomHeader
                  projectId={roomProjectId}
                  present={present}
                  conversation={conversation}
                />
              )}
              {roomProjectId !== null && conversationId && !isLoadingConversation && (
                <RoomRoutingPanel
                  conversationId={conversationId}
                  readOnly={readOnly}
                  onOpenThread={onOpenThread}
                />
              )}
              {roomProjectId === null && conversationId && (isRoom || !compact) && (
                <ChatRoomBar
                  conversationId={conversationId}
                  conversation={conversation}
                  present={present}
                  meId={authUser?.id}
                  canShare={ownsConversation}
                  className="sticky top-2 z-20 mb-3"
                />
              )}
              {isLoadingConversation ? (
                <ConversationSkeleton />
              ) : messages.length === 0 && voice.call.phase === "idle" ? (
                <div className={cn("flex h-full items-center", !emptyState && "chat-empty-state")}>
                  {isRoom ? (
                    <TeamRoomEmpty />
                  ) : emptyState ? (
                    emptyState((picked) => sendMessage(picked))
                  ) : (
                    <ChatEmptyState
                      suggestionsSlot={!compact ? homeHintsSlot : undefined}
                      onPick={(picked) => sendMessage(picked)}
                    />
                  )}
                </div>
              ) : (
                <LiveBrowsesProvider
                  value={{
                    browses,
                    surfaces,
                    onComment: commentOnPage,
                    onProtected: onBrowserProtected,
                  }}
                >
                  <ConversationVisualsProvider
                    messages={messages}
                    conversationId={conversationId}
                    onReport={onVisualReport}
                    onCompose={(text) => setIncoming({ id: Date.now(), files: [], text })}
                    onSend={readOnly ? undefined : (text) => sendMessage(text)}
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
                    {forkedFrom && onOpenForkSource && (
                      <ForkedFrom origin={forkedFrom} onOpen={onOpenForkSource} />
                    )}
                    <MessageList
                      messages={messages}
                      roomReactionsEnabled={isRoom}
                      canReactToRoomMessages={
                        isRoom &&
                        !roomReadOnly &&
                        !roomRequests.isError &&
                        roomRequests.data?.can_post === true
                      }
                      delegations={delegations}
                      sideThreadActions={sideThreadActions}
                      messagePinActions={messagePinActions}
                      onRegenerate={onRegenerate}
                      onFork={onFork}
                      forkingMessageId={forkingMessageId}
                      pins={pins}
                      onOpenThread={onOpenThread}
                      canStartThread={canStartThread}
                      allowReply={!readOnly && (!isRoom || canStartThread)}
                    />
                  </ConversationVisualsProvider>
                </LiveBrowsesProvider>
              )}
              {/* After the transcript, not inside it: a delegation is a second agent's
                conversation happening inside one turn of this one, and it can still be
                streaming when the turn it belongs to has already answered. */}
              <DelegationPanels
                delegations={isRoom && activeThreadRootId !== null ? [] : delegations}
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
                    allowReply={false}
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
              <div ref={sentTurnSpacerRef} aria-hidden className="pointer-events-none" />
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
            data-chat-dock
            onMouseDownCapture={(event) => {
              // Keep the keyboard and caret while tapping Send or attachment
              // actions. Menus manage their own focus after their click.
              if (
                document.activeElement?.getAttribute("contenteditable") === "true" &&
                event.target instanceof Element &&
                event.target.closest("button")
              )
                event.preventDefault();
            }}
            className={cn(
              "pointer-events-none inset-x-0 bottom-0 z-20",
              showWorkspaceHome ? "relative shrink-0" : "absolute",
              compact && "bg-background",
            )}
          >
            {/* Actionable notices belong beside the composer, outside the transcript.
              The approval panel replaces approval notices, including older runs. */}
            {conversationId && !compact && (
              <OutcomeCards
                conversationId={conversationId}
                hasApprovalPanel={!!pendingApproval && !!onResumeDecisions}
                isWorking={
                  isProcessing ||
                  continuingApproval ||
                  messages.some((message) => message.isStreaming)
                }
                className="pointer-events-auto mx-auto max-h-40 w-full max-w-4xl min-w-0 overflow-y-auto overscroll-contain px-4 pb-2 sm:px-6"
              />
            )}
            {personalGaps.length > 0 && (!isRoom || activeThreadRootId === null) && (
              <div className="chat-composer-suggestions pointer-events-auto mx-auto w-full max-w-4xl min-w-0 px-4 pb-2 sm:px-6">
                <ConnectServicesCard gaps={personalGaps} />
              </div>
            )}
            {renderActions(null)}
            {threadRootId === null && threadNotices}
            <div
              className={cn(
                "pointer-events-auto mx-auto w-full min-w-0",
                // Glass in the page: the answer scrolls on behind the composer,
                // blurred, and the strip fades to the page by the caption under it
                // so no line of text is ever cut in half behind the words.
                compact
                  ? "px-3 pt-1 pb-1.5"
                  : "max-w-4xl bg-[linear-gradient(to_bottom,transparent_30%,var(--color-background)_62%)] px-4 pb-4 sm:px-6",
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
              {!isRoom && onCancelQueued && (
                <PendingMessages
                  messages={queuedMessages ?? []}
                  steers={steers}
                  onCancel={onCancelQueued}
                  onRetry={onRetryQueued}
                  waitingForNetwork={!isConnected}
                  onSendNow={isProcessing && isConnected ? onSendQueuedNow : undefined}
                  onMove={onMoveQueued}
                />
              )}
              {/* The checklist the agent is working to. Here rather than in the
                transcript because a plan is written in one turn and worked through
                over the next several: as a step it scrolls away under the work it
                describes, and what somebody wants is where the agent is now. */}
              <BackgroundTasks conversationId={conversationId} />
              <PlanStrip
                plan={plan}
                live={isProcessing && (!isRoom || activeThreadRootId === null)}
              />
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
              {isRoom ? (
                <TeamRoomComposer
                  key={`${activeOrgId}:${authUser?.id}:${conversationId}`}
                  projectId={roomProjectId}
                  conversationId={conversationId}
                  readOnly={roomReadOnly}
                  onTyping={onTyping}
                  consumeInitialContent={consumeDirectDraft}
                  onRoomCreated={authorizeCreatedRoomDraft}
                />
              ) : (viewOnly || accessState) && !onCall ? (
                <ConversationAccessNotice state={accessState ?? "view"} onRetry={onRetryAccess} />
              ) : (
                <div className="@container min-w-0">
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
                                  <DictationPill
                                    state={dictationState}
                                    actions={dictationActions}
                                  />
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
                      {/* Every hint on top of the box, beside the pill it belongs to. */}
                      {!readOnly && !onCall && !manualCompacting && (
                        <NextSteps steps={nextSteps} onPick={(step) => sendMessage(step)} />
                      )}
                      {callAgent?.personal_model_key && (
                        <PersonalModelConnection key={selectedAgentId} agentId={selectedAgentId} />
                      )}
                      {manualCompaction && (
                        <ChatCompactionNotice
                          status={manualCompaction.status}
                          messagesBefore={manualCompaction.progress?.messages_before}
                        />
                      )}
                      <DictationStrip hint={composerStrip} placement="above" />
                      <div
                        data-tour="chat-composer"
                        className={cn(
                          "panel composer-box focus-within:border-foreground/25 focus-within:ring-foreground/10 min-w-0 rounded-2xl transition-colors focus-within:ring-2",
                          composerStrip !== null && "rounded-t-none",
                        )}
                      >
                        {!agentFixed && (
                          <div className="border-border bg-muted/40 hidden items-center rounded-t-2xl border-b px-3 py-1.5 has-[a]:flex">
                            <ProjectChip
                              conversationId={conversationId}
                              pickerOpen={projectPickerOpen}
                              onPickerOpenChange={setProjectPickerOpen}
                            />
                          </div>
                        )}
                        <div
                          className={cn("min-w-0 px-3 pt-2 pb-2", !compact && "sm:px-4 sm:pt-3")}
                        >
                          {isArchived && (
                            <p className="text-muted-foreground pb-2 text-center font-mono text-xs tracking-wider uppercase">
                              {t("conversationArchived")}
                            </p>
                          )}
                          {/* One row of actions under the text, the same at every
                          level of every limit: attach and who answers on the left;
                          files, settings, the microphone and send on the right. A
                          limit near its end changes an icon's colour and never
                          costs the row a button. */}
                          <ChatInput
                            key={JSON.stringify([accountId, activeOrgId, selectionVersion])}
                            autoFocus={!compact && !onCall && requestedMessageId === null}
                            preserveReadingFocus={requestedMessageId !== null}
                            focusRequest={composerFocusRequest}
                            onSend={sendMessage}
                            sendMode={
                              showSendMode &&
                              isProcessing &&
                              !readOnly &&
                              isArchived !== true &&
                              !isLoadingConversation &&
                              !sendDisabled &&
                              !pendingApproval &&
                              !pendingQuestions?.length &&
                              !isStopping &&
                              !onCall &&
                              !isRoom
                                ? sendMode
                                : undefined
                            }
                            onSendModeChange={showSendMode ? setSendMode : undefined}
                            onSteer={onSteer}
                            steerContextAvailable={steerContextAvailable}
                            // Mentions address the agent the thread is talking to -
                            // in a fixed window (the test panel, the Architect) the
                            // scope's own selection holds it.
                            agentId={delegatingAgentId}
                            mentionsFromDraft={testingDraft}
                            hints={messages.length === 0}
                            disabled={
                              sendDisabled ||
                              manualCompacting ||
                              isStopping ||
                              isLoadingConversation ||
                              (!isConnected && !keepsOutbox) ||
                              readOnly ||
                              onCall ||
                              !!pendingApproval ||
                              !!(pendingQuestions && pendingQuestions.length)
                            }
                            isProcessing={isProcessing}
                            canStop={
                              manualCompacting ||
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
                            onTextDraftChange={recordDirectDraft}
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
                            dictateNow={dictateNow}
                            onDictateStarted={clearIntent}
                            // Who answers first and largest: it is the most
                            // consequential choice in the composer.
                            controlsSlot={
                              <>
                                {!agentFixed && (
                                  <fieldset disabled={manualCompacting} className="contents">
                                    <AgentPicker />
                                  </fieldset>
                                )}
                                <ChatApprovalSelector
                                  onChange={onApprovalModeChange}
                                  disabled={isProcessing || readOnly || manualCompacting}
                                />
                                {!agentFixed && (
                                  <span className="contents max-md:hidden">
                                    <ProjectChip
                                      conversationId={conversationId}
                                      pickerOpen={projectPickerOpen}
                                      onPickerOpenChange={setProjectPickerOpen}
                                      readOnly={projectReadOnly || manualCompacting}
                                    />
                                  </span>
                                )}
                              </>
                            }
                            onProject={
                              agentFixed || conversationId
                                ? undefined
                                : () => setProjectPickerOpen(true)
                            }
                            // A phone's row keeps +, the agent, the microphone and
                            // send; these move into its `+` sheet as rows.
                            phoneRows={
                              <>
                                {!agentFixed && (
                                  <SheetRow icon={Bot} label={t("rail.agent")}>
                                    <fieldset disabled={manualCompacting} className="contents">
                                      <AgentPicker />
                                    </fieldset>
                                  </SheetRow>
                                )}
                                {offerCall && !onCall && (
                                  <SheetRow
                                    icon={PhoneCall}
                                    label={t("input.callAgent", {
                                      agent: callAgent?.name ?? t("rail.agent"),
                                    })}
                                  >
                                    <VoiceCallButton
                                      readiness={readiness}
                                      failed={readinessFailed}
                                      disabled={isProcessing || readOnly || manualCompacting}
                                      onStart={startCall}
                                      setUpHref={agentCallsHref}
                                      publishedOnly={testingDraft}
                                    />
                                  </SheetRow>
                                )}
                                <SheetRow
                                  icon={SlidersHorizontal}
                                  label={t("input.modelAndApprovals")}
                                >
                                  <fieldset disabled={manualCompacting} className="contents">
                                    <ChatControls
                                      onModelProfileChange={onModelProfileChange}
                                      onApprovalModeChange={onApprovalModeChange}
                                      agentModel={agentModel}
                                      agentCapabilities={agentCapabilities}
                                    />
                                  </fieldset>
                                </SheetRow>
                                <SheetRow icon={Gauge} label={t("input.contextUsed")}>
                                  <UsageMeter
                                    usage={lastUsage}
                                    workspace={workspace}
                                    total={conversationCost}
                                    contextWindow={contextWindow}
                                  />
                                </SheetRow>
                              </>
                            }
                            actionsSlot={
                              <span className="contents max-md:hidden">
                                {/* Wide screens only, as is the panel it opens. */}
                                <UsageMeter
                                  usage={lastUsage}
                                  workspace={workspace}
                                  total={conversationCost}
                                  contextWindow={contextWindow}
                                />
                                <fieldset disabled={manualCompacting}>
                                  <ChatControls
                                    usageSlot={
                                      <div className="text-muted-foreground flex items-center gap-2 text-xs">
                                        <span>{t("input.contextUsed")}</span>{" "}
                                        <UsageMeter
                                          usage={lastUsage}
                                          workspace={workspace}
                                          total={conversationCost}
                                          contextWindow={contextWindow}
                                        />
                                      </div>
                                    }
                                    onModelProfileChange={onModelProfileChange}
                                    onApprovalModeChange={onApprovalModeChange}
                                    agentModel={agentModel}
                                    agentCapabilities={agentCapabilities}
                                  />
                                </fieldset>
                                {/* The call stands in Send's place, as one that can
                                  start or one that says why it cannot - except
                                  during the call, when it waits here, hidden, for
                                  focus to come back to. */}
                                {onCall && callButton}
                              </span>
                            }
                            // Not during a call: the box is closed then, Send with it.
                            // Nor while readiness loads, when the button draws
                            // nothing and the slot would leave no Send at all.
                            idleSlot={callShown && !onCall ? callButton : undefined}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                  <ComposerStatus isConnected={isConnected} />
                </div>
              )}
            </div>
          </div>
          {showWorkspaceHome && !emptyState && (
            <div
              ref={setHomeHintsSlot}
              className="chat-home-hints mx-auto min-h-40 w-full max-w-4xl min-w-0 shrink-0 px-4 pb-4 sm:px-6"
            />
          )}
        </div>
        <FilePreviewDialog />
        {/* The browser shares the chat's width; a narrow chat opens it full screen. */}
        <WorkspacePanels
          teamRoom={isRoom}
          compact={compact}
          browses={browses}
          onBrowserProtected={onBrowserProtected}
          surfaces={surfaces}
          onComment={commentOnPage}
          onSend={sendMessage}
          agentId={selectedAgentId}
          hostedCapabilities={agentHostedCapabilities}
          canRun={workspaceCanRun}
          agentUsesLocalTools={agentUsesLocalTools}
          conversationId={conversationId}
          revision={turns}
          attachments={attachments}
          busy={
            isProcessing ||
            sandboxPreparing ||
            isStopping ||
            onCall ||
            !!pendingApproval ||
            !!pendingQuestions?.length
          }
          connected={isConnected}
          readOnly={
            isRoom
              ? roomReadOnly || roomRequests.isError || roomRequests.data?.can_post !== true
              : readOnly || sendDisabled
          }
          loading={Boolean(isLoadingConversation)}
        />
      </div>
      {/* Beside the transcript rather than under it: what the agent is holding is
          something you glance at while reading, and a list that pushed the input
          down would move the box you are typing in. Closed by default - it is a
          button among the composer's controls until somebody opens it, because a
          permanent third column took space from every conversation including the
          ones where the agent keeps nothing. Hidden on a narrow screen, where there
          is no room for it. */}
      {conversationId !== null && threadRootId !== null && onCloseThread && (
        <RoomThreadPanel
          key={`${activeOrgId}:${authUser?.id}:${conversationId}:${threadRootId}`}
          conversationId={conversationId}
          isRoom={isRoom}
          projectId={roomProjectId}
          roomReactionsEnabled={isRoom}
          rootId={threadRootId}
          requestedMessageId={requestedMessageId}
          messageJumpRevision={messageJumpRevision}
          messagePinActions={messagePinActions}
          onOpenPinnedMessage={onOpenPinnedMessage}
          readOnly={!isRoom || roomReadOnly}
          onClose={onCloseThread}
          onTyping={onTyping}
          actions={(scopeReadOnly) => (
            <>
              {renderActions(threadRootId, scopeReadOnly)}
              {threadNotices}
            </>
          )}
          isProcessing={isProcessing && activeThreadRootId === threadRootId}
        />
      )}
      <SourcesPanel contained={compact} conversationId={conversationId} />
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
