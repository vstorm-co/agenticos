"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { nanoid } from "nanoid";
import { useWebSocket } from "./use-websocket";
import { useChatStore, useAuthStore, useOrgStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { useAgentSelectionStore } from "@/stores";
import type {
  ActionRequest,
  AskUserAnswer,
  AskUserQuestion,
  ChatMessageFile,
  Decision,
  PendingApproval,
  ReviewConfig,
  ToolCall,
  TurnUsage,
  WSEvent,
} from "@/types";
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
  // What the last turn cost. Replaced rather than accumulated: the strip says
  // "that turn", and a running total would be a second, disagreeing answer to a
  // question the billing pages already own.
  const [lastUsage, setLastUsage] = useState<TurnUsage | null>(null);
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
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [pendingQuestions, setPendingQuestions] = useState<AskUserQuestion[] | null>(null);

  const handleWebSocketMessage = useCallback(
    (event: MessageEvent) => {
      const wsEvent: WSEvent = JSON.parse(event.data);

      const createNewMessage = (content: string): string => {
        if (currentMessageIdRef.current) {
          updateMessage(currentMessageIdRef.current, (msg) => ({
            ...msg,
            isStreaming: false,
          }));
        }

        const newMsgId = nanoid();
        // Use current conversationId from store to avoid closure issues
        const effectiveConversationId =
          currentConversationIdFromStore || conversationId || undefined;
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
          // Handle new conversation created by backend
          const { conversation_id } = wsEvent.data as { conversation_id: string };
          setCurrentConversationId(conversation_id);
          // Reflect the new ID in the URL so the page is refreshable + shareable.
          setUrlParam("id", conversation_id);
          // Update all messages that don't have a conversationId yet
          const { updateMessagesWhere } = useChatStore.getState();
          updateMessagesWhere(
            (msg) => !msg.conversationId,
            (msg) => ({ ...msg, conversationId: conversation_id }),
          );
          onConversationCreated?.(conversation_id);
          break;
        }

        case "message_saved": {
          // Assistant message was saved to database, update local ID to real database ID
          const { message_id } = wsEvent.data as { message_id: string };
          if (currentMessageIdRef.current) {
            // Update the current streaming message's ID to the real database ID
            updateMessage(currentMessageIdRef.current, (msg) => ({
              ...msg,
              id: message_id,
              isTemporaryId: false,
            }));
          } else {
            // Fallback: find the last assistant message with a temp ID
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
          // PydanticAI/LangChain - create message immediately
          createNewMessage("");
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

        case "llm_started":
        case "llm_completed": {
          // LLM lifecycle events - optionally show status
          break;
        }

        case "tool_call": {
          // Add tool call to current message
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
          // Update tool call with result
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
          // Finalize message
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

        case "error": {
          // Handle error
          if (currentMessageIdRef.current) {
            const id = currentMessageIdRef.current;
            const { message } = wsEvent.data as { message: string };
            // Into the timeline rather than onto `content` directly: the store's
            // append keeps the two in step, and it starts a parts list for a
            // message that has none - which is what a replayed turn looks like.
            appendTextDelta(id, `\n\n❌ Error: ${message || "Unknown error"}`);
            updateMessage(id, (msg) => ({ ...msg, isStreaming: false }));
          }
          setIsProcessing(false);
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
          setPendingApproval({
            actionRequests: action_requests,
            reviewConfigs: review_configs,
            runId: run_id,
          });
          // Resolve the cards rather than leaving them spinning. A parked call
          // produces no `tool_result` until somebody decides, so "running" is a
          // state it can sit in forever.
          if (currentMessageIdRef.current) {
            const id = currentMessageIdRef.current;
            for (const request of action_requests) {
              updateToolCallPart(id, request.tool_call_id, { status: "awaiting_approval" });
            }
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
            const { usage } = wsEvent.data as { usage?: TurnUsage | null };
            if (usage) {
              setLastUsage(usage);
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
      currentConversationIdFromStore,
      conversationId,
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
    [addMessage, sendMessage, conversationId],
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
  }, [tenantId, clearQueued]);

  /** Record one decision on the `approvals` row it belongs to. */
  const decideApproval = useCallback(
    (approvalId: string, approved: boolean) =>
      apiClient.post(`/approvals/${approvalId}`, { approved }),
    [],
  );

  /** Continue a run whose parked calls have all been decided. */
  const resumeRun = useCallback((runId: string) => apiClient.post(`/runs/${runId}/resume`), []);

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
          if (currentMessageIdRef.current) {
            updateToolCallPart(currentMessageIdRef.current, request.tool_call_id, {
              status: decision.type === "approve" ? "running" : "error",
              result: decision.type === "approve" ? undefined : "Refused",
            });
          }
        }
        // Once, after all of them: the run continues when nothing is left
        // parked, and resuming per decision would start it while calls it has
        // not been told about are still waiting.
        await resumeRun(parked.runId);
        toast.success("Continuing the run");
      } catch (error) {
        // Put it back rather than swallowing it. A decision that failed to
        // record is a run still parked, and a panel that vanished is a person
        // believing they unblocked it.
        setPendingApproval(parked);
        toast.error(getErrorMessage(error));
      }
    },
    [pendingApproval, updateToolCallPart, decideApproval, resumeRun],
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

  return {
    messages,
    isConnected,
    isProcessing,
    lastUsage,
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
    // Human-in-the-Loop support
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
  };
}
