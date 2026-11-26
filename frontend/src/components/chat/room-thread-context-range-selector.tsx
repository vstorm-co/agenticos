"use client";

import { useId, useMemo, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import type {
  RoomThreadContextCandidateMessage,
  RoomThreadContextRangeInput,
  RoomThreadContextRead,
} from "@/types/room-thread-context";

interface RoomThreadContextRangeSelectorProps {
  mode: "create" | "edit";
  sourceConversationId: string;
  sourceTitle?: string;
  messages: readonly RoomThreadContextCandidateMessage[];
  rootMessageId?: string | null;
  initial?: RoomThreadContextRead | null;
  title?: string;
  hasEarlier?: boolean;
  isLoading?: boolean;
  isLoadingEarlier?: boolean;
  isSaving?: boolean;
  error?: string | null;
  onLoadEarlier?: () => void;
  onCancel?: () => void;
  onSubmit: (input: RoomThreadContextRangeInput) => Promise<void>;
}

/** Keyboard-accessible range boundaries and per-message exclusions. */
export function RoomThreadContextRangeSelector(props: RoomThreadContextRangeSelectorProps) {
  const scope = JSON.stringify([
    props.mode,
    props.sourceConversationId,
    props.rootMessageId ?? null,
    props.initial?.revision ?? null,
    props.initial?.start_message_id ?? null,
    props.initial?.end_message_id ?? null,
    props.initial?.excluded_message_ids ?? [],
    props.title ?? "",
  ]);
  return <RoomThreadContextRangeSelectorContent key={scope} {...props} />;
}

function RoomThreadContextRangeSelectorContent({
  mode,
  sourceConversationId,
  sourceTitle,
  messages,
  rootMessageId = null,
  initial = null,
  title: initialTitle = "",
  hasEarlier = false,
  isLoading = false,
  isLoadingEarlier = false,
  isSaving = false,
  error = null,
  onLoadEarlier,
  onCancel,
  onSubmit,
}: RoomThreadContextRangeSelectorProps) {
  const t = useTranslations("chat.roomThreadContext");
  const titleInputId = useId();
  const [startId, setStartId] = useState(initial?.start_message_id ?? "");
  const [endId, setEndId] = useState(initial?.end_message_id ?? "");
  const [excludedIds, setExcludedIds] = useState<Set<string>>(
    () => new Set(initial?.excluded_message_ids ?? []),
  );
  const [title, setTitle] = useState(initialTitle);
  const [selectionError, setSelectionError] = useState<string | null>(null);

  const eligible = useMemo(() => {
    const rows = messages.filter(
      (message) =>
        (message.role === "user" || message.role === "assistant") &&
        (message.deleted_at == null || message.deleted_at === "") &&
        (message.thread_root_message_id == null ||
          (rootMessageId !== null && message.thread_root_message_id === rootMessageId)),
    );
    if (!rows.every((message) => typeof message.ordinal === "number")) return rows;
    return [...rows].sort((left, right) => left.ordinal! - right.ordinal!);
  }, [messages, rootMessageId]);

  const startIndex = eligible.findIndex((message) => message.id === startId);
  const endIndex = eligible.findIndex((message) => message.id === endId);
  const validBounds = startIndex >= 0 && endIndex >= 0;
  const lower = validBounds ? Math.min(startIndex, endIndex) : -1;
  const upper = validBounds ? Math.max(startIndex, endIndex) : -1;
  const range = validBounds ? eligible.slice(lower, upper + 1) : [];
  const rangeIds = useMemo(() => new Set(range.map((message) => message.id)), [range]);
  const activeExcluded = [...excludedIds].filter((id) => rangeIds.has(id));
  const included = range.filter((message) => !excludedIds.has(message.id));
  const tooManyIncluded = included.length > 500;
  const tooManyExcluded = activeExcluded.length > 500;
  const submitDisabled =
    isLoading ||
    isSaving ||
    !validBounds ||
    included.length === 0 ||
    tooManyIncluded ||
    tooManyExcluded;

  const setBoundary = (kind: "start" | "end", messageId: string) => {
    const nextStart = kind === "start" ? messageId : startId;
    const nextEnd = kind === "end" ? messageId : endId;
    setStartId(nextStart);
    setEndId(nextEnd);
    setSelectionError(null);
    const nextStartIndex = eligible.findIndex((message) => message.id === nextStart);
    const nextEndIndex = eligible.findIndex((message) => message.id === nextEnd);
    if (nextStartIndex < 0 || nextEndIndex < 0) return;
    const nextRange = eligible.slice(
      Math.min(nextStartIndex, nextEndIndex),
      Math.max(nextStartIndex, nextEndIndex) + 1,
    );
    const nextIds = new Set(nextRange.map((message) => message.id));
    setExcludedIds((previous) => new Set([...previous].filter((id) => nextIds.has(id))));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSelectionError(null);
    if (submitDisabled) {
      setSelectionError(
        !validBounds
          ? t("range.chooseBoundaries")
          : included.length === 0
            ? t("range.emptySelection")
            : t("range.limitExceeded", { count: 500 }),
      );
      return;
    }
    await onSubmit({
      start_message_id: eligible[lower]!.id,
      end_message_id: eligible[upper]!.id,
      excluded_message_ids: activeExcluded,
      source_conversation_id: sourceConversationId,
      ...(mode === "create" && title.trim() ? { title: title.trim() } : {}),
    });
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          {t("range.instructions", { source: sourceTitle ?? t("source.selected") })}
        </p>
        {hasEarlier && onLoadEarlier && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isLoadingEarlier}
            onClick={onLoadEarlier}
          >
            {isLoadingEarlier ? t("range.loadingEarlier") : t("range.loadEarlier")}
          </Button>
        )}
      </div>
      {isLoading ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("range.loadingMessages")}
        </p>
      ) : eligible.length === 0 ? (
        <p role="status" className="text-muted-foreground rounded-lg border p-4 text-sm">
          {t("range.noEligibleMessages")}
        </p>
      ) : (
        <ol className="max-h-80 space-y-2 overflow-y-auto rounded-lg border p-2">
          {eligible.map((message) => {
            const inRange = rangeIds.has(message.id);
            const excluded = excludedIds.has(message.id);
            const author =
              message.sender?.name ??
              t(message.role === "user" ? "range.userMessage" : "range.assistantMessage");
            const excerpt = (message.content || author).replace(/\s+/g, " ").slice(0, 80);
            return (
              <li key={message.id} className="rounded-md border p-3">
                <div className="flex flex-wrap items-start gap-2">
                  <p className="min-w-0 flex-1 text-sm font-medium">{author}</p>
                  <div className="flex flex-wrap gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant={startId === message.id ? "secondary" : "outline"}
                      aria-pressed={startId === message.id}
                      aria-label={t("range.setStartFor", { message: excerpt })}
                      onClick={() => setBoundary("start", message.id)}
                    >
                      {t("range.setStart")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={endId === message.id ? "secondary" : "outline"}
                      aria-pressed={endId === message.id}
                      aria-label={t("range.setEndFor", { message: excerpt })}
                      onClick={() => setBoundary("end", message.id)}
                    >
                      {t("range.setEnd")}
                    </Button>
                    {inRange && (
                      <Button
                        type="button"
                        size="sm"
                        variant={excluded ? "secondary" : "outline"}
                        aria-pressed={excluded}
                        aria-label={
                          excluded
                            ? t("range.includeFor", { message: excerpt })
                            : t("range.excludeFor", { message: excerpt })
                        }
                        onClick={() =>
                          setExcludedIds((previous) => {
                            const next = new Set(previous);
                            if (next.has(message.id)) next.delete(message.id);
                            else next.add(message.id);
                            return next;
                          })
                        }
                      >
                        {t(excluded ? "range.include" : "range.exclude")}
                      </Button>
                    )}
                  </div>
                </div>
                <p className="text-muted-foreground mt-2 line-clamp-3 text-sm whitespace-pre-wrap">
                  {message.content || t("range.attachmentOnly")}
                </p>
              </li>
            );
          })}
        </ol>
      )}
      {validBounds && (
        <p aria-live="polite" className="text-muted-foreground text-sm">
          {t("range.selectedCount", { count: included.length })}
        </p>
      )}
      {tooManyIncluded && (
        <p role="alert" className="text-destructive text-sm">
          {t("range.limitExceeded", { count: 500 })}
        </p>
      )}
      {tooManyExcluded && (
        <p role="alert" className="text-destructive text-sm">
          {t("range.exclusionLimitExceeded", { count: 500 })}
        </p>
      )}
      {(error || selectionError) && (
        <p role="alert" className="text-destructive text-sm">
          {error ?? selectionError}
        </p>
      )}
      {mode === "create" && (
        <div className="space-y-2">
          <Label htmlFor={titleInputId}>{t("range.title")}</Label>
          <Input
            id={titleInputId}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t("range.titlePlaceholder")}
            maxLength={120}
            disabled={isSaving}
          />
        </div>
      )}
      <div className="flex justify-end gap-2 border-t pt-3">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={isSaving}>
            {t("range.cancel")}
          </Button>
        )}
        <Button type="submit" disabled={submitDisabled}>
          {isSaving
            ? t("range.saving")
            : t(mode === "create" ? "range.createThread" : "range.saveContext")}
        </Button>
      </div>
    </form>
  );
}
