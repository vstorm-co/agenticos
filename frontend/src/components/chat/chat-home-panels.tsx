"use client";

import { useId } from "react";
import { Inbox, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChatHomeInbox, useChatHomeInbox } from "./chat-home-inbox";

export function ChatHomePanels({
  suggestionsRef,
}: {
  suggestionsRef: (node: HTMLDivElement | null) => void;
}) {
  const t = useTranslations("chat.homePanels");
  const inboxText = useTranslations("inbox");
  const inbox = useChatHomeInbox();
  const count = inbox.suggested.suggestions.length + inbox.pending.count;
  const promptsId = useId();

  return (
    <div className="chat-home-panels">
      <div className="min-w-0">
        <h3
          className="chat-home-panel-heading"
          aria-label={count > 0 ? `${t("inbox")}, ${inboxText("waiting", { count })}` : undefined}
        >
          <Inbox className="size-3.5 shrink-0" aria-hidden />
          {t("inbox")}
          {count > 0 && (
            <span
              aria-hidden
              className="bg-foreground/10 rounded-full px-1.5 text-[10px] leading-4 tabular-nums"
            >
              {count}
            </span>
          )}
        </h3>
        <ChatHomeInbox {...inbox} />
      </div>
      <section className="min-w-0" aria-labelledby={promptsId}>
        <h3 id={promptsId} className="chat-home-panel-heading">
          <Sparkles className="size-3.5 shrink-0" aria-hidden />
          {t("prompts")}
        </h3>
        <div ref={suggestionsRef} className="chat-home-starters" />
      </section>
    </div>
  );
}
