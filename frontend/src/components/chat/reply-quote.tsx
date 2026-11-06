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
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
  if (reducedMotion) return;
  target.animate?.(
    [
      { backgroundColor: "var(--reply-flash, rgb(127 127 127 / 0.14))" },
      { backgroundColor: "transparent" },
    ],
    { duration: 1400, easing: "ease-out" },
  );
}

/**
 * A compact quote, embedded in a user reply or standing above an agent answer.
 *
 * In a chat several people talk to at once "yes, do that" has to say to what.
 * A click goes to the quoted message where it is still on screen.
 */
export function ReplyQuote({
  reply,
  agents = [],
  align = "end",
  embedded = false,
}: {
  reply: MessageReply;
  agents?: readonly NamedAgent[];
  align?: "start" | "end";
  embedded?: boolean;
}) {
  const t = useTranslations("chat.reply");
  const author = useQuotedAuthor(reply, agents);

  return (
    <div
      className={cn(
        "min-w-0",
        embedded ? "mb-2 w-full" : "w-fit max-w-[min(85%,28rem)]",
        align === "end" ? "self-end" : "self-start",
      )}
    >
      <button
        type="button"
        onClick={() => jumpTo(reply.messageId)}
        title={t("jump")}
        className={cn(
          "border-foreground/20 hover:border-foreground/40 focus-visible:ring-ring block w-full min-w-0 border-l-2 py-1 pl-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none motion-reduce:transition-none",
          !embedded && "bg-foreground/[0.03] rounded-r-lg py-2 pr-3",
        )}
      >
        <span className="text-foreground/75 mb-0.5 flex min-w-0 items-center gap-1.5 text-[11px] font-medium">
          <CornerUpLeft className="size-3 shrink-0" aria-hidden />
          <span className="truncate">
            {author.mine ? t("inReplyToYou") : t("inReplyTo", { name: author.name })}
          </span>
        </span>
        <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed break-words">
          {reply.excerpt}
        </span>
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
    <div className="border-foreground/20 bg-foreground/[0.025] mx-3 mt-3 mb-1 flex min-w-0 items-start gap-2.5 rounded-r-lg border-l-2 py-2 pr-1.5 pl-2.5">
      <CornerUpLeft className="text-muted-foreground mt-0.5 size-3.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-foreground/85 text-xs leading-5">
          {author.mine
            ? t("replyingToYourself")
            : t.rich("replyingTo", {
                name: author.name,
                strong: (chunks) => <span className="font-semibold">{chunks}</span>,
              })}
        </p>
        <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed break-words">
          {reply.excerpt}
        </p>
      </div>
      <button
        type="button"
        onClick={onCancel}
        aria-label={t("cancel")}
        title={t("cancel")}
        className="text-muted-foreground hover:text-foreground hover:bg-accent/60 focus-visible:ring-ring flex size-8 shrink-0 items-center justify-center rounded-md focus-visible:ring-2 focus-visible:outline-none"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
