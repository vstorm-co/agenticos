"use client";

import { GitBranch } from "lucide-react";
import { useTranslations } from "next-intl";

import type { ConversationForkOrigin } from "@/types";

interface ForkedFromProps {
  origin: ConversationForkOrigin;
  /** Open the source conversation. */
  onOpen: (conversationId: string) => void;
}

/**
 * The line at the top of a fork that names the conversation it came from (#2762).
 *
 * The server sends the origin only to the person who owns both conversations,
 * so whoever a fork is shared with never sees this line.
 */
export function ForkedFrom({ origin, onOpen }: ForkedFromProps) {
  const t = useTranslations("chat");
  return (
    <div className="text-muted-foreground mx-auto mb-4 flex max-w-full flex-wrap items-center justify-center gap-1.5 text-xs">
      <GitBranch className="h-3 w-3" aria-hidden />
      {t.rich("forkedFrom", {
        title: origin.title || t("untitledFork"),
        link: (chunks) => (
          <button
            type="button"
            onClick={() => onOpen(origin.conversation_id)}
            className="hover:text-foreground max-w-64 truncate underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {chunks}
          </button>
        ),
      })}
    </div>
  );
}
