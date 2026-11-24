"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { RoomParticipantRead } from "@/types/room";

interface RoomParticipantRowProps {
  participant: RoomParticipantRead;
  currentUserId: string | undefined;
  canManage: boolean;
  canRemove: boolean;
  isUpdatingAutoReply: boolean;
  isRemoving: boolean;
  onRemove: (participant: RoomParticipantRead) => void;
  onAutoReplyChange: (agentId: string, enabled: boolean) => void;
}

/** One room member with the actions the current reader is allowed to take. */
export function RoomParticipantRow({
  participant,
  currentUserId,
  canManage,
  canRemove,
  isUpdatingAutoReply,
  isRemoving,
  onRemove,
  onAutoReplyChange,
}: RoomParticipantRowProps) {
  const t = useTranslations("chat.roomParticipants");
  const kindLabel = t(participant.kind === "agent" ? "agents" : "people");
  const isSelf = participant.kind === "user" && participant.id === currentUserId;

  return (
    <li className="border-border flex min-w-0 items-start gap-3 border-b py-3 last:border-b-0">
      <EntityAvatar
        seed={participant.id}
        name={participant.name}
        imageSrc={participant.avatar_url ?? undefined}
        size="sm"
        ariaHidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium">{participant.name}</span>
          {isSelf && <span className="text-muted-foreground text-xs">{t("you")}</span>}
          <span className="text-muted-foreground shrink-0 text-xs">{kindLabel}</span>
        </div>
        {canManage && participant.kind === "agent" && (
          <div className="mt-2 flex items-start gap-2.5">
            <Switch
              checked={participant.auto_reply ?? false}
              onCheckedChange={(enabled) => onAutoReplyChange(participant.id, enabled)}
              disabled={isUpdatingAutoReply}
              aria-label={t("autoReplyNamed", { name: participant.name })}
              className="mt-0.5"
            />
            <div className="min-w-0">
              <p className="text-sm">{t("autoReply")}</p>
              <p className="text-muted-foreground text-xs">{t("autoReplyHint")}</p>
            </div>
          </div>
        )}
      </div>
      {canRemove && !isSelf && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("removeNamed", { name: participant.name })}
          disabled={isRemoving}
          onClick={() => onRemove(participant)}
          className="text-muted-foreground hover:text-destructive size-8 shrink-0"
        >
          <Trash2 className="size-4" aria-hidden />
        </Button>
      )}
    </li>
  );
}
