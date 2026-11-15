"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { clientId } from "@/lib/ids";
import { useChatStore } from "@/stores";
import { useRoomActions } from "./use-room";
import type { MessageReply } from "@/types/chat";
import type { RoomMessageCreate } from "@/types/room";

interface Attempt {
  input: RoomMessageCreate;
  reply: MessageReply | null;
}

/** An uncertain POST keeps its exact payload until the server acknowledges it. */
export function useRoomDraft(conversationId: string | null) {
  const t = useTranslations("chat.teamRoom");
  const tErrors = useTranslations("errors");
  const { post, isCurrent } = useRoomActions(conversationId);
  const chatApi = useChatStore.useApi();
  const reply = useChatStore((state) => state.replyTo);
  const [content, setContent] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  async function submit() {
    if (inFlight.current || !isCurrent() || content.trim().length === 0) return;
    const snapshot = attempt ?? {
      input: {
        client_message_id: clientId(),
        content: content.trim(),
        ...(agentId === null ? {} : { agent_id: agentId }),
        ...(reply === null ? {} : { reply_to_message_id: reply.messageId }),
      },
      reply,
    };
    inFlight.current = true;
    setAttempt(snapshot);
    setSending(true);
    setError(null);
    try {
      const accepted = await post(snapshot.input);
      if (!accepted || !isCurrent()) return;
      setContent("");
      setAgentId(null);
      setAttempt(null);
      // Reply can be selected from the transcript while the acknowledgement travels.
      if (chatApi.getState().replyTo?.messageId === snapshot.reply?.messageId) {
        chatApi.getState().setReplyTo(null);
      }
    } catch (failure) {
      if (!isCurrent()) return;
      setError(getErrorMessage(failure, tErrors, t("postFailed")));
      // These are definite refusals before admission. Unknown outcomes retain
      // the id and frozen payload, including the chosen agent and reply.
      if (
        attempt === null &&
        failure instanceof ApiError &&
        [400, 403, 404, 422].includes(failure.status)
      ) {
        setAttempt(null);
      }
    } finally {
      inFlight.current = false;
      if (isCurrent()) setSending(false);
    }
  }

  return {
    content,
    setContent,
    agentId,
    setAgentId,
    reply: attempt === null ? reply : attempt.reply,
    clearReply: () => chatApi.getState().setReplyTo(null),
    locked: attempt !== null,
    retrying: attempt !== null && !sending,
    sending,
    error,
    submit,
  };
}
