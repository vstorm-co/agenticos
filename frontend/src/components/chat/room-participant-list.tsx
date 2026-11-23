"use client";

import { useTranslations } from "next-intl";

import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantRow } from "./room-participant-row";

interface RoomParticipantListProps {
  members: RoomParticipantRead[];
  currentUserId: string | undefined;
  canManage: boolean;
  ownerUserId: string | undefined;
  isProjectConversation: boolean;
  isUpdatingAutoReply: boolean;
  isRemoving: boolean;
  onRemove: (participant: RoomParticipantRead) => void;
  onAutoReplyChange: (agentId: string, enabled: boolean) => void;
}

/** Draw members and only the membership controls the current room allows. */
export function RoomParticipantList({
  members,
  currentUserId,
  canManage,
  ownerUserId,
  isProjectConversation,
  isUpdatingAutoReply,
  isRemoving,
  onRemove,
  onAutoReplyChange,
}: RoomParticipantListProps) {
  const t = useTranslations("chat.roomParticipants");

  return (
    <section aria-labelledby="room-participants-heading">
      <h3 id="room-participants-heading" className="text-sm font-medium">
        {t("title")}
      </h3>
      {members.length > 0 ? (
        <ul className="divide-border divide-y">
          {members.map((participant) => (
            <RoomParticipantRow
              key={`${participant.kind}:${participant.id}`}
              participant={participant}
              currentUserId={currentUserId}
              canManage={canManage}
              canRemove={
                canManage &&
                !(participant.kind === "user" && participant.id === ownerUserId) &&
                (!isProjectConversation || participant.kind === "agent")
              }
              isUpdatingAutoReply={isUpdatingAutoReply}
              isRemoving={isRemoving}
              onRemove={onRemove}
              onAutoReplyChange={onAutoReplyChange}
            />
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground py-3 text-sm">{t("empty")}</p>
      )}
    </section>
  );
}
