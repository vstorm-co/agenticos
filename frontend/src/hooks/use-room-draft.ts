"use client";

import { useTranslations } from "next-intl";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { clientId } from "@/lib/ids";
import { useAuthStore, useChatStore, useOrgStore } from "@/stores";
import { EMPTY_ROOM_DRAFT } from "@/stores/chat-store";
import { useRoomActions } from "./use-room";
import type { MessageReply } from "@/types/chat";

/** An uncertain POST keeps its exact payload until the server acknowledges it. */
export function useRoomDraft(
  conversationId: string | null,
  threadRootMessageId: string | null = null,
) {
  const t = useTranslations("chat.teamRoom");
  const tErrors = useTranslations("errors");
  const { post, isCurrent } = useRoomActions(conversationId);
  const chatApi = useChatStore.useApi();
  const accountId = useAuthStore((state) => state.user?.id);
  const tenantId = useOrgStore((state) => state.activeOrgId);
  const key = JSON.stringify([accountId, tenantId, conversationId, threadRootMessageId]);
  const draft = useChatStore((state) => state.roomDrafts[key]) ?? EMPTY_ROOM_DRAFT;
  const reply = useChatStore((state) =>
    threadRootMessageId === null ? state.replyTo : (state.roomDrafts[key]?.reply ?? null),
  );
  const change = (apply: (value: typeof EMPTY_ROOM_DRAFT) => typeof EMPTY_ROOM_DRAFT) =>
    chatApi.getState().updateRoomDraft(key, apply);
  const setReply = (value: MessageReply | null) => {
    if (threadRootMessageId === null) chatApi.getState().setReplyTo(value);
    else change((held) => ({ ...held, reply: value }));
  };

  async function submit() {
    const generation = chatApi.getState().roomDraftGeneration;
    const held = chatApi.getState().roomDrafts[key] ?? EMPTY_ROOM_DRAFT;
    if (held.sending || !isCurrent() || held.content.trim().length === 0) return;
    const selectedReply = threadRootMessageId === null ? chatApi.getState().replyTo : held.reply;
    const snapshot = held.attempt ?? {
      input: {
        client_message_id: clientId(),
        content: held.content.trim(),
        ...(held.agentId === null ? {} : { agent_id: held.agentId }),
        ...(selectedReply === null ? {} : { reply_to_message_id: selectedReply.messageId }),
        ...(threadRootMessageId === null ? {} : { thread_root_message_id: threadRootMessageId }),
      },
      reply: selectedReply,
    };
    change((value) => ({ ...value, attempt: snapshot, sending: true, error: null }));
    try {
      const accepted = await post(snapshot.input);
      if (
        !accepted ||
        !isCurrent() ||
        chatApi.getState().roomDraftGeneration !== generation ||
        chatApi.getState().roomDrafts[key]?.attempt !== snapshot
      )
        return;
      change((value) => ({
        ...EMPTY_ROOM_DRAFT,
        reply: value.reply?.messageId === snapshot.reply?.messageId ? null : value.reply,
      }));
      // Reply can be selected from the transcript while the acknowledgement travels.
      if (
        threadRootMessageId === null &&
        chatApi.getState().replyTo?.messageId === snapshot.reply?.messageId
      ) {
        chatApi.getState().setReplyTo(null);
      }
    } catch (failure) {
      if (
        !isCurrent() ||
        chatApi.getState().roomDraftGeneration !== generation ||
        chatApi.getState().roomDrafts[key]?.attempt !== snapshot
      )
        return;
      change((value) => ({ ...value, error: getErrorMessage(failure, tErrors, t("postFailed")) }));
      // These are definite refusals before admission. Unknown outcomes retain
      // the id and frozen payload, including the chosen agent and reply.
      if (
        held.attempt === null &&
        failure instanceof ApiError &&
        [400, 403, 404, 422].includes(failure.status)
      ) {
        change((value) => ({ ...value, attempt: null, sending: false }));
      }
    } finally {
      // Closing a thread keeps its uncertain token retryable. A tenant reset
      // removes the slot, and a late response must never recreate it.
      if (
        chatApi.getState().roomDraftGeneration === generation &&
        chatApi.getState().roomDrafts[key]?.attempt === snapshot
      ) {
        change((value) => ({ ...value, sending: false }));
      }
    }
  }

  return {
    content: draft.content,
    setContent: (content: string) => change((value) => ({ ...value, content })),
    agentId: draft.agentId,
    setAgentId: (agentId: string | null) => change((value) => ({ ...value, agentId })),
    reply: draft.attempt === null ? reply : draft.attempt.reply,
    setReply,
    clearReply: () => setReply(null),
    locked: draft.attempt !== null,
    retrying: draft.attempt !== null && !draft.sending,
    sending: draft.sending,
    error: draft.error,
    submit,
  };
}
