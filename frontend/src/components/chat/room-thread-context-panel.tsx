"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import {
  useRoomThreadContextActions,
  useRoomThreadContextCandidates,
  useRoomThreadContextSourceConversation,
  useRoomThreadContextSource,
} from "@/hooks/use-room-thread-context";
import type { RawMessage } from "@/lib/conversation-to-chat";
import type {
  RoomThreadContextCandidateMessage,
  RoomThreadContextRangeInput,
  RoomThreadContextRead,
} from "@/types/room-thread-context";
import { RoomThreadContextRangeSelector } from "./room-thread-context-range-selector";
import { RoomThreadContextSourcePicker } from "./room-thread-context-source-picker";

interface RoomThreadContextPanelProps {
  mode: "create" | "thread";
  destinationConversationId: string;
  destinationTitle: string;
  rootMessageId?: string | null;
  threadTitle?: string;
  context?: RoomThreadContextRead | null;
  contextMessages?: readonly RawMessage[];
  canManage?: boolean;
  threadState?: "open" | "closed" | "archived";
  onCreated?: (rootMessageId: string) => void;
}

/** Create a marker from a message range, or manage a thread's separate context snapshot. */
export function RoomThreadContextPanel(props: RoomThreadContextPanelProps) {
  const scope = JSON.stringify([
    props.mode,
    props.destinationConversationId,
    props.rootMessageId ?? null,
    props.context?.source_conversation_id ?? null,
    props.context?.revision ?? null,
  ]);
  return <RoomThreadContextPanelContent key={scope} {...props} />;
}

function RoomThreadContextPanelContent({
  mode,
  destinationConversationId,
  destinationTitle,
  rootMessageId = null,
  threadTitle = "",
  context = null,
  contextMessages = [],
  canManage = false,
  threadState = "open",
  onCreated,
}: RoomThreadContextPanelProps) {
  const t = useTranslations("chat.roomThreadContext");
  const tErrors = useTranslations("errors");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editorLifetime, setEditorLifetime] = useState(0);
  const [sourceConversationId, setSourceConversationId] = useState(
    context?.source_conversation_id ?? destinationConversationId,
  );
  const [sourceTitle, setSourceTitle] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = mode === "create" ? createOpen : editing;
  const actions = useRoomThreadContextActions(
    destinationConversationId,
    mode === "thread" ? rootMessageId : null,
    editorLifetime,
  );
  const source = useRoomThreadContextSource(sourceConversationId, active);
  const sourceConversation = useRoomThreadContextSourceConversation(
    sourceConversationId,
    sourceConversationId !== destinationConversationId && (mode === "thread" || active),
  );
  const candidates = useRoomThreadContextCandidates(
    destinationConversationId,
    rootMessageId,
    context?.revision ?? null,
    mode === "thread" &&
      editing &&
      canManage &&
      sourceConversationId === context?.source_conversation_id,
    context?.source_conversation_id ?? null,
  );

  const openCreateEditor = () => {
    setEditorLifetime((lifetime) => lifetime + 1);
    setCreateOpen(true);
  };
  const closeCreateEditor = () => {
    setEditorLifetime((lifetime) => lifetime + 1);
    setCreateOpen(false);
  };
  const openContextEditor = () => {
    setEditorLifetime((lifetime) => lifetime + 1);
    setEditing(true);
  };
  const closeContextEditor = () => {
    setEditorLifetime((lifetime) => lifetime + 1);
    setEditing(false);
  };

  const sourceRows = useMemo(() => {
    const byId = new Map<string, RoomThreadContextCandidateMessage>();
    if (
      mode === "thread" &&
      context !== null &&
      sourceConversationId === context.source_conversation_id &&
      candidates.data?.source_conversation_id === context.source_conversation_id
    ) {
      for (const item of candidates.data.items) byId.set(item.id, item);
    }
    for (const item of source.messages) {
      byId.set(item.id, item as RoomThreadContextCandidateMessage);
    }
    return [...byId.values()];
  }, [candidates.data, context, mode, source.messages, sourceConversationId]);
  const readableSourceTitle =
    sourceTitle ||
    sourceConversation.data?.title ||
    (sourceConversationId === destinationConversationId ? destinationTitle : "");

  const displayRows = useMemo(() => {
    const rows = [...contextMessages];
    if (rows.every((row) => typeof row.ordinal === "number")) {
      rows.sort((left, right) => (left.ordinal ?? 0) - (right.ordinal ?? 0));
    }
    return rows;
  }, [contextMessages]);

  const sourceReadError =
    active && source.isError
      ? getErrorMessage(source.error, tErrors, t("errors.readFailed"))
      : active &&
          candidates.isError &&
          mode === "thread" &&
          sourceConversationId === context?.source_conversation_id
        ? getErrorMessage(candidates.error, tErrors, t("errors.readFailed"))
        : null;

  const reasonMessage = (error: unknown): string | null => {
    if (!(error instanceof ApiError) || typeof error.details?.reason !== "string") return null;
    switch (error.details.reason) {
      case "room_busy":
        return t("errors.roomBusy");
      case "nested_replies":
        return t("errors.nestedReplies");
      case "stale_context":
        return t("errors.staleContext");
      case "archived_thread":
        return t("errors.archivedThread");
      case "invalid_range":
        return t("errors.invalidRange");
      case "cross_room_move":
        return t("errors.crossRoomMove");
      case "context_source_in_use":
        return t("errors.contextSourceInUse");
      default:
        return null;
    }
  };

  const reportActionError = (error: unknown) =>
    reasonMessage(error) ?? getErrorMessage(error, tErrors, t("errors.actionFailed"));

  const create = async (range: {
    start_message_id: string;
    end_message_id: string;
    excluded_message_ids?: string[];
    title?: string;
    source_conversation_id?: string;
  }) => {
    setActionError(null);
    setNotice(null);
    try {
      const action = await actions.createFromRange(range);
      if (!action || !actions.isCurrent()) return;
      closeCreateEditor();
      onCreated?.(action.root_message_id);
    } catch (error) {
      setActionError(reportActionError(error));
    }
  };

  const update = async (range: Omit<RoomThreadContextRangeInput, "title">) => {
    if (rootMessageId === null || context === null) return;
    setActionError(null);
    setNotice(null);
    try {
      const sourceId = range.source_conversation_id ?? sourceConversationId;
      const action = await actions.updateContext({
        ...range,
        expected_context_revision: context.revision,
        ...(context.moved && sourceId !== destinationConversationId ? { move: false } : {}),
        // Omitting move preserves the current moved state while the server
        // replaces the range atomically.
      });
      if (!action || !actions.isCurrent()) return;
      closeContextEditor();
      setNotice(t("context.saved"));
    } catch (error) {
      setActionError(reportActionError(error));
    }
  };

  const move = async () => {
    if (rootMessageId === null || context === null) return;
    setActionError(null);
    setNotice(null);
    try {
      const action = await actions.moveContext({
        expected_context_revision: context.revision,
      });
      if (!action || !actions.isCurrent()) return;
      setNotice(t("context.moved"));
    } catch (error) {
      setActionError(reportActionError(error));
    }
  };

  const returnToRoom = async () => {
    if (rootMessageId === null || context === null) return;
    setActionError(null);
    setNotice(null);
    try {
      const action = await actions.returnContext({
        expected_context_revision: context.revision,
      });
      if (!action || !actions.isCurrent()) return;
      setNotice(t("context.returned"));
    } catch (error) {
      setActionError(reportActionError(error));
    }
  };

  if (mode === "create") {
    return (
      <section className="my-3 rounded-lg border p-3">
        {!createOpen ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-tour="chat-room-thread-context"
            onClick={openCreateEditor}
          >
            {t("selectContext")}
          </Button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t("create.title")}</h3>
              <Button type="button" size="sm" variant="ghost" onClick={closeCreateEditor}>
                {t("range.cancel")}
              </Button>
            </div>
            <p className="text-muted-foreground text-sm">{t("create.description")}</p>
            <RoomThreadContextSourcePicker
              destinationConversationId={destinationConversationId}
              destinationTitle={destinationTitle}
              sourceConversationId={sourceConversationId}
              sourceTitle={readableSourceTitle}
              disabled={actions.isPending}
              onChange={(id, title) => {
                setSourceConversationId(id);
                setSourceTitle(title);
                setActionError(null);
              }}
            />
            <RoomThreadContextRangeSelector
              mode="create"
              sourceConversationId={sourceConversationId}
              sourceTitle={readableSourceTitle || undefined}
              messages={sourceRows}
              hasEarlier={source.hasNextPage ?? false}
              isLoading={source.isPending}
              isLoadingEarlier={source.isFetchingNextPage}
              isSaving={actions.isPending}
              error={actionError ?? sourceReadError}
              onLoadEarlier={() => void source.fetchNextPage()}
              onCancel={closeCreateEditor}
              onSubmit={create}
            />
          </div>
        )}
      </section>
    );
  }

  if (context === null) return null;

  const sameRoom = context.source_conversation_id === destinationConversationId;
  const canEdit = canManage && threadState !== "archived";
  const initialRange = sourceConversationId === context.source_conversation_id ? context : null;

  return (
    <section aria-label={t("context.title")} className="bg-muted/20 mb-4 rounded-xl border p-3">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">{t("context.title")}</h3>
          <p className="text-muted-foreground mt-1 text-xs">
            {t("context.range", { count: context.message_count })}
          </p>
          {!sameRoom && (
            <>
              <Link
                className="text-primary mt-1 inline-block text-xs underline-offset-4 hover:underline"
                href={`/chat?id=${encodeURIComponent(context.source_conversation_id)}`}
              >
                {readableSourceTitle
                  ? t("context.openSourceNamed", { title: readableSourceTitle })
                  : t("context.openSource")}
              </Link>
              <p className="text-muted-foreground mt-1 text-xs">{t("context.referenceOnly")}</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {canEdit && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={actions.isPending}
              onClick={() => {
                setActionError(null);
                setNotice(null);
                if (editing) closeContextEditor();
                else openContextEditor();
              }}
            >
              {editing ? t("range.cancel") : t("context.edit")}
            </Button>
          )}
          {canEdit && sameRoom && !context.moved && (
            <Button
              type="button"
              size="sm"
              disabled={actions.isPending || context.stale === true}
              onClick={() => void move()}
            >
              {actions.isPending ? t("context.saving") : t("moveIntoThread")}
            </Button>
          )}
          {canEdit && sameRoom && context.moved && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={actions.isPending || context.stale === true}
              onClick={() => void returnToRoom()}
            >
              {actions.isPending ? t("context.saving") : t("returnToRoom")}
            </Button>
          )}
        </div>
      </div>

      {displayRows.length > 0 ? (
        <ol className="mt-3 max-h-64 space-y-2 overflow-y-auto border-t pt-3">
          {displayRows.map((message) => (
            <li key={message.id} className="bg-background/60 rounded-md border p-2">
              <p className="text-muted-foreground mb-1 text-xs font-medium">
                {message.sender?.name ??
                  t(message.role === "user" ? "range.userMessage" : "range.assistantMessage")}
              </p>
              <p className="line-clamp-4 text-sm whitespace-pre-wrap">
                {message.content || t("range.attachmentOnly")}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted-foreground mt-3 border-t pt-3 text-sm">{t("context.empty")}</p>
      )}

      {context.stale === true && (
        <p role="status" className="text-muted-foreground mt-3 text-sm">
          {t("context.stale")}
        </p>
      )}

      {(actionError || sourceReadError || notice) && (
        <p
          role={actionError || sourceReadError ? "alert" : "status"}
          className={
            actionError || sourceReadError
              ? "text-destructive mt-3 text-sm"
              : "text-primary mt-3 text-sm"
          }
        >
          {actionError ?? sourceReadError ?? notice}
        </p>
      )}

      {editing && canEdit && (
        <div className="mt-3 space-y-3 border-t pt-3">
          <RoomThreadContextSourcePicker
            destinationConversationId={destinationConversationId}
            destinationTitle={destinationTitle}
            sourceConversationId={sourceConversationId}
            sourceTitle={readableSourceTitle || undefined}
            disabled={actions.isPending}
            onChange={(id, title) => {
              setSourceConversationId(id);
              setSourceTitle(title);
              setActionError(null);
            }}
          />
          {context.moved && sourceConversationId !== destinationConversationId && (
            <p className="text-muted-foreground text-sm">{t("context.returnMovedRangeOnSave")}</p>
          )}
          <RoomThreadContextRangeSelector
            mode="edit"
            sourceConversationId={sourceConversationId}
            sourceTitle={readableSourceTitle || undefined}
            messages={sourceRows}
            rootMessageId={rootMessageId}
            initial={initialRange}
            title={threadTitle}
            hasEarlier={source.hasNextPage ?? false}
            isLoading={
              source.isPending ||
              (sourceConversationId === context.source_conversation_id && candidates.isPending)
            }
            isLoadingEarlier={source.isFetchingNextPage}
            isSaving={actions.isPending}
            error={actionError ?? sourceReadError}
            onLoadEarlier={() => void source.fetchNextPage()}
            onCancel={closeContextEditor}
            onSubmit={update}
          />
        </div>
      )}
    </section>
  );
}
