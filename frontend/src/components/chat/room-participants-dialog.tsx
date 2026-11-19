"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAddRoomParticipant,
  useJoinPublicRoom,
  useRemoveRoomParticipant,
  useRoomMentionables,
  useRoomParticipants,
  useUpdateRoomAgentAutoReply,
} from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { Conversation } from "@/types/conversation";
import type { RoomParticipantRead } from "@/types/room";
import {
  RoomParticipantConfirmation,
  type RoomParticipantAction,
} from "./room-participant-confirmation";
import { RoomParticipantsDialogBody } from "./room-participants-dialog-body";

interface RoomParticipantsDialogProps {
  conversationId: string;
  conversation: Conversation | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** View, add and remove room participants, with explicit history disclosure. */
export function RoomParticipantsDialog({
  conversationId,
  conversation,
  open,
  onOpenChange,
}: RoomParticipantsDialogProps) {
  const t = useTranslations("chat.roomParticipants");
  const tRooms = useTranslations("chat.rooms");
  const tErrors = useTranslations("errors");
  const currentUserId = useAuthStore((state) => state.user?.id);
  const participantsQuery = useRoomParticipants(conversationId);
  const mentionablesQuery = useRoomMentionables(conversationId);
  const addParticipant = useAddRoomParticipant(conversationId);
  const joinRoom = useJoinPublicRoom();
  const removeParticipant = useRemoveRoomParticipant(conversationId);
  const autoReply = useUpdateRoomAgentAutoReply(conversationId);
  const [action, setAction] = useState<RoomParticipantAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);
  const members = participantsQuery.participants.filter((item) => item.is_member);
  const isProjectConversation =
    conversation !== null &&
    conversation.project_id !== null &&
    conversation.project_id !== undefined;
  const candidates = mentionablesQuery.mentionables.filter(
    (item) => !item.is_member && item.can_add && (!isProjectConversation || item.kind === "agent"),
  );
  const canManage = participantsQuery.canManage;
  const canPost = participantsQuery.canPost;
  const canJoinPublicRoom =
    participantsQuery.visibility === "public" && !canPost && conversation?.is_archived !== true;
  const isLegacyDirect =
    conversation !== null &&
    conversation.project_id === null &&
    conversation.room_visibility === null;
  const isPending = addParticipant.isAdding || removeParticipant.isRemoving;

  const handleJoin = async () => {
    setJoinError(null);
    try {
      await joinRoom.join(conversationId);
      await participantsQuery.refetch();
    } catch (error) {
      setJoinError(getErrorMessage(error, tErrors, tRooms("joinFailed")));
    }
  };

  const handleConfirm = async () => {
    if (action === null) return;
    setActionError(null);
    try {
      const { participant } = action;
      if (action.kind === "add")
        await addParticipant.add({ kind: participant.kind, id: participant.id });
      else await removeParticipant.remove({ kind: participant.kind, id: participant.id });
      setAction(null);
    } catch (error) {
      setActionError(
        getErrorMessage(error, tErrors, t(action.kind === "add" ? "addFailed" : "removeFailed")),
      );
    }
  };

  const handleAutoReplyChange = async (agentId: string, enabled: boolean) => {
    setInlineError(null);
    try {
      await autoReply.update(agentId, enabled);
    } catch (error) {
      setInlineError(getErrorMessage(error, tErrors, t("autoReplyFailed")));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(DIALOG_FORM, DIALOG_SCROLL)}
        dismissible={!isPending && !joinRoom.isJoining && !autoReply.isUpdating}
      >
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <RoomParticipantsDialogBody
          isLoading={participantsQuery.isLoading}
          error={participantsQuery.error}
          members={members}
          candidates={candidates}
          currentUserId={currentUserId}
          canManage={canManage}
          canPost={canPost}
          canJoinPublicRoom={canJoinPublicRoom}
          isJoining={joinRoom.isJoining}
          joinError={joinError}
          isProjectConversation={isProjectConversation}
          ownerUserId={conversation?.user_id}
          isUpdatingAutoReply={autoReply.isUpdating}
          isRemoving={removeParticipant.isRemoving}
          isAdding={addParticipant.isAdding}
          mentionablesLoading={mentionablesQuery.isLoading}
          mentionablesError={mentionablesQuery.error}
          inlineError={inlineError}
          onRetry={() => void participantsQuery.refetch()}
          onRetryMentionables={() => void mentionablesQuery.refetch()}
          onJoin={() => void handleJoin()}
          onRemove={(participant: RoomParticipantRead) => {
            setActionError(null);
            setAction({ kind: "remove", participant });
          }}
          onAutoReplyChange={(agentId, enabled) => void handleAutoReplyChange(agentId, enabled)}
          onAdd={(participant) => {
            setActionError(null);
            setAction({ kind: "add", participant });
          }}
        />
        <RoomParticipantConfirmation
          action={action}
          isLegacyDirect={isLegacyDirect}
          isPending={isPending}
          error={actionError}
          onOpenChange={(nextOpen) => {
            if (!nextOpen) {
              setAction(null);
              setActionError(null);
            }
          }}
          onConfirm={() => void handleConfirm()}
        />
      </DialogContent>
    </Dialog>
  );
}
