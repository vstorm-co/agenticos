"use client";

import { MessageSquare } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ChatMessage } from "@/types";
import { TURN_ACTION } from "./turn-action";

export function RoomThreadButton({
  message,
  canStart,
  onOpen,
}: {
  message: ChatMessage;
  canStart: boolean;
  onOpen: (messageId: string) => void;
}) {
  const t = useTranslations("chat.roomThread");
  if (message.isTemporaryId || message.isStreaming || message.role === "system" || !message.content)
    return null;
  const count = message.threadReplyCount ?? 0;
  if (!canStart && count === 0) return null;
  return (
    <button
      type="button"
      data-tour="chat-room-thread"
      className={TURN_ACTION}
      aria-label={count > 0 ? t("replies", { count }) : t("start")}
      onClick={() => onOpen(message.id)}
    >
      <MessageSquare aria-hidden />
      <span>{count > 0 ? t("replies", { count }) : t("start")}</span>
    </button>
  );
}
