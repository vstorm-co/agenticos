"use client";

import { CornerUpLeft, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { MessageReply } from "@/types";

/** As much of an agent as a quote names it by. */
type NamedAgent = { id: string | null; name: string };

/** How much of a message a reply quotes - the server cuts the same. */
const EXCERPT_CHARS = 280;

/** A message as one short line, the way the server quotes it. */
export function replyExcerpt(text: string): string {
  const flat = text.split(/\s+/).filter(Boolean).join(" ");
  return flat.length <= EXCERPT_CHARS ? flat : `${flat.slice(0, EXCERPT_CHARS)}…`;
}

/** Who wrote the quoted message: the reader, a teammate, or an agent by its name. */
function useQuotedAuthor(reply: MessageReply, agents: readonly NamedAgent[]) {
  const me = useAuthStore((state) => state.user?.id);
  const t = useTranslations("chat.reply");
  if (reply.role === "assistant") {
    const agent = agents.find((one) => one.id === reply.agentId);
    return { mine: false, name: agent?.name ?? reply.agentName ?? t("theAgent") };
  }
  const sender = reply.sender;
  if (sender === undefined || sender.user_id === me) return { mine: true, name: "" };
  return { mine: false, name: sender.name };
}

/** Scroll to the quoted message and light it for a moment, so the eye finds it. */
function jumpTo(messageId: string): void {
  const target = document.querySelector<HTMLElement>(
    `[data-message-id="${CSS.escape(messageId)}"]`,
  );
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.animate?.(
    [
      { backgroundColor: "var(--reply-flash, rgb(127 127 127 / 0.14))" },
      { backgroundColor: "transparent" },
    ],
    { duration: 1400, easing: "ease-out" },
  );
}

/**
 * What a turn answers: a small "in reply to" line, and the quoted message as a
 * faded bubble just above the reply.
 *
 * In a chat several people talk to at once "yes, do that" has to say to what.
 * A click goes to the quoted message where it is still on screen.
 */
export function ReplyQuote({
  reply,
  agents = [],
  align = "end",
}: {
  reply: MessageReply;
  agents?: readonly NamedAgent[];
  align?: "start" | "end";
}) {
  const t = useTranslations("chat.reply");
  const author = useQuotedAuthor(reply, agents);

  return (
    <div className={cn("flex max-w-[85%] flex-col", align === "end" ? "items-end" : "items-start")}>
      <span className="text-muted-foreground mb-1 flex items-center gap-1 px-1 text-[11px]">
        <CornerUpLeft className="h-3 w-3" aria-hidden />
        {author.mine ? t("inReplyToYou") : t("inReplyTo", { name: author.name })}
      </span>
      <button
        type="button"
        onClick={() => jumpTo(reply.messageId)}
        title={t("jump")}
        className={cn(
          // A fill rather than an outline, and above the reply rather than under
          // it: a bubble pulled over the quote let the quote's edge show through
          // its translucent fill.
          "bg-foreground/[0.04] text-muted-foreground hover:bg-foreground/[0.07] mb-1 line-clamp-2 rounded-2xl px-3.5 py-2 text-left text-[13px] leading-snug transition-colors",
          align === "end" ? "rounded-br-md" : "rounded-bl-md",
        )}
      >
        {reply.excerpt}
      </button>
    </div>
  );
}

/**
 * The reply being written, above the composer: who it answers and a line of what.
 */
export function ReplyingTo({ reply, onCancel }: { reply: MessageReply; onCancel: () => void }) {
  const t = useTranslations("chat.reply");
  const author = useQuotedAuthor(reply, []);
  return (
    <div className="animate-in fade-in-0 slide-in-from-bottom-2 border-border/60 flex min-w-0 items-start gap-3 border-b px-4 py-2.5">
      <CornerUpLeft className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-foreground text-xs">
          {author.mine
            ? t("replyingToYourself")
            : t.rich("replyingTo", {
                name: author.name,
                strong: (chunks) => <span className="font-semibold">{chunks}</span>,
              })}
        </p>
        <p className="text-muted-foreground truncate text-xs">{reply.excerpt}</p>
      </div>
      <button
        type="button"
        onClick={onCancel}
        aria-label={t("cancel")}
        title={t("cancel")}
        className="text-muted-foreground hover:text-foreground hover:bg-accent/60 -mr-1 shrink-0 rounded-full p-1"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
