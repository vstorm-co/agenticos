"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantAddSection } from "./room-participant-add-section";
import { RoomParticipantList } from "./room-participant-list";

interface RoomParticipantsDialogBodyProps {
  isLoading: boolean;
  error: unknown;
  members: RoomParticipantRead[];
  candidates: RoomParticipantRead[];
  currentUserId: string | undefined;
  canManage: boolean;
  canPost: boolean;
  canJoinPublicRoom: boolean;
  isJoining: boolean;
  joinError: string | null;
  isProjectConversation: boolean;
  ownerUserId: string | undefined;
  isUpdatingAutoReply: boolean;
  isRemoving: boolean;
  isAdding: boolean;
  mentionablesLoading: boolean;
  mentionablesError: unknown;
  inlineError: string | null;
  onRetry: () => void;
  onRetryMentionables: () => void;
  onJoin: () => void;
  onRemove: (participant: RoomParticipantRead) => void;
  onAutoReplyChange: (agentId: string, enabled: boolean) => void;
  onAdd: (participant: RoomParticipantRead) => void;
}

/** Roster, eligible candidates and their query states. */
export function RoomParticipantsDialogBody({
  isLoading,
  error,
  members,
  candidates,
  currentUserId,
  canManage,
  canPost,
  canJoinPublicRoom,
  isJoining,
  joinError,
  isProjectConversation,
  ownerUserId,
  isUpdatingAutoReply,
  isRemoving,
  isAdding,
  mentionablesLoading,
  mentionablesError,
  inlineError,
  onRetry,
  onRetryMentionables,
  onJoin,
  onRemove,
  onAutoReplyChange,
  onAdd,
}: RoomParticipantsDialogBodyProps) {
  const t = useTranslations("chat.roomParticipants");
  const tRooms = useTranslations("chat.rooms");
  if (error) {
    return (
      <div role="alert" className="space-y-3">
        <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (isLoading) {
    return (
      <p role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {t("loading")}
      </p>
    );
  }
  return (
    <div className="min-h-0 space-y-4 overflow-y-auto">
      {canJoinPublicRoom && (
        <div className="border-border rounded-lg border p-3">
          <p className="text-muted-foreground mb-2 text-xs">{tRooms("joinDescription")}</p>
          <Button type="button" size="sm" disabled={isJoining} onClick={onJoin}>
            {isJoining && (
              <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            )}
            {isJoining ? tRooms("joining") : tRooms("join")}
          </Button>
          {joinError && (
            <p className="text-destructive mt-2 text-xs" role="alert">
              {joinError}
            </p>
          )}
        </div>
      )}
      {inlineError && (
        <p role="alert" className="text-destructive text-sm">
          {inlineError}
        </p>
      )}
      <RoomParticipantList
        members={members}
        currentUserId={currentUserId}
        canManage={canManage}
        ownerUserId={ownerUserId}
        isProjectConversation={isProjectConversation}
        isUpdatingAutoReply={isUpdatingAutoReply}
        isRemoving={isRemoving}
        onRemove={onRemove}
        onAutoReplyChange={onAutoReplyChange}
      />
      {canPost ? (
        <RoomParticipantAddSection
          candidates={candidates}
          isLoading={mentionablesLoading}
          error={mentionablesError}
          disabled={isAdding}
          onRetry={onRetryMentionables}
          onAdd={onAdd}
        />
      ) : (
        <p className="text-muted-foreground border-border rounded-lg border p-3 text-xs">
          {t("notManager")}
        </p>
      )}
    </div>
  );
}
