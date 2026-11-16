"use client";

import { retainNextSteps } from "@/lib/next-step-events";

import { create, createStore, type StateCreator } from "zustand";

import { scopedStore } from "./chat-scope-context";
import type { TranscriptIdentity } from "./conversation-store";
import { clientId } from "@/lib/ids";
import type { ChatMessage, MessagePart, MessageReply, ToolCall } from "@/types";
import type { RoomDraft } from "@/types/room";

export const EMPTY_ROOM_DRAFT: RoomDraft = {
  content: "",
  agentId: null,
  reply: null,
  attempt: null,
  sending: false,
  error: null,
};

/** A tab's correlation id is meaningful only for its author in this conversation. */
function promptKey(message: ChatMessage): string | undefined {
  if (
    message.role !== "user" ||
    !message.clientMessageId ||
    !message.sender ||
    !message.conversationId
  )
    return undefined;
  return JSON.stringify([message.conversationId, message.sender.user_id, message.clientMessageId]);
}

function persistedAliases(local: ChatMessage[], history: ChatMessage[]): Map<string, string> {
  const aliases = new Map<string, string>();
  const prompts = new Map<string, number | null>();
  history.forEach((message, index) => {
    const key = promptKey(message);
    if (key !== undefined) prompts.set(key, prompts.has(key) ? null : index);
  });
  local.forEach((message, index) => {
    if (!message.isTemporaryId || message.role !== "user") return;
    const key = promptKey(message);
    const savedIndex = key === undefined ? undefined : prompts.get(key);
    if (typeof savedIndex !== "number") return;
    const saved = history[savedIndex]!;
    aliases.set(message.id, saved.id);
    // Only this prompt's initial local answer, never a later turn or a resumed
    // segment whose saved history contains several distinct assistant messages.
    const answer = local[index + 1];
    if (answer?.role !== "assistant" || !answer.isTemporaryId) return;
    const suffix = history.slice(savedIndex + 1);
    const boundary = suffix.findIndex((item) => item.role === "user");
    const responses = answer.runId
      ? history.filter((item) => item.role === "assistant" && item.runId === answer.runId)
      : (boundary < 0 ? suffix : suffix.slice(0, boundary)).filter(
          (item) => item.role === "assistant",
        );
    if (responses.length === 1) {
      aliases.set(answer.id, responses[0]!.id);
    }
  });
  // HTTP continuations have no message_saved frame. Their text and call ids
  // arrive again in persisted rows, sometimes split across several segments.
  for (const message of local) {
    if (!message.isLocalContinuation || !message.runId) continue;
    const run = history.filter(
      (saved) =>
        saved.role === "assistant" && saved.runId === message.runId && !saved.isLocalContinuation,
    );
    const calls = message.toolCalls ?? [];
    const savedCalls = new Set(
      run.flatMap((saved) => (saved.toolCalls ?? []).map((call) => call.id)),
    );
    if (!calls.every((call) => savedCalls.has(call.id))) continue;
    const match = message.content
      ? run.find((saved) => saved.content === message.content)
      : calls.length > 0
        ? run.find((saved) => saved.toolCalls?.some((call) => call.id === calls.at(-1)?.id))
        : undefined;
    if (match) aliases.set(message.id, match.id);
  }
  return aliases;
}

export interface ChatState {
  messages: ChatMessage[];
  /** Set atomically with the converted transcript, before its socket may attach. */
  loadedTranscript: TranscriptIdentity | null;
  isStreaming: boolean;

  addMessage: (message: ChatMessage) => void;
  updateMessage: (id: string, updater: (msg: ChatMessage) => ChatMessage) => void;
  /** Take a message back off the transcript: one the server refused before saving it. */
  removeMessage: (id: string) => void;
  updateMessagesWhere: (
    predicate: (msg: ChatMessage) => boolean,
    updater: (msg: ChatMessage) => ChatMessage,
  ) => void;
  addToolCall: (messageId: string, toolCall: ToolCall) => void;
  updateToolCall: (messageId: string, toolCallId: string, update: Partial<ToolCall>) => void;
  /** Append a streamed text delta - extends the trailing text part or
   *  starts a new one, keeping the flat `content` aggregate in sync. `fresh`
   *  starts one regardless: the delta opens a new model response. */
  appendTextDelta: (messageId: string, text: string, fresh?: boolean) => void;
  /** Append a streamed reasoning delta - same logic for "thinking" parts. */
  appendThinkingDelta: (messageId: string, text: string) => void;
  /** Add a tool call as an ordered part (and to the flat `toolCalls`). */
  addToolCallPart: (messageId: string, toolCall: ToolCall) => void;
  /** Update a tool call inside its part and the flat `toolCalls`. */
  updateToolCallPart: (messageId: string, toolCallId: string, update: Partial<ToolCall>) => void;
  setStreaming: (streaming: boolean) => void;
  clearMessages: () => void;
  /** Reconcile stored rows while retaining later turns and unsaved local outcomes. */
  rereadMessages: (history?: ChatMessage[], identity?: TranscriptIdentity | null) => void;
  /** The message the next turn replies to, chosen with Reply; null for none. */
  replyTo: MessageReply | null;
  setReplyTo: (reply: MessageReply | null) => void;
  roomDrafts: Record<string, RoomDraft>;
  roomDraftGeneration: number;
  updateRoomDraft: (key: string, update: (draft: RoomDraft) => RoomDraft) => void;
  clearRoomDrafts: () => void;
  rereadRoomThread: (history: ChatMessage[], root: string, identity: TranscriptIdentity) => void;
}

function reconcileTranscript(
  state: Pick<ChatState, "messages" | "loadedTranscript">,
  history: ChatMessage[],
  identity: TranscriptIdentity | null,
) {
  const previous = state.loadedTranscript;
  const sameTranscript =
    identity !== null &&
    previous !== null &&
    previous.conversationId === identity.conversationId &&
    previous.selectionVersion === identity.selectionVersion &&
    previous.accountId === identity.accountId &&
    (previous.tenantId === identity.tenantId ||
      // Only a successful history commit may give an unresolved live
      // transcript its concrete tenant. The stored identity changes now;
      // null never acts as a wildcard for a later tenant or socket attach.
      (previous.tenantId === null && identity.tenantId !== null));
  const local = identity !== null && !sameTranscript ? [] : state.messages;
  // An empty refresh can have started before a live message arrived. Keep
  // those newer messages only within this exact loaded selection/session.
  if (history.length === 0)
    return { messages: identity === null ? [] : local, loadedTranscript: identity };
  const incoming = new Map(history.map((message) => [message.id, message]));
  const aliases = persistedAliases(local, history);
  const savedId = (message: ChatMessage): string =>
    aliases.get(message.id) ?? message.persistedId ?? message.id;
  const anchor = local.findLastIndex((message) => incoming.has(savedId(message)));
  const before = new Map<string | undefined, ChatMessage[]>();
  let nextPersisted: string | undefined;
  // The server's ordinal order is authoritative, including tied timestamps.
  // Local-only outcomes keep their place beside the nearest persisted row.
  for (let index = local.length - 1; index >= 0; index--) {
    const message = local[index]!;
    const id = savedId(message);
    const persisted = incoming.get(id);
    if (persisted) {
      nextPersisted = id;
      incoming.set(
        id,
        message.isStreaming
          ? { ...message, persistedId: id }
          : {
              ...retainNextSteps(persisted, message),
              renderKey: message.renderKey ?? message.id,
            },
      );
    } else if (
      message.threadRootMessageId !== undefined ||
      message.isStreaming ||
      (message.role === "assistant" && message.isTemporaryId) ||
      index > anchor
    ) {
      const group = before.get(nextPersisted) ?? [];
      group.push(message);
      before.set(nextPersisted, group);
    }
  }
  const messages = [...incoming.entries()].flatMap(([id, message]) => [
    ...(before.get(id) ?? []).reverse(),
    message,
  ]);
  messages.push(...(before.get(undefined) ?? []).reverse());
  return { messages, loadedTranscript: identity };
}

const chatState: StateCreator<ChatState> = (set) => ({
  messages: [],
  loadedTranscript: null,
  isStreaming: false,
  replyTo: null,
  roomDrafts: {},
  roomDraftGeneration: 0,

  addMessage: (message) =>
    set((state) => {
      // A persisted update can beat the HTTP response that describes it.
      if (
        message.isLocalContinuation &&
        persistedAliases([message], state.messages).has(message.id)
      )
        return state;
      return { messages: [...state.messages, message] };
    }),

  updateMessage: (id, updater) =>
    set((state) => {
      const index = state.messages.findIndex((message) => message.id === id);
      if (index < 0) return state;
      const updated = updater(state.messages[index]!);
      // History may arrive before message_saved renames the live bubble. Keep
      // its render key and current content, replacing the already-fetched row.
      return {
        messages: state.messages.flatMap((message, position) =>
          position === index ? [updated] : message.id === updated.id ? [] : [message],
        ),
      };
    }),

  removeMessage: (id) =>
    set((state) => ({
      messages: state.messages.filter((msg) => msg.id !== id),
    })),

  updateMessagesWhere: (predicate, updater) =>
    set((state) => ({
      messages: state.messages.map((msg) => (predicate(msg) ? updater(msg) : msg)),
    })),

  addToolCall: (messageId, toolCall) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === messageId ? { ...msg, toolCalls: [...(msg.toolCalls || []), toolCall] } : msg,
      ),
    })),

  updateToolCall: (messageId, toolCallId, update) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              toolCalls: msg.toolCalls?.map((tc) =>
                tc.id === toolCallId ? { ...tc, ...update } : tc,
              ),
            }
          : msg,
      ),
    })),

  appendTextDelta: (messageId, text, fresh = false) =>
    set((state) => ({
      messages: state.messages.map((msg) => {
        if (msg.id !== messageId) return msg;
        const parts: MessagePart[] = msg.parts ? [...msg.parts] : [];
        const last = parts[parts.length - 1];
        if (last && last.type === "text" && !fresh) {
          parts[parts.length - 1] = { ...last, content: (last.content ?? "") + text };
        } else {
          parts.push({ id: clientId(), type: "text", content: text });
        }
        return { ...msg, parts, content: msg.content + text };
      }),
    })),

  appendThinkingDelta: (messageId, text) =>
    set((state) => ({
      messages: state.messages.map((msg) => {
        if (msg.id !== messageId) return msg;
        const parts: MessagePart[] = msg.parts ? [...msg.parts] : [];
        const last = parts[parts.length - 1];
        if (last && last.type === "thinking") {
          parts[parts.length - 1] = { ...last, content: (last.content ?? "") + text };
        } else {
          parts.push({ id: clientId(), type: "thinking", content: text });
        }
        return { ...msg, parts, thinking: (msg.thinking ?? "") + text };
      }),
    })),

  addToolCallPart: (messageId, toolCall) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              parts: [...(msg.parts ?? []), { id: clientId(), type: "tool", toolCall }],
              toolCalls: [...(msg.toolCalls || []), toolCall],
            }
          : msg,
      ),
    })),

  updateToolCallPart: (messageId, toolCallId, update) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === messageId
          ? {
              ...msg,
              parts: msg.parts?.map((p) =>
                p.type === "tool" && p.toolCall && p.toolCall.id === toolCallId
                  ? { ...p, toolCall: { ...p.toolCall, ...update } }
                  : p,
              ),
              toolCalls: msg.toolCalls?.map((tc) =>
                tc.id === toolCallId ? { ...tc, ...update } : tc,
              ),
            }
          : msg,
      ),
    })),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  // Another conversation opened: a reply chosen in this one goes with it.
  clearMessages: () => set({ messages: [], replyTo: null, loadedTranscript: null }),
  rereadMessages: (history = [], identity = null) =>
    set((state) => reconcileTranscript(state, history, identity)),
  rereadRoomThread: (history, root, identity) =>
    set((state) => {
      const loaded = state.loadedTranscript;
      if (
        loaded === null ||
        loaded.conversationId !== identity.conversationId ||
        loaded.selectionVersion !== identity.selectionVersion ||
        loaded.accountId !== identity.accountId ||
        loaded.tenantId !== identity.tenantId ||
        history.some(
          (message) =>
            message.conversationId !== identity.conversationId ||
            message.threadRootMessageId !== root,
        )
      )
        return state;
      const selected = state.messages.filter((message) => message.threadRootMessageId === root);
      const result = reconcileTranscript(
        { messages: selected, loadedTranscript: loaded },
        history,
        identity,
      );
      return {
        messages: [
          ...state.messages.filter((message) => message.threadRootMessageId !== root),
          ...result.messages,
        ],
      };
    }),
  setReplyTo: (replyTo) => set({ replyTo }),
  updateRoomDraft: (key, update) =>
    set((state) => ({
      roomDrafts: { ...state.roomDrafts, [key]: update(state.roomDrafts[key] ?? EMPTY_ROOM_DRAFT) },
    })),
  clearRoomDrafts: () =>
    set((state) => ({ roomDrafts: {}, roomDraftGeneration: state.roomDraftGeneration + 1 })),
});

/** A copy of its own, for a conversation in a scope - see `ChatScope`. */
export const createChatStore = () => createStore<ChatState>()(chatState);

export const useChatStore = scopedStore(create<ChatState>()(chatState), (scope) => scope.chat);
