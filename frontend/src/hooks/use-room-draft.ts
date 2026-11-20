"use client";

import { useTranslations } from "next-intl";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { clientId } from "@/lib/ids";
import { announceRoomChange } from "@/lib/room-events";
import { useAuthStore, useChatStore, useOrgStore } from "@/stores";
import { EMPTY_ROOM_DRAFT } from "@/stores/chat-store";
import { insertRoomMention, reconcileRoomMentionEdit, roomMentionRefs } from "@/lib/room-mentions";
import type { RoomMentionEditHint, RoomMentionQuery } from "@/lib/room-mentions";
import { useRoomActions } from "./use-room";
import type { MessageReply } from "@/types/chat";
import type { RoomParticipantRead, RoomPendingUpload } from "@/types/room";
import type { FileUploadResponse } from "@/lib/file-api";

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
  const generation = useChatStore((state) => state.roomDraftGeneration);
  const key = JSON.stringify([accountId, tenantId, conversationId, threadRootMessageId]);
  const draft = useChatStore((state) => state.roomDrafts[key]) ?? EMPTY_ROOM_DRAFT;
  const reply = useChatStore((state) =>
    threadRootMessageId === null ? state.replyTo : (state.roomDrafts[key]?.reply ?? null),
  );
  const change = (apply: (value: typeof EMPTY_ROOM_DRAFT) => typeof EMPTY_ROOM_DRAFT) => {
    if (chatApi.getState().roomDraftGeneration !== generation) return false;
    chatApi.getState().updateRoomDraft(key, apply);
    return true;
  };
  const setReply = (value: MessageReply | null) => {
    if (threadRootMessageId === null) chatApi.getState().setReplyTo(value);
    else change((held) => ({ ...held, reply: value }));
  };

  async function submit(leadPolicyRevision?: number) {
    const generation = chatApi.getState().roomDraftGeneration;
    const held = chatApi.getState().roomDrafts[key] ?? EMPTY_ROOM_DRAFT;
    if (
      held.sending ||
      held.pendingUploads.length > 0 ||
      held.uploadError !== null ||
      !isCurrent() ||
      (held.content.trim().length === 0 && held.attachments.length === 0)
    )
      return;
    if (held.attempt === null && held.intent === "ask_lead" && leadPolicyRevision === undefined)
      return;
    const selectedReply = threadRootMessageId === null ? chatApi.getState().replyTo : held.reply;
    const snapshot = held.attempt ?? {
      input: {
        client_message_id: clientId(),
        content: held.content.trim(),
        mentions: roomMentionRefs(held.roomMentions),
        ...(held.attachments.length === 0
          ? {}
          : { file_ids: [...new Set(held.attachments.map((file) => file.id))] }),
        ...(held.intent === "ask_lead"
          ? { intent: "ask_lead" as const, expected_policy_revision: leadPolicyRevision }
          : {}),
        ...(selectedReply === null ? {} : { reply_to_message_id: selectedReply.messageId }),
        ...(selectedReply?.selectedText === undefined
          ? {}
          : { reply_to_excerpt: selectedReply.selectedText }),
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
      const firstPolicyRefusal =
        held.attempt === null &&
        snapshot.input.intent === "ask_lead" &&
        failure instanceof ApiError &&
        failure.status === 409 &&
        failure.code === "ROOM_LEAD_POLICY_CHANGED";
      change((value) => ({
        ...value,
        error: firstPolicyRefusal
          ? t("leadPolicyChanged")
          : getErrorMessage(failure, tErrors, t("postFailed")),
      }));
      // These are definite refusals before admission. Unknown outcomes retain
      // the id and frozen payload, including the chosen agent and reply.
      if (
        held.attempt === null &&
        failure instanceof ApiError &&
        ([400, 403, 404, 422].includes(failure.status) || firstPolicyRefusal)
      ) {
        change((value) => ({ ...value, attempt: null, sending: false }));
        if (firstPolicyRefusal && conversationId !== null) {
          announceRoomChange({ conversationId, accountId, organizationId: tenantId });
        }
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
    roomMentions: draft.roomMentions,
    attachments: draft.attachments,
    pendingUploads: draft.pendingUploads,
    uploadError: draft.uploadError,
    canContinueUpload: () =>
      chatApi.getState().roomDraftGeneration === generation &&
      useAuthStore.getState().user?.id === accountId &&
      useOrgStore.getState().activeOrgId === tenantId,
    beginUploads: (uploads: RoomPendingUpload[]) => {
      let began = false;
      change((value) => {
        if (value.attempt !== null || value.pendingUploads.length > 0 || uploads.length === 0)
          return value;
        began = true;
        return { ...value, pendingUploads: uploads, uploadError: null };
      });
      return began;
    },
    completeUpload: (uploadId: string, file: FileUploadResponse) => {
      let completed = false;
      change((value) => {
        if (!value.pendingUploads.some((upload) => upload.id === uploadId)) return value;
        completed = true;
        return {
          ...value,
          pendingUploads: value.pendingUploads.filter((upload) => upload.id !== uploadId),
          attachments:
            value.attempt !== null || value.attachments.some((item) => item.id === file.id)
              ? value.attachments
              : [...value.attachments, file],
        };
      });
      return completed;
    },
    failUpload: (uploadId: string, error: string) => {
      let failed = false;
      change((value) => {
        if (!value.pendingUploads.some((upload) => upload.id === uploadId)) return value;
        failed = true;
        return {
          ...value,
          pendingUploads: value.pendingUploads.filter((upload) => upload.id !== uploadId),
          uploadError: error,
        };
      });
      return failed;
    },
    clearUploadError: () =>
      change((value) => (value.uploadError === null ? value : { ...value, uploadError: null })),
    addAttachment: (file: FileUploadResponse) =>
      change((value) =>
        value.attempt !== null || value.attachments.some((item) => item.id === file.id)
          ? value
          : { ...value, attachments: [...value.attachments, file] },
      ),
    removeAttachment: (fileId: string) =>
      change((value) =>
        value.attempt !== null
          ? value
          : { ...value, attachments: value.attachments.filter((file) => file.id !== fileId) },
      ),
    setContent: (content: string, editHint?: RoomMentionEditHint) =>
      change((value) => ({
        ...value,
        content,
        roomMentions: reconcileRoomMentionEdit(
          value.content,
          content,
          value.roomMentions,
          editHint,
        ),
      })),
    pickMention: (query: RoomMentionQuery, participant: RoomParticipantRead) => {
      let caret = query.start;
      change((value) => {
        const result = insertRoomMention(value.content, value.roomMentions, query, participant);
        caret = result.caret;
        return { ...value, content: result.content, roomMentions: result.mentions };
      });
      return caret;
    },
    intent: draft.intent,
    setMessageIntent: () => change((value) => ({ ...value, intent: "message" })),
    setAskLead: () => change((value) => ({ ...value, intent: "ask_lead" })),
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
