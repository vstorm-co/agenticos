"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { nanoid } from "nanoid";
import { useTranslations } from "next-intl";
import { useWebSocket } from "./use-websocket";
import { usePermissions } from "./use-permissions";
import { useChatStore, useAuthStore, useOrgStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { useAgentSelectionStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type {
  ActionRequest,
  AskUserAnswer,
  AskUserQuestion,
  ChatMessageFile,
  Decision,
  Delegation,
  PendingApproval,
  ReviewConfig,
  SubagentFrame,
  ToolCall,
  TurnUsage,
  WSEvent,
} from "@/types";
import type { ParkedCall, ResumedRun } from "@/types/runs";
import {
  applyDelegationFrame,
  closeOpenDelegations,
  resolveAwaitingOnResume,
  resumeFailureStatus,
} from "@/lib/delegations";
import { buildAssistantParts } from "@/lib/conversation-to-chat";
import { WS_URL } from "@/lib/constants";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/utils";
import { setUrlParam } from "@/lib/utils";
import { useConversationStore } from "@/stores";
/** A message the user typed while the agent was busy / socket offline.
 *  Held outside the chat history until the drainer ships it. */
export interface QueuedMessage {
  id: string;
  content: string;
  fileIds?: string[];
  files?: ChatMessageFile[];
}

interface UseChatOptions {
  conversationId?: string | null;
  onConversationCreated?: (conversationId: string) => void;
}

export function useChat(options: UseChatOptions = {}) {
  const { conversationId, onConversationCreated } = options;
  // `chat.unknownError` was in the catalog and read by nothing, while this hook
  // wrote the words out (#425). The `❌ Error:` in front of it is still English:
  // no catalog message holds it, so it belongs to the copy the guard has never
  // looked at rather than to this defect.
  const t = useTranslations("chat");
  const { setCurrentConversationId, currentConversationId: currentConversationIdFromStore } =
    useConversationStore();
  const {
    messages,
    addMessage,
    updateMessage,
    appendTextDelta,
    appendThinkingDelta,
    addToolCallPart,
    updateToolCallPart,
    clearMessages,
  } = useChatStore();

  const [isProcessing, setIsProcessing] = useState(false);
  // What the last turn cost, and *which conversation it was*. Replaced rather than
  // accumulated: the strip says "that turn", and a running total would be a second,
  // disagreeing answer to a question the billing pages already own.
  //
  // Keyed on the conversation because it is read after switching to another one. The
  // bare value survived the switch and the strip reported the previous thread's cost
  // under this one's input - a stale number that looked exactly like a real one.
  // Keyed, it simply is not returned, so the staleness is impossible rather than
  // cleaned up afterwards.
  const [liveUsage, setLiveUsage] = useState<{
    conversationId: string | null;
    usage: TurnUsage;
  } | null>(null);
  // Held in a ref instead of state because the WS handler reads it
  // synchronously: events arriving in the same tick (e.g. model_request_start
  // + text_delta in one server flush) need to see the just-created message id
  // without waiting for React's batched re-render. The handler never causes a
  // re-render based on this id, so state isn't needed.
  const currentMessageIdRef = useRef<string | null>(null);
  const setCurrentMessageId = useCallback((id: string | null) => {
    currentMessageIdRef.current = id;
  }, []);
  const currentGroupIdRef = useRef<string | null>(null);
  // Outbound queue: messages typed while agent is busy / socket offline. Held
  // here (not in the chat history) so the UI can surface them as cancellable
  // "pending" entries above the input. The ref is the source of truth for the
  // drainer effect; the parallel state triggers re-renders for the UI.
  const messageQueueRef = useRef<QueuedMessage[]>([]);
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const modelProfileRef = useRef<string | null>(null);
  const temperatureRef = useRef<number | null>(null);
  const thinkingEffortRef = useRef<"low" | "medium" | "high" | null>(null);
  // The agent the in-flight turn was addressed to, captured when the frame goes
  // out. A ref for the same reason `currentMessageIdRef` is one - the WS handler
  // reads it while stamping the assistant message - and captured rather than
  // read from the store at that moment, because switching agents while an answer
  // is streaming must not re-credit that answer to the newly picked agent.
  const turnAgentIdRef = useRef<string | null>(null);
  // Which conversation this hook is about: the store's, or the one passed in before
  // the store has caught up. Computed once because three places need the same answer
  // - stamping a new message, recording what a turn cost, and deciding whether that
  // cost still belongs to what is on screen - and three copies of the fallback chain
  // is three chances for them to disagree.
  const activeConversationId = currentConversationIdFromStore || conversationId || null;

  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  // Runs this hook has already put an approval panel up for, live or restored.
  // What keeps the restore effect below from re-opening a panel somebody is in
  // the middle of deciding: `sendResumeDecisions` clears the panel before the
  // steps stop reading `awaiting_approval`, which is exactly the state the
  // effect reads as "a reloaded parked run".
  const approvalOfferedForRef = useRef<Set<string>>(new Set());
  const [pendingQuestions, setPendingQuestions] = useState<AskUserQuestion[] | null>(null);
  // The delegations of the turn on screen, keyed by their own `task_id` and held
  // *outside* the assistant message on purpose.
  //
  // This is what fixes the teardown bug rather than working around it. `complete`
  // clears `currentMessageIdRef`, and a background delegation reports after the
  // parent's answer - so anything hung off the streaming message loses the last
  // thing a specialist said, silently, in exactly the case the delegation was
  // started to handle. Here the panels simply outlive `complete`, and each closes
  // on its own `subagent_complete`.
  const [delegations, setDelegations] = useState<Delegation[]>([]);

  const handleWebSocketMessage = useCallback(
    (event: MessageEvent) => {
      const wsEvent: WSEvent = JSON.parse(event.data);

      // Opens the turn's message. It used to close a previous one first, which is
      // no longer reachable and would be the wrong place for it if it were: every
      // caller now opens a message only when the turn has none, and what ends the
      // previous turn is `complete`, `final_result`, `error`, a stop, or the next
      // question - see `doSend`.
      const createNewMessage = (content: string): string => {
        const newMsgId = nanoid();
        const effectiveConversationId = activeConversationId ?? undefined;
        addMessage({
          id: newMsgId,
          role: "assistant",
          content,
          timestamp: new Date(),
          isStreaming: true,
          toolCalls: [],
          parts: content === "" ? [] : undefined,
          groupId: currentGroupIdRef.current || undefined,
          conversationId: effectiveConversationId,
          isTemporaryId: true,
          agentId: turnAgentIdRef.current ?? undefined,
        });
        setCurrentMessageId(newMsgId);
        return newMsgId;
      };

      switch (wsEvent.type) {
        case "conversation_created": {
          const { conversation_id } = wsEvent.data as { conversation_id: string };
          setCurrentConversationId(conversation_id);
          // Reflect the new ID in the URL so the page is refreshable + shareable.
          setUrlParam("id", conversation_id);
          const { updateMessagesWhere } = useChatStore.getState();
          updateMessagesWhere(
            (msg) => !msg.conversationId,
            (msg) => ({ ...msg, conversationId: conversation_id }),
          );
          onConversationCreated?.(conversation_id);
          break;
        }

        case "message_saved": {
          const { message_id } = wsEvent.data as { message_id: string };
          if (currentMessageIdRef.current) {
            updateMessage(currentMessageIdRef.current, (msg) => ({
              ...msg,
              id: message_id,
              isTemporaryId: false,
            }));
            // And point the ref at it. Everything after this - `complete` writing
            // what the turn cost, an `error` marking the message failed - addresses
            // the message through this ref, and a ref still holding the temporary id
            // addresses a message that no longer exists. The cost was being written
            // to nothing, so it appeared only after a reload fetched it from the row.
            setCurrentMessageId(message_id);
          } else {
            // This handles cases where currentMessageId was already cleared
            const messages = useChatStore.getState().messages;
            const lastTemp = [...messages]
              .reverse()
              .find((msg) => msg.role === "assistant" && !!msg.isTemporaryId);
            if (lastTemp) {
              updateMessage(lastTemp.id, (msg) => ({
                ...msg,
                id: message_id,
                isTemporaryId: false,
              }));
            }
          }
          break;
        }

        case "model_request_start": {
          // One bubble per turn, not per model request.
          //
          // A multi-step turn makes a request per tool round, and opening a message
          // on each one split a single answer across several: a turn that drew three
          // charts arrived as four bubbles, each with its own avatar and its own
          // timestamp. The tool steps were scattered one per message, so `runsOf`
          // had nothing consecutive to gather onto a rail and the run never reached
          // the two steps `AgentSteps` needs to say "Done".
          //
          // It also produced a turn the backend could not match. One turn is one
          // `messages` row, so `message_saved` renamed one bubble to the real id and
          // the rest kept a temporary one forever - no cost, no rating, and they
          // disappeared on reload when the single stored row replaced all four.
          // That is the difference between the live transcript and the reloaded one.
          //
          // A turn ends at `complete`, which clears the ref. So this opens a message
          // when a turn has none and appends to it for every round after the first,
          // exactly as `thinking_delta` below already did.
          if (!currentMessageIdRef.current) {
            createNewMessage("");
          }
          break;
        }

        case "text_delta": {
          // Append to the ordered parts timeline (extends the trailing
          // text part or starts a new one after a thinking/tool part).
          if (currentMessageIdRef.current) {
            const content = (wsEvent.data as { index: number; content: string }).content;
            appendTextDelta(currentMessageIdRef.current, content);
          }
          break;
        }

        case "thinking_delta": {
          // Reasoning trace from extended-thinking models - its own
          // ordered part so it renders before the tools/text that follow.
          if (!currentMessageIdRef.current) {
            createNewMessage("");
          }
          if (currentMessageIdRef.current) {
            const content = (wsEvent.data as { index: number; content: string }).content;
            appendThinkingDelta(currentMessageIdRef.current, content);
          }
          break;
        }

        case "tool_call": {
          if (currentMessageIdRef.current) {
            const { tool_name, args, tool_call_id } = wsEvent.data as {
              tool_name: string;
              args: Record<string, unknown>;
              tool_call_id: string;
            };
            const toolCall: ToolCall = {
              id: tool_call_id,
              name: tool_name,
              args,
              status: "running",
            };
            addToolCallPart(currentMessageIdRef.current, toolCall);
          }
          break;
        }

        case "tool_result": {
          if (currentMessageIdRef.current) {
            const { tool_call_id, content } = wsEvent.data as {
              tool_call_id: string;
              content: string;
            };
            updateToolCallPart(currentMessageIdRef.current, tool_call_id, {
              result: content,
              status: "completed",
            });
          }
          break;
        }

        case "final_result": {
          if (currentMessageIdRef.current) {
            const { output } = wsEvent.data as { output: string };
            // If the model returned text only via final_result (no streamed
            // text_delta), append it as the trailing text part.
            const fr = useChatStore
              .getState()
              .messages.find((m) => m.id === currentMessageIdRef.current);
            if (output && fr && !fr.content) {
              appendTextDelta(currentMessageIdRef.current, output);
            }
            updateMessage(currentMessageIdRef.current, (msg) => ({
              ...msg,
              isStreaming: false,
            }));
          }
          setIsProcessing(false);
          // Don't clear currentMessageId yet - we need it for message_saved event
          currentGroupIdRef.current = null;
          break;
        }

        case "subagent_start":
        case "subagent_text_delta":
        case "subagent_thinking_delta":
        case "subagent_tool_call":
        case "subagent_tool_result":
        case "subagent_awaiting_approval":
        case "subagent_complete": {
          // One branch for every frame: the envelope's `type` is the frame's own
          // `kind` (see `AgentSession._subagent_event`), so the payload narrows
          // itself and the cases share one reducer instead of one copy each of
          // "find the task, change one field".
          setDelegations((current) => applyDelegationFrame(current, wsEvent.data as SubagentFrame));
          break;
        }

        case "error": {
          if (currentMessageIdRef.current) {
            const id = currentMessageIdRef.current;
            const { message } = wsEvent.data as { message: string };
            // Into the timeline rather than onto `content` directly: the store's
            // append keeps the two in step, and it starts a parts list for a
            // message that has none - which is what a replayed turn looks like.
            appendTextDelta(
              id,
              `\n\n${t("streamError", { message: message || t("unknownError") })}`,
            );
            updateMessage(id, (msg) => ({ ...msg, isStreaming: false }));
          }
          setIsProcessing(false);
          // The turn is over and no `subagent_complete` is coming for whatever was
          // still running. A panel left open past that spins forever - the state a
          // parked tool call used to sit in.
          setDelegations(closeOpenDelegations);
          break;
        }

        case "tool_approval_required": {
          // The run stopped on a gated tool call. The `approvals` queue has the
          // same rows and the email points at them; this is the shortcut for
          // whoever is already looking at the tab.
          const { action_requests, review_configs, run_id } = wsEvent.data as {
            action_requests: ActionRequest[];
            review_configs: ReviewConfig[];
            run_id: string;
          };
          approvalOfferedForRef.current.add(run_id);
          setPendingApproval({
            actionRequests: action_requests,
            reviewConfigs: review_configs,
            runId: run_id,
            // Captured now, because `complete` follows this frame and clears it.
            messageId: currentMessageIdRef.current,
          });
          // Resolve the cards rather than leaving them spinning. A parked call
          // produces no `tool_result` until somebody decides, so "running" is a
          // state it can sit in forever.
          if (currentMessageIdRef.current) {
            const id = currentMessageIdRef.current;
            for (const request of action_requests) {
              updateToolCallPart(id, request.tool_call_id, { status: "awaiting_approval" });
            }
            // The only frame that names the run this turn is, and the turn that
            // parks is the only one that needs it: what somebody approves is
            // written as further segments of this run, and `MessageList` draws
            // them as one turn by matching exactly this id. A reloaded
            // conversation gets it from the stored message instead.
            updateMessage(id, (msg) => ({ ...msg, runId: run_id }));
          }
          break;
        }

        case "ask_user": {
          const { questions } = wsEvent.data as {
            questions: { question: string; options: string[]; allow_custom: boolean }[];
          };
          setPendingQuestions(
            (questions ?? []).map((q) => ({
              question: q.question,
              options: q.options ?? [],
              allowCustom: q.allow_custom,
            })),
          );
          break;
        }

        case "complete": {
          setIsProcessing(false);
          // `wsEvent.data`, not `event.data`: the latter is the raw JSON string
          // this handler parsed, and reading a field off it silently yields
          // `undefined` - which looked exactly like a turn nobody measured.
          //
          // Absent is left absent, rather than clearing a number the previous
          // turn legitimately reported: the strip would flicker to nothing.
          {
            const { usage, stopped } = wsEvent.data as {
              usage?: TurnUsage | null;
              stopped?: boolean;
            };
            // **`complete` is not the cue to tear a delegation down.** It says the
            // *parent* is finished, and a background delegation reports after that -
            // so the panels are left exactly as they are and each closes on its own
            // `subagent_complete`. The one exception is the cancelled path, which
            // sends `stopped` (`AgentSession._run_turn`): nothing more is coming for
            // a run that was cancelled, so whatever was open is closed here. Until
            // now the frontend never read this field at all.
            if (stopped) setDelegations(closeOpenDelegations);
            if (usage) {
              setLiveUsage({
                // From the store rather than the render closure: a turn that created
                // the conversation learns its id from `conversation_created` in this
                // same handler, and the closure still holds `null`.
                conversationId:
                  useConversationStore.getState().currentConversationId ?? activeConversationId,
                usage,
              });
              // Also on the message itself. The strip under the input only ever
              // describes the last turn, so in a long conversation there is no
              // way to see which answer was the expensive one - and "the one
              // that read four documents" is exactly the question somebody
              // watching a budget is asking.
              if (currentMessageIdRef.current)
                updateMessage(currentMessageIdRef.current, (msg) => ({ ...msg, usage }));
            }
          }
          // Clear currentMessageId after complete (message_saved should have handled ID mapping)
          setCurrentMessageId(null);
          // The turn just debited credits server-side - nudge any mounted
          // billing view to refetch so the user doesn't see stale numbers.
          if (typeof window !== "undefined") {
            window.dispatchEvent(new Event("billing:refresh"));
          }
          break;
        }
      }
    },
    [
      // currentMessageId is read via currentMessageIdRef inside the handler,
      // so we deliberately omit it here - that's the whole point of the ref.
      addMessage,
      updateMessage,
      appendTextDelta,
      appendThinkingDelta,
      addToolCallPart,
      updateToolCallPart,
      setCurrentConversationId,
      setCurrentMessageId,
      onConversationCreated,
      activeConversationId,
      t,
    ],
  );

  // Access token lives in memory only (populated by login/refresh responses).
  // It is sent to the WS via Sec-WebSocket-Protocol rather than a URL query
  // string so it does not end up in access logs or Referer headers.
  const accessToken = useAuthStore((state) => state.accessToken);

  // The active org travels in the query string because a browser cannot set
  // headers on a WebSocket handshake (the HTTP API uses X-Organization-Id).
  // An org id is not a secret - the server verifies membership and closes the
  // socket otherwise. Switching orgs changes the URL, which reconnects the
  // socket, so a conversation never continues under the wrong organization.
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const tenantId = useTenantId();
  const wsUrl = useMemo(() => {
    const base = `${WS_URL}/api/v1/ws/agent`;
    return activeOrgId ? `${base}?organization_id=${encodeURIComponent(activeOrgId)}` : base;
  }, [activeOrgId]);
  const wsProtocols = useMemo(
    () => (accessToken ? [`access_token.${accessToken}`, "chat"] : undefined),
    [accessToken],
  );

  // Guards against firing a token refresh on every backoff attempt - one
  // in-flight /me at a time is enough to recover a stale access token.
  const refreshingRef = useRef(false);

  const { isConnected, connect, disconnect, sendMessage } = useWebSocket({
    url: wsUrl,
    protocols: wsProtocols,
    onMessage: handleWebSocketMessage,
    // A dropped socket is often a stale access token. Refresh it so the
    // auto-reconnect (and the token-gated connect effect) uses a fresh one.
    // The hook only calls this on genuine drops (not deliberate disconnects),
    // and the ref keeps concurrent reconnect attempts from stampeding /me.
    onClose: () => {
      if (refreshingRef.current) return;
      refreshingRef.current = true;
      void (async () => {
        try {
          const res = await fetch("/api/auth/me");
          if (res.ok) {
            const data = (await res.json()) as { access_token?: string };
            if (data.access_token) useAuthStore.getState().setAccessToken(data.access_token);
          }
        } catch {
          // ignore - backoff reconnect will retry
        } finally {
          refreshingRef.current = false;
        }
      })();
    },
  });

  // Own the socket lifecycle here: only open once the in-memory access token is
  // available (the WS authenticates via Sec-WebSocket-Protocol). Connecting
  // before the token loads used to open a token-less socket that the server
  // rejects, triggering a reconnect storm + console errors on every page load.
  // When the token refreshes, `connect` changes identity → reconnect with it.
  useEffect(() => {
    if (!accessToken) return;
    connect();
    return () => disconnect();
  }, [accessToken, connect, disconnect]);

  const doSend = useCallback(
    (content: string, fileIds?: string[], files?: ChatMessageFile[]) => {
      // The previous turn's panels belong to the previous turn. Cleared here rather
      // than on `complete` so they survive it - which is the whole point - and a
      // late frame from a background delegation of the turn before is dropped by
      // `applyDelegationFrame` rather than opening a nameless panel.
      setDelegations([]);
      // A new question ends whatever the agent was saying, and it is the only
      // boundary that always holds. `complete` clears this on every ordinary
      // ending, but a socket that dropped mid-answer sends no `complete` at all -
      // and now that a turn is one message rather than one per model request, a
      // ref still pointing at the abandoned turn would have the next answer
      // appended to it. The half-written one also stops rendering its cursor,
      // which nothing else was going to do for it.
      if (currentMessageIdRef.current) {
        updateMessage(currentMessageIdRef.current, (msg) => ({ ...msg, isStreaming: false }));
        setCurrentMessageId(null);
      }
      const userMessageId = nanoid();
      addMessage({
        id: userMessageId,
        role: "user",
        content,
        timestamp: new Date(),
        conversationId: conversationId || undefined,
        fileIds,
        files,
      });
      setIsProcessing(true);
      const payload: Record<string, unknown> = {
        message: content,
        conversation_id: conversationId || null,
      };
      if (fileIds?.length) payload.file_ids = fileIds;
      // A model profile from the vault - the agent runs on it for this turn
      // instead of the model its spec names, and the run records which.
      if (modelProfileRef.current) payload.model_profile_id = modelProfileRef.current;
      if (temperatureRef.current !== null) payload.temperature = temperatureRef.current;
      if (thinkingEffortRef.current !== null) payload.thinking_effort = thinkingEffortRef.current;
      // Read at send time, not captured in the closure: the queue drainer calls
      // this up to a turn later, and the frame must name whatever is selected
      // when it actually leaves. The picker keeps a published agent selected
      // whenever the organization has one, so a frame without an `agent_id`
      // only happens when nothing is published at all - and the backend
      // refuses it with the message that says to publish one.
      const agentId = useAgentSelectionStore.getState().selectedAgentId;
      if (agentId) payload.agent_id = agentId;
      turnAgentIdRef.current = agentId;
      sendMessage(payload);
    },
    [addMessage, updateMessage, setCurrentMessageId, sendMessage, conversationId],
  );

  const sendChatMessage = useCallback(
    (content: string, fileIds?: string[], files?: ChatMessageFile[]) => {
      // Queue when the agent is busy OR the socket is offline. The queue is
      // surfaced above the input as pending entries the user can cancel; the
      // drainer effect below pops the head as soon as the agent is idle.
      if (isProcessing || !isConnected) {
        const id = nanoid();
        messageQueueRef.current.push({ id, content, fileIds, files });
        setQueuedMessages([...messageQueueRef.current]);
        return;
      }
      doSend(content, fileIds, files);
    },
    [isProcessing, isConnected, doSend],
  );

  const cancelQueued = useCallback((id: string) => {
    messageQueueRef.current = messageQueueRef.current.filter((q) => q.id !== id);
    setQueuedMessages([...messageQueueRef.current]);
  }, []);

  const clearQueued = useCallback(() => {
    messageQueueRef.current = [];
    setQueuedMessages([]);
  }, []);

  // A queued message belongs to the organization it was typed in. It sits in
  // this hook's own state until the socket comes back, so neither dropping the
  // query cache nor resetting the stores reaches it - switching organization
  // with the connection down left the message on screen and sent it as the new
  // tenant once their socket connected. An approval or a question waiting on
  // the previous organization's run is the same thing, one turn later.
  //
  // A layout effect rather than a write during render, because the queue lives
  // in a ref as well as in state and a ref may not be written while rendering.
  // Before the paint either way, so nothing of the previous tenant is shown.
  const queueBelongsTo = useRef(tenantId);
  useLayoutEffect(() => {
    if (queueBelongsTo.current === tenantId) return;
    queueBelongsTo.current = tenantId;
    clearQueued();
    setPendingApproval(null);
    setPendingQuestions(null);
    approvalOfferedForRef.current = new Set();
    // A delegation belongs to a run in one organization, and to one conversation
    // inside it - the effect below is the other half of that sentence. Left on
    // screen it would show the previous tenant's specialist names and prompts to
    // the new one.
    setDelegations([]);
  }, [tenantId, clearQueued]);

  // The other half: a delegation, an approval and a question all belong to a run in
  // *this* conversation, and all three are drawn over whatever transcript is on
  // screen. Switching to another conversation clears the messages and the queue and
  // used to leave them, so the previous thread's specialist names, prompts, streamed
  // answers and costs were drawn under the new one - until the next message, which is
  // the only other thing that clears them. Cleared here rather than on `complete`,
  // which the panels deliberately outlive: a background delegation reports after the
  // parent answered.
  //
  // The approval panel is the worst of the three, because it is not only stale but
  // actionable: an *approve* under another agent's transcript decides a call the
  // person is no longer looking at, and its `messageId` points into a conversation
  // whose messages are gone, so the step it settles is settled nowhere. It is not
  // lost by clearing it - the approvals queue holds the same rows, and reopening the
  // conversation is not what the decision needs. A question is cleared for the same
  // reason in reverse: answering it here would put words typed under one transcript
  // into a turn belonging to another.
  //
  // Not keyed by conversation, deliberately. A turn that creates its conversation
  // learns the id from `conversation_created` mid-stream, so the key would move under
  // panels that are already open and `applyDelegationFrame` would drop every frame
  // after it as naming a task it holds no panel for - a silent loss of the last thing
  // a specialist said, which is the failure this whole design exists to avoid. The
  // delegation and question panels are live state that no reload restores, so keeping
  // them for a conversation somebody may return to would also disagree with what that
  // reload shows; the approval panel is the one the restore effect below rebuilds
  // from the rows, which is why its guard is reset here - coming back to a still
  // parked conversation must offer the decision again.
  //
  // A layout effect for the reason the one above is one: before the paint, so no
  // frame of the previous conversation's panels is shown under this one's transcript.
  const panelsBelongTo = useRef(activeConversationId);
  useLayoutEffect(() => {
    const previous = panelsBelongTo.current;
    panelsBelongTo.current = activeConversationId;
    // `previous === null` is the turn that just created its conversation being told
    // its id, not a different conversation being opened - clearing there would throw
    // away the panels of the turn still streaming, and a first turn that parks on an
    // approval is exactly that turn.
    if (previous === activeConversationId || previous === null) return;
    setDelegations([]);
    setPendingApproval(null);
    setPendingQuestions(null);
    approvalOfferedForRef.current = new Set();
  }, [activeConversationId]);

  // The caller's permissions, for the restore effect below: rebuilding the
  // approval panel reads an endpoint gated on `approvals:decide`, so a caller
  // without it is not asked to 403 on every reopened conversation.
  const { can } = usePermissions();
  const canDecide = can(Perm.approvalsDecide);

  // The other direction of `tool_approval_required`: that frame exists only for
  // whoever was watching when the run parked. A reloaded conversation carries
  // the parked state on its steps - the transcript stores them
  // `awaiting_approval` - but the panel with the decision was gone, so the only
  // way to finish the run was the approvals queue on another page (#601). This
  // asks the backend what the run is still waiting on and puts the panel back.
  //
  // Guarded per run so it never reopens a panel mid-decision:
  // `sendResumeDecisions` clears the panel before the steps stop reading
  // `awaiting_approval`, which is exactly the state this effect would otherwise
  // read as a reloaded parked run. Empty rows are left alone - a run decided
  // elsewhere but not yet resumed has nothing left to offer - and a fetch that
  // failed is left alone too: the approvals queue holds the same rows, and an
  // error toast over a transcript somebody is reading buys nothing.
  useEffect(() => {
    if (pendingApproval !== null || isProcessing || !canDecide) return;
    const parkedMessage = [...messages]
      .reverse()
      .find(
        (message) =>
          message.role === "assistant" &&
          (message.toolCalls ?? []).some((call) => call.status === "awaiting_approval"),
      );
    // No `runId` is a turn stored before runs were stamped on messages: its
    // step still says it is waiting, but there is no run to ask about.
    if (parkedMessage === undefined || parkedMessage.runId === undefined) return;
    const runId = parkedMessage.runId;
    if (approvalOfferedForRef.current.has(runId)) return;
    approvalOfferedForRef.current.add(runId);
    const conversation = activeConversationId;
    void (async () => {
      try {
        const parked = await apiClient.get<ParkedCall[]>(`/runs/${runId}/parked`);
        // An answer that lands after the reader has moved on is dropped: a
        // panel drawn under another conversation's transcript is the stale,
        // actionable state the conversation-switch effect above exists to
        // prevent, and this fetch can resolve on the far side of that switch.
        if (parked.length === 0 || panelsBelongTo.current !== conversation) return;
        setPendingApproval({
          actionRequests: parked.map((call) => ({
            id: call.id,
            tool_call_id: call.tool_call_id ?? "",
            tool_name: call.tool_name,
            args: call.tool_args,
          })),
          // The same shape the live frame carries: editing a parked call is not
          // offered, because the arguments were recorded on the row being decided.
          reviewConfigs: parked.map((call) => ({ tool_name: call.tool_name, allow_edit: false })),
          runId,
          messageId: parkedMessage.id,
        });
      } catch {
        // Deliberately quiet - see above.
      }
    })();
  }, [messages, pendingApproval, isProcessing, canDecide, activeConversationId]);

  /** Record one decision on the `approvals` row it belongs to. */
  const decideApproval = useCallback(
    (approvalId: string, approved: boolean) =>
      apiClient.post(`/approvals/${approvalId}`, { approved }),
    [],
  );

  /** Continue a run whose parked calls have all been decided.
   *
   * Answers with the resumed turn, not an acknowledgement: `resume_run` executes
   * the agent and returns its output, so the continuation is in this response and
   * nothing needs to be waited for. */
  const resumeRun = useCallback(
    (runId: string) => apiClient.post<ResumedRun>(`/runs/${runId}/resume`),
    [],
  );

  const sendResumeDecisions = useCallback(
    async (decisions: Decision[]) => {
      // Read from state and listed in the deps below. A ref would avoid
      // rebuilding this callback, but it cannot be written during render - and
      // rebuilding it is harmless: it is only ever passed down as a prop.
      const parked = pendingApproval;
      setPendingApproval(null);

      if (parked === null) return;

      // The same endpoints the approvals queue uses. This used to send a
      // `resume` frame over the WebSocket, which the server silently ignores -
      // so the panel reported "3 approved" and nothing whatsoever happened.
      // Recording the decision on the row is also what keeps the queue, the
      // audit entry and the email honest about what was decided.
      try {
        for (const [index, request] of parked.actionRequests.entries()) {
          const decision = decisions[index];
          if (decision === undefined) continue;
          await decideApproval(request.id, decision.type === "approve");
          // `parked.messageId`, never the live ref: the turn ended at `complete`
          // the moment the run parked, so the ref is null by now and every one of
          // these updates was being skipped - which is why the step stayed at
          // "waiting for approval" after an approval that had actually worked.
          if (parked.messageId !== null) {
            updateToolCallPart(parked.messageId, request.tool_call_id, {
              status: decision.type === "approve" ? "running" : "error",
              result: decision.type === "approve" ? undefined : "Refused",
            });
          }
        }
        // Once, after all of them: the run continues when nothing is left
        // parked, and resuming per decision would start it while calls it has
        // not been told about are still waiting.
        const resumed = await resumeRun(parked.runId);
        // Approved calls are marked finished here rather than left `running`. The
        // resume ran over HTTP, so their `tool_result` frames went to that response
        // and not to this socket - a step set running when the decision was recorded
        // would spin for the rest of the session waiting for one that cannot arrive.
        //
        // With what they returned, which arrives in that same response. The call a
        // person reviewed was made by the execution that parked, so the resume
        // produces only its return - it belongs to this step rather than to a new
        // one, and without it the one call somebody deliberately looked at was the
        // one that opened onto nothing.
        const settled = new Map((resumed.settled ?? []).map((call) => [call.tool_call_id, call]));
        if (parked.messageId !== null) {
          const id = parked.messageId;
          for (const [index, request] of parked.actionRequests.entries()) {
            if (decisions[index]?.type === "approve") {
              updateToolCallPart(id, request.tool_call_id, {
                status: "completed",
                result: settled.get(request.tool_call_id)?.result,
              });
            }
          }
        }
        // Close whatever delegate parked here. The resume ran over HTTP and its
        // frames went nowhere this socket can see, so a delegation panel left
        // `awaiting_approval` never got its `subagent_complete` and would read
        // "waiting for approval" forever - the answer above it, the panel below it
        // frozen. The resumed run's own status is the outcome those panels take;
        // a resume that parks again leaves them waiting. See `resolveAwaitingOnResume`.
        setDelegations((current) => resolveAwaitingOnResume(current, resumed.status));
        // A continuation can stop again: the agent reaches a second gated call and
        // parks on it. Nothing announces that here - the resume ran over HTTP, so
        // no `tool_approval_required` frame arrives - so the panel used to close on
        // a run that was still blocked, and the only way to finish it was the
        // approvals queue on another page.
        const parkedAgain = resumed.parked ?? [];
        const parkedAgainIds = new Set(parkedAgain.map((call) => call.tool_call_id));
        // What the continuation did, as steps. Nothing else carries them: the
        // agent ran inside the resume request, so its `tool_call` frames went to
        // that response and not to this socket. Drawing only the answer left the
        // second half of the turn missing - approve a command and nothing appears
        // to run, then a second approval arrives for a step nobody has seen, and
        // the transcript ends with a reply that accounts for neither.
        //
        // The calls just decided are dropped: their steps are already on screen in
        // the message that parked, and were marked finished above.
        const decided = new Set(parked.actionRequests.map((request) => request.tool_call_id));
        const steps: ToolCall[] = (resumed.steps ?? [])
          .filter((step) => !decided.has(step.tool_call_id))
          .map((step) => ({
            id: step.tool_call_id,
            name: step.tool_name,
            args: step.args,
            result: step.result ?? undefined,
            // A call with a pending approval against it has not run and never
            // will until somebody decides - the state the panel below is asking
            // about, not a spinner that resolves.
            status: parkedAgainIds.has(step.tool_call_id) ? "awaiting_approval" : "completed",
          }));
        // **The answer is shown, not discarded.** `resume_run` runs the agent and
        // returns what it said, but it returns it *here* - over HTTP, to the caller
        // - and not over the socket this conversation is streaming. So the reply
        // used to exist and be thrown away: the panel vanished, a toast said the
        // run was continuing, and the chat then sat unchanged forever. Reloading
        // the page showed the finished turn, which is how this looked like an
        // approval that did nothing.
        //
        // One message for the whole continuation, steps then answer, which is the
        // order they happened in and the order a reloaded conversation replays
        // them in. Nothing is added for a continuation that neither called
        // anything nor said anything - a resume into a refusal has both empty.
        const continuation = nanoid();
        if (steps.length > 0 || resumed.output) {
          // A finished assistant message, which is also what makes the file panel
          // re-read: `turns` counts those, and a resumed call is usually the one
          // that was gated - an `execute`, a write - so the workspace beside the
          // transcript is exactly what changed.
          addMessage({
            id: continuation,
            role: "assistant",
            content: resumed.output,
            toolCalls: steps,
            parts: buildAssistantParts(steps, resumed.output, continuation),
            timestamp: new Date(),
            conversationId: conversationId || undefined,
            // The same run as the turn that parked, which is what draws the two as
            // one turn instead of as two agents answering the same question.
            runId: parked.runId,
            // What the run has cost *in total*, which is what the row carries -
            // the continuation's own share would read as the price of the whole
            // answer. Drawn once, under the end of the turn; the figure the
            // parked segment recorded is superseded rather than added to.
            usage: {
              input_tokens: resumed.input_tokens,
              output_tokens: resumed.output_tokens,
              cost_usd: Number(resumed.cost_usd),
              // A resume is not told where the run stands against its budget, and
              // an invented percentage is worse than a bar that is not drawn.
              budget_percent: null,
              agent_budget_percent: null,
              sandbox: null,
            },
            // The agent that was answering when the run parked. Without it the
            // continuation rendered under the generic robot with no name beside it,
            // so the second half of one turn looked like a different agent had
            // written it - the same turn, two faces.
            agentId: turnAgentIdRef.current ?? undefined,
          });
        }
        if (parkedAgain.length > 0) {
          setPendingApproval({
            actionRequests: parkedAgain.map((call) => ({
              id: call.id,
              tool_call_id: call.tool_call_id ?? "",
              tool_name: call.tool_name,
              args: call.tool_args,
            })),
            reviewConfigs: parkedAgain.map((call) => ({
              tool_name: call.tool_name,
              allow_edit: false,
            })),
            runId: parked.runId,
            // The message the new step was just drawn in, not the one that parked
            // first. Deciding writes the outcome back onto the step it belongs to,
            // and pointing at the older message meant every decision after the
            // first landed on a tool call that message does not contain.
            messageId: continuation,
          });
        }
      } catch (error) {
        const terminalStatus = resumeFailureStatus(error);
        if (terminalStatus !== null) {
          // The continuation itself failed. The backend recorded the run terminal
          // and committed it before re-raising, so the run is no longer parked and
          // this resume cannot be retried - restoring the approval would only offer
          // a button that 400s. Close the delegate panels to that outcome instead,
          // the closing the resume answer would have carried had it returned, and
          // still surface the failure (agenticos#262).
          setDelegations((current) => resolveAwaitingOnResume(current, terminalStatus));
          toast.error(getErrorMessage(error));
          return;
        }
        // The decision failed to record, or the resume could not be built (a secret
        // deleted since the park): the run is still parked, so put the approval back
        // rather than swallowing it - a panel that vanished is a person believing
        // they unblocked it, and the retry can now succeed.
        setPendingApproval(parked);
        toast.error(getErrorMessage(error));
      }
    },
    [pendingApproval, updateToolCallPart, decideApproval, resumeRun, addMessage, conversationId],
  );

  const sendAskUserResponses = useCallback(
    (answers: AskUserAnswer[]) => {
      if (!isConnected) return;
      setPendingQuestions(null);
      sendMessage({ type: "ask_user_response", answers });
    },
    [isConnected, sendMessage],
  );

  const stopGeneration = useCallback(() => {
    sendMessage({ type: "stop" });
    if (currentMessageIdRef.current) {
      updateMessage(currentMessageIdRef.current, (msg) => ({ ...msg, isStreaming: false }));
    }
    setCurrentMessageId(null);
    currentGroupIdRef.current = null;
    setIsProcessing(false);
    setPendingApproval(null);
    setPendingQuestions(null);
    // Optimistic, and it has to be: the `stop` frame cancels the turn task and the
    // server's own `complete` carries `stopped`, but nothing guarantees it arrives -
    // the socket may be what went away. Closing here means the panels never outlive
    // the run that fed them.
    setDelegations(closeOpenDelegations);
  }, [sendMessage, updateMessage, setCurrentMessageId]);

  // Drain message queue when processing finishes AND we're back online.
  // Re-runs on either flip so a reconnect after offline → drains; a busy turn
  // ending → drains the next one.
  useEffect(() => {
    if (isConnected && !isProcessing && messageQueueRef.current.length > 0) {
      const next = messageQueueRef.current.shift();
      setQueuedMessages([...messageQueueRef.current]);
      if (next) {
        // Small debounce so the UI shows the queue clearing visibly before
        // the next user bubble lands; also avoids racing the WS state flip.
        setTimeout(() => doSend(next.content, next.fileIds, next.files), 100);
      }
    }
  }, [isProcessing, isConnected, doSend]);

  // The live turn's cost, and only while it still belongs to the conversation on
  // screen. A value from the thread somebody just left is not a value about this one.
  const onThisConversation =
    liveUsage !== null && liveUsage.conversationId === activeConversationId;

  return {
    messages,
    isConnected,
    isProcessing,
    lastUsage: onThisConversation ? liveUsage.usage : null,
    /** The turn's delegations, in the order they started. See `DelegationPanels`. */
    delegations,
    connect,
    disconnect,
    sendMessage: sendChatMessage,
    stopGeneration,
    clearMessages,
    queuedMessages,
    cancelQueued,
    clearQueued,
    setModelProfile: (profileId: string | null) => {
      modelProfileRef.current = profileId;
    },
    setTemperature: (temperature: number | null) => {
      temperatureRef.current = temperature;
    },
    setThinkingEffort: (effort: "low" | "medium" | "high" | null) => {
      thinkingEffortRef.current = effort;
    },
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
  };
}
