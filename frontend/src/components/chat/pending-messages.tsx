"use client";

import { useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  GripVertical,
  ListOrdered,
  Loader2,
  Paperclip,
  Send,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { QueuedMessage, SteerDraft } from "@/hooks/use-chat";
import { cn } from "@/lib/utils";

interface PendingMessagesProps {
  /** Waiting for the agent's answer, in the order they will be sent. */
  messages: QueuedMessage[];
  /** Sent into the running task, until the model has read them. */
  steers?: SteerDraft[];
  onCancel: (id: string) => void;
  /** Absent where nothing can be sent now - no running task to join. */
  onSendNow?: (id: string) => void;
  /** Absent where the order cannot change. */
  onMove?: (id: string, to: number) => void;
}

const ROW_ACTION =
  "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors disabled:pointer-events-none disabled:opacity-30 [&_svg]:size-3.5";

/**
 * What the person typed while the agent worked, as a panel above the composer -
 * the same shape as the agent's plan beside it, folding to one line on a click.
 *
 * A message waits for the answer, as in any chat. Each row can be sent now
 * instead, into the running task, dropped, or moved: dragged by its handle or
 * stepped with the arrows, because the queue is the order they go in. One sent
 * into the task stays on the panel, marked, until the model has read it - then
 * it is in the conversation, as the person's own message, where it landed.
 */
export function PendingMessages({
  messages,
  steers = [],
  onCancel,
  onSendNow,
  onMove,
}: PendingMessagesProps) {
  const t = useTranslations("chat");
  const [open, setOpen] = useState(true);
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<number | null>(null);
  if (messages.length === 0 && steers.length === 0) return null;

  const endDrag = () => {
    setDragging(null);
    setOver(null);
  };

  return (
    <div className="panel border-foreground/8 mb-2 overflow-hidden rounded-xl border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        className="hover:bg-foreground/[0.03] flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors"
      >
        <ListOrdered className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        <span className="text-foreground/85 min-w-0 flex-1 truncate text-[13px]">
          {messages.length > 0
            ? t("queuedCount", { count: messages.length })
            : t("whileWorking.steersWaiting")}
        </span>
        {messages.length > 0 && (
          <span className="text-muted-foreground shrink-0 text-xs max-sm:hidden">
            {t("queuedSendsAfterCurrent")}
          </span>
        )}
        <ChevronDown
          className={cn(
            "text-muted-foreground h-3.5 w-3.5 shrink-0 transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="border-foreground/8 max-h-56 scrollbar-thin overflow-y-auto border-t p-1.5">
          {steers.map((steer) => (
            <div
              key={steer.id}
              className="text-muted-foreground flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px]"
            >
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{steer.text}</span>
              <span className="shrink-0 text-xs">{t("sentIntoTask")}</span>
            </div>
          ))}

          <ol>
            {messages.map((message, index) => {
              const fileCount = message.files?.length ?? 0;
              const pointsAt = message.mentions?.length ?? 0;
              return (
                <li
                  key={message.id}
                  draggable={onMove !== undefined}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "move";
                    setDragging(message.id);
                  }}
                  onDragOver={(event) => {
                    if (dragging === null) return;
                    event.preventDefault();
                    setOver(index);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    if (dragging !== null) onMove?.(dragging, index);
                    endDrag();
                  }}
                  onDragEnd={endDrag}
                  className={cn(
                    "group hover:bg-foreground/[0.04] flex items-center gap-1.5 rounded-lg py-1 pr-1 pl-0.5 transition-colors",
                    dragging === message.id && "opacity-40",
                    over === index && dragging !== message.id && "bg-foreground/[0.06]",
                  )}
                >
                  {onMove && (
                    <GripVertical
                      className="text-muted-foreground/50 h-3.5 w-3.5 shrink-0 cursor-grab"
                      aria-hidden
                    />
                  )}
                  <span className="text-muted-foreground w-4 shrink-0 text-center font-mono text-[11px] tabular-nums">
                    {index + 1}
                  </span>
                  <span className="text-foreground min-w-0 flex-1 truncate text-[13px]">
                    {message.content}
                  </span>
                  {fileCount > 0 && (
                    <span className="text-muted-foreground inline-flex shrink-0 items-center gap-1 text-xs">
                      <Paperclip className="h-3 w-3" aria-hidden />
                      {t("fileCount", { count: fileCount })}
                    </span>
                  )}
                  {/* On hover, as the actions under a message are; always there on
                      a touch screen. The arrows are the keyboard's way to reorder. */}
                  <span className="touch:opacity-100 flex shrink-0 items-center opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    {onMove && (
                      <>
                        <button
                          type="button"
                          disabled={index === 0}
                          onClick={() => onMove(message.id, index - 1)}
                          title={t("moveUp")}
                          aria-label={t("moveUp")}
                          className={ROW_ACTION}
                        >
                          <ArrowUp aria-hidden />
                        </button>
                        <button
                          type="button"
                          disabled={index === messages.length - 1}
                          onClick={() => onMove(message.id, index + 1)}
                          title={t("moveDown")}
                          aria-label={t("moveDown")}
                          className={ROW_ACTION}
                        >
                          <ArrowDown aria-hidden />
                        </button>
                      </>
                    )}
                    {onSendNow && (
                      <button
                        type="button"
                        onClick={() => onSendNow(message.id)}
                        // Neither a file nor a mention can ride along into a running task.
                        disabled={fileCount > 0 || pointsAt > 0}
                        title={
                          fileCount > 0
                            ? t("sendNowNotWithFiles")
                            : pointsAt > 0
                              ? t("sendNowNotWithMentions")
                              : t("sendNowHint")
                        }
                        className={cn(ROW_ACTION, "w-auto gap-1 px-1.5 text-xs")}
                      >
                        <Send aria-hidden />
                        {t("sendNow")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => onCancel(message.id)}
                      title={t("removeFromQueue")}
                      aria-label={t("removeFromQueue")}
                      className={cn(ROW_ACTION, "hover:text-destructive")}
                    >
                      <X aria-hidden />
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}
