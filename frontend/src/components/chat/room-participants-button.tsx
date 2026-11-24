"use client";

import { useState } from "react";
import { UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { Conversation } from "@/types/conversation";
import { RoomParticipantsDialog } from "./room-participants-dialog";

interface RoomParticipantsButtonProps {
  conversationId: string;
  conversation: Conversation | null;
  showLabel?: boolean;
}

/** Persistent room roster access, available even when nobody else is present. */
export function RoomParticipantsButton({
  conversationId,
  conversation,
  showLabel = true,
}: RoomParticipantsButtonProps) {
  const t = useTranslations("chat.roomParticipants");
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 shrink-0 gap-1.5 px-2 text-xs"
        aria-label={t("button")}
        title={t("button")}
        onClick={() => setOpen(true)}
      >
        <UsersRound className="h-3.5 w-3.5" aria-hidden />
        {showLabel && <span className="sr-only sm:not-sr-only">{t("button")}</span>}
      </Button>
      {open && (
        <RoomParticipantsDialog
          key={conversationId}
          conversationId={conversationId}
          conversation={conversation}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}
