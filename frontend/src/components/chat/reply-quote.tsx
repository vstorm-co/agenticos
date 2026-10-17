"use client";

import { CornerUpLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { MessageReply } from "@/types";

/** How much of a message a reply quotes - the server cuts the same. */
const EXCERPT_CHARS = 280;

/** A message as one short line, the way the server quotes it. */
export function replyExcerpt(text: string): string {
  const flat = text.split(/\s+/).filter(Boolean).join(" ");
  return flat.length <= EXCERPT_CHARS ? flat : `${flat.slice(0, EXCERPT_CHARS)}…`;
}

/**
 * The message a turn answers, as one quoted line above it.
 *
 * In a chat several people talk to at once "yes, do that" has to say to what.
 * A click scrolls to the message where it is still on screen.
 */
export function ReplyQuote({ reply, className }: { reply: MessageReply; className?: string }) {
  const t = useTranslations("chat.reply");
  const tRail = useTranslations("chat.rail");
  const me = useAuthStore((state) => state.user?.id);
  const who =
    reply.role === "assistant"
      ? t("theAgent")
      : reply.sender === undefined || reply.sender.user_id === me
        ? tRail("you")
        : reply.sender.name;

  return (
    <button
      type="button"
      onClick={() =>
        document
          .querySelector(`[data-message-id="${CSS.escape(reply.messageId)}"]`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" })
      }
      title={t("jump")}
      className={cn(
        "border-border/70 bg-muted/40 hover:bg-muted text-muted-foreground flex max-w-full min-w-0 items-center gap-1.5 rounded-lg border-l-2 px-2.5 py-1 text-left text-xs transition-colors",
        className,
      )}
    >
      <CornerUpLeft className="h-3 w-3 shrink-0" aria-hidden />
      <span className="text-foreground/80 shrink-0 font-medium">{who}</span>
      <span className="min-w-0 truncate">{reply.excerpt}</span>
    </button>
  );
}
