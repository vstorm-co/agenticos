"use client";

import { Pin, PinOff } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useMessagePins } from "@/hooks/use-message-pins";

export interface PinnedMessageTarget {
  messageId: string;
  threadRootMessageId?: string | null;
}

/** A bounded, reader-private list of pins for the open conversation. */
export function PinnedMessages({
  conversationId,
  onJumpToMessage,
}: {
  conversationId: string | null | undefined;
  onJumpToMessage: (target: PinnedMessageTarget) => void;
}) {
  const t = useTranslations("chat.messagePins");
  const [open, setOpen] = useState(false);
  const jumping = useRef(false);
  const pins = useMessagePins(conversationId, open);

  if (!conversationId) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={pins.isSuccess ? `${t("open")} (${pins.total})` : t("open")}
          title={t("open")}
          data-tour="chat-message-pins"
        >
          <Pin aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-80 p-0"
        onCloseAutoFocus={(event) => {
          if (!jumping.current) return;
          jumping.current = false;
          event.preventDefault();
        }}
      >
        <div className="border-border border-b px-4 py-3">
          <h2 className="text-sm font-medium">{t("title")}</h2>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5">
          {pins.isLoading ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("loading")}</p>
          ) : pins.isError ? (
            <div className="flex flex-col items-center gap-2 px-3 py-5 text-center">
              <p role="alert" className="text-muted-foreground text-sm">
                {t("listFailed")}
              </p>
              <Button type="button" variant="outline" size="sm" onClick={() => void pins.refetch()}>
                {t("retry")}
              </Button>
            </div>
          ) : pins.items.length === 0 ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("empty")}</p>
          ) : (
            <>
              <ul>
                {pins.items.map((pin) => (
                  <li key={pin.message_id} className="flex items-start gap-1">
                    <button
                      type="button"
                      onClick={() => {
                        jumping.current = true;
                        onJumpToMessage({
                          messageId: pin.message_id,
                          threadRootMessageId: pin.thread_root_message_id,
                        });
                        setOpen(false);
                      }}
                      className="hover:bg-accent flex min-w-0 flex-1 items-start gap-2.5 rounded-lg px-3 py-2.5 text-left"
                    >
                      <Pin className="text-muted-foreground mt-0.5 size-3.5 shrink-0" aria-hidden />
                      <span className="text-foreground line-clamp-3 min-w-0 text-sm leading-relaxed">
                        {pin.preview.trim() || t("emptyPreview")}
                      </span>
                    </button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("unpin")}
                      title={t("unpin")}
                      disabled={pins.pendingMessageId === pin.message_id}
                      loading={pins.pendingMessageId === pin.message_id}
                      onClick={() => pins.togglePin(pin.message_id, false)}
                    >
                      <PinOff aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
              {pins.hasNextPage && (
                <div className="px-2 pt-1 pb-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    loading={pins.isFetchingNextPage}
                    onClick={() => void pins.fetchNextPage()}
                  >
                    {t("loadMore")}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
