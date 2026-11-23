"use client";

import { useState } from "react";
import { SmilePlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { RoomMessageReactionSummary } from "@/types/room-message-reaction";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useRoomMessageReactions } from "@/hooks/use-room-message-reactions";

const QUICK_REACTIONS = [
  "👍",
  "❤️",
  "😂",
  "🎉",
  "👀",
  "🙏",
  "✅",
  "🚀",
  "🤔",
  "🙌",
  "🔥",
  "💯",
  "😮",
  "😢",
  "👎",
  "🤝",
];

const EMPTY_REACTIONS: RoomMessageReactionSummary[] = [];

interface RoomMessageReactionsProps {
  conversationId: string;
  messageId: string;
  initialReactions?: RoomMessageReactionSummary[];
  canReact: boolean;
  align: "start" | "end";
}

export function RoomMessageReactions({
  conversationId,
  messageId,
  initialReactions = EMPTY_REACTIONS,
  canReact,
  align,
}: RoomMessageReactionsProps) {
  const t = useTranslations("chat.roomReactions");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [customEmoji, setCustomEmoji] = useState("");
  const { reactions, add, remove, retry, isPending, hasError } = useRoomMessageReactions(
    conversationId,
    messageId,
    initialReactions,
  );

  const choose = async (emoji: string) => {
    const saved = await add(emoji);
    if (saved) setPickerOpen(false);
    return saved;
  };

  const submitCustom = async () => {
    if (!customEmoji.trim()) return;
    const saved = await choose(customEmoji.trim());
    if (saved) setCustomEmoji("");
  };

  return (
    <div className={cn("flex flex-wrap items-center gap-1", align === "end" && "justify-end")}>
      {reactions.map((reaction) => {
        const content = (
          <>
            <span aria-hidden>{reaction.emoji}</span>
            <span className="tabular-nums">{reaction.count}</span>
          </>
        );
        return canReact ? (
          <button
            key={reaction.emoji}
            type="button"
            onClick={() =>
              void (reaction.reacted_by_me ? remove(reaction.emoji) : add(reaction.emoji))
            }
            disabled={isPending}
            aria-pressed={reaction.reacted_by_me}
            aria-label={`${reaction.emoji} ${reaction.count}`}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-full border px-2 text-xs transition-colors disabled:opacity-60",
              reaction.reacted_by_me
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "border-foreground/10 bg-muted/40 text-muted-foreground hover:bg-muted",
            )}
          >
            {content}
          </button>
        ) : (
          <span
            key={reaction.emoji}
            aria-label={`${reaction.emoji} ${reaction.count}`}
            className="border-foreground/10 bg-muted/40 text-muted-foreground inline-flex h-7 items-center gap-1 rounded-full border px-2 text-xs"
          >
            {content}
          </span>
        );
      })}

      {canReact && (
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              title={t("add")}
              aria-label={t("add")}
              aria-expanded={pickerOpen}
              disabled={isPending}
              className="text-muted-foreground hover:bg-muted hover:text-foreground inline-flex size-7 items-center justify-center rounded-full border border-transparent transition-colors disabled:opacity-60"
            >
              <SmilePlus className="size-4" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent align={align === "end" ? "end" : "start"} className="w-64 space-y-3 p-3">
            <div className="grid grid-cols-8 gap-1" aria-label={t("add")}>
              {QUICK_REACTIONS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  onClick={() => void choose(emoji)}
                  disabled={isPending}
                  aria-label={emoji}
                  title={emoji}
                  className="hover:bg-muted focus-visible:outline-foreground flex size-7 items-center justify-center rounded-md text-base focus-visible:outline-2 disabled:opacity-50"
                >
                  {emoji}
                </button>
              ))}
            </div>
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void submitCustom();
              }}
            >
              <input
                value={customEmoji}
                onChange={(event) => setCustomEmoji(event.target.value)}
                maxLength={32}
                aria-label={t("customPlaceholder")}
                placeholder={t("customPlaceholder")}
                className="border-foreground/15 bg-background placeholder:text-muted-foreground focus-visible:ring-foreground/30 min-w-0 flex-1 rounded-lg border px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2"
              />
              <button
                type="submit"
                disabled={isPending || !customEmoji.trim()}
                className="bg-control hover:bg-control-hover rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50"
              >
                {t("submit")}
              </button>
            </form>
          </PopoverContent>
        </Popover>
      )}

      {hasError && (
        <span className="text-destructive flex items-center gap-1 text-xs" role="alert">
          {t("error")}
          <button
            type="button"
            onClick={() => void retry()}
            disabled={isPending}
            className="underline underline-offset-2 disabled:opacity-60"
          >
            {t("retry")}
          </button>
        </span>
      )}
    </div>
  );
}
