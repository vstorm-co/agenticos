"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { MessageCircleQuestion, Paperclip, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Textarea } from "@/components/ui";
import { AttachmentCard, PendingAttachmentCard } from "./attachment-card";
import { AttachmentRow } from "./attachment-row";
import { FileDropOverlay } from "@/components/files";
import { StartTeamRoom } from "@/components/projects/start-team-room";
import { useAgents } from "@/hooks/use-agents";
import { useFileDrop } from "@/hooks/use-file-drop";
import { useProject } from "@/hooks/use-projects";
import { useRoomRequests } from "@/hooks/use-room";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { useRoomLeadPolicy } from "@/hooks/use-room-routing";
import { useAddRoomParticipant, useRoomMentionables } from "@/hooks/use-room-participants";
import { getErrorMessage } from "@/lib/api-error";
import { clientId } from "@/lib/ids";
import { CHAT_FILE_ACCEPT } from "@/lib/chat-file-accept";
import { uploadFile } from "@/lib/file-api";
import { matchingRoomMentionables, roomMentionAt } from "@/lib/room-mentions";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import type { RoomMentionQuery } from "@/lib/room-mentions";
import type { RoomParticipantRead } from "@/types/room";
import type { RoomLeadPolicy } from "@/types/room-routing";
import { ReplyingTo, ReplyQuote } from "./reply-quote";
import { TeamRoomQueue } from "./team-room-queue";
import { RoomMentionPalette } from "./room-mention-palette";
import { toast } from "sonner";

interface TeamRoomComposerProps {
  conversationId: string | null;
  projectId: string | null;
  readOnly: boolean;
  onTyping: () => void;
  actionsSlot?: ReactNode;
  consumeInitialContent?: () => string;
  onRoomCreated?: (roomId: string, projectId: string) => boolean;
}

interface RoomComposerProps {
  conversationId: string;
  allowLead?: boolean;
  readOnly: boolean;
  onTyping: () => void;
  actionsSlot?: ReactNode;
}

const MAX_ROOM_ATTACHMENTS = 10;

export function TeamRoomComposer(props: TeamRoomComposerProps) {
  const draft = useRoomDraft(props.conversationId);
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || props.conversationId === null) return;
    seeded.current = true;
    const initialContent = props.consumeInitialContent?.() ?? "";
    if (initialContent && draft.content.length === 0) draft.setContent(initialContent);
  }, [draft.content, draft.setContent, props.conversationId, props.consumeInitialContent]);
  if (props.conversationId === null) {
    return props.projectId === null ? (
      <RoomWithoutProject />
    ) : (
      <ProjectRoomEmptyState
        projectId={props.projectId}
        readOnly={props.readOnly}
        onRoomCreated={props.onRoomCreated}
      />
    );
  }
  return (
    <RoomComposer
      conversationId={props.conversationId}
      allowLead={props.projectId !== null}
      readOnly={props.readOnly}
      onTyping={props.onTyping}
      actionsSlot={props.actionsSlot}
      draft={draft}
    />
  );
}

function RoomWithoutProject() {
  const t = useTranslations("chat.teamRoom");
  return <p className="text-muted-foreground py-3 text-center text-xs">{t("readOnly")}</p>;
}

function ProjectRoomEmptyState({
  projectId,
  readOnly,
  onRoomCreated,
}: {
  projectId: string;
  readOnly: boolean;
  onRoomCreated?: (roomId: string, projectId: string) => boolean;
}) {
  const t = useTranslations("chat.teamRoom");
  const projectQuery = useProject(projectId);
  return projectQuery.project?.can_use && !readOnly ? (
    <div className="py-3 text-center">
      <StartTeamRoom
        key={projectId}
        projectId={projectId}
        onCreated={onRoomCreated ? (roomId) => onRoomCreated(roomId, projectId) : undefined}
      />
    </div>
  ) : (
    <p className="text-muted-foreground py-3 text-center text-xs">
      {t(projectQuery.isLoading ? "checking" : "readOnly")}
    </p>
  );
}

export function RoomComposer({
  conversationId,
  allowLead = false,
  readOnly,
  onTyping,
  actionsSlot,
  draft,
  threadRootMessageId = null,
}: RoomComposerProps & {
  draft: ReturnType<typeof useRoomDraft>;
  threadRootMessageId?: string | null;
}) {
  const t = useTranslations("chat.teamRoom");
  const tErrors = useTranslations("errors");
  const requests = useRoomRequests(conversationId);
  const leadPolicy = useRoomLeadPolicy(allowLead ? conversationId : null);
  const { agents } = useAgents();
  const canPost = !readOnly && !requests.isError && requests.data?.can_post === true;
  return (
    <div>
      <TeamRoomQueue
        conversationId={conversationId}
        requests={(requests.data?.items ?? []).filter(
          (request) => (request.thread_root_message_id ?? null) === threadRootMessageId,
        )}
        agents={agents}
        canPost={canPost}
      />
      {requests.isError ? (
        <div
          role="alert"
          className="text-destructive flex items-center justify-between gap-2 p-3 text-xs"
        >
          <span>{getErrorMessage(requests.error, tErrors, t("loadFailed"))}</span>
          <Button size="sm" variant="ghost" onClick={() => void requests.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : requests.isPending ? (
        <p className="text-muted-foreground p-3 text-center text-xs" role="status">
          {t("checking")}
        </p>
      ) : !canPost ? (
        <p className="text-muted-foreground p-3 text-center text-xs">{t("readOnly")}</p>
      ) : (
        <TeamRoomForm
          conversationId={conversationId}
          draft={draft}
          allowLead={allowLead}
          leadPolicy={leadPolicy.data}
          onTyping={onTyping}
          actionsSlot={actionsSlot}
          inThread={threadRootMessageId !== null}
        />
      )}
      {!canPost && actionsSlot && (
        <div className="hidden justify-end px-4 lg:flex">{actionsSlot}</div>
      )}
    </div>
  );
}

function TeamRoomForm({
  conversationId,
  draft,
  allowLead,
  onTyping,
  actionsSlot,
  inThread,
  leadPolicy,
}: {
  conversationId: string;
  draft: ReturnType<typeof useRoomDraft>;
  allowLead: boolean;
  onTyping: () => void;
  actionsSlot?: ReactNode;
  inThread: boolean;
  leadPolicy?: RoomLeadPolicy;
}) {
  const t = useTranslations("chat.teamRoom");
  const tParticipants = useTranslations("chat.roomParticipants");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const thread = useTranslations("chat.roomThread");
  const routing = useTranslations("chat.roomRouting");
  const tInput = useTranslations("chat.input");
  const { chatMaxUploadSizeMb } = usePublicConfig();
  const { mentionables, isLoading, error, refetch } = useRoomMentionables(conversationId);
  const addParticipant = useAddRoomParticipant(conversationId);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const mentionEditBeforeInput = useRef<{
    content: string;
    selectionStart: number;
    selectionEnd: number;
    inputType: string;
  } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const caretAfterPick = useRef<number | null>(null);
  const mentionListId = useId();
  const [mentionQuery, setMentionQuery] = useState<RoomMentionQuery | null>(null);
  const [pendingAdd, setPendingAdd] = useState<{
    participant: RoomParticipantRead;
    query: RoomMentionQuery;
  } | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const askingLead = draft.intent === "ask_lead";
  const hasAgentMentions = draft.roomMentions.some((mention) => mention.kind === "agent");
  const available = !askingLead || (allowLead && leadPolicy?.can_ask === true && !hasAgentMentions);
  const isUploading = draft.pendingUploads.length > 0;
  const canSend =
    !draft.sending &&
    !isUploading &&
    draft.uploadError === null &&
    (draft.content.trim().length > 0 || draft.attachments.length > 0) &&
    (draft.retrying || available);

  async function uploadFiles(files: File[]) {
    if (draft.locked || draft.pendingUploads.length > 0 || files.length === 0) return;
    const remaining = Math.max(
      0,
      MAX_ROOM_ATTACHMENTS - draft.attachments.length - draft.pendingUploads.length,
    );
    if (files.length > remaining) {
      toast.error(t("attachmentLimit", { max: MAX_ROOM_ATTACHMENTS }));
    }
    const candidates = files.slice(0, remaining);
    const accepted = candidates.filter((file) => {
      if (file.size <= chatMaxUploadSizeMb * 1024 * 1024) return true;
      toast.error(tInput("fileTooLarge", { file: file.name, max: chatMaxUploadSizeMb }));
      return false;
    });
    if (accepted.length === 0) return;

    const queued = accepted.map((file) => ({
      id: clientId(),
      name: file.name,
      size: file.size,
    }));
    if (!draft.beginUploads(queued)) return;

    for (const [index, file] of accepted.entries()) {
      const pending = queued[index]!;
      if (!draft.canContinueUpload()) {
        const remaining = queued.slice(index);
        const message = t("uploadStopped");
        for (const upload of remaining) draft.failUpload(upload.id, message);
        return;
      }
      try {
        const uploaded = await uploadFile(file);
        draft.completeUpload(pending.id, uploaded);
      } catch (failure) {
        const message = `${file.name}: ${getErrorMessage(failure, tErrors, tInput("uploadFailed"))}`;
        if (draft.failUpload(pending.id, message)) toast.error(message);
      }
    }
  }

  const drop = useFileDrop({
    onFiles: (files) => void uploadFiles(files),
    disabled: draft.locked || isUploading,
  });
  const mentionMatches = useMemo(
    () =>
      mentionQuery === null
        ? []
        : matchingRoomMentionables(
            askingLead ? mentionables.filter((item) => item.kind === "user") : mentionables,
            mentionQuery.query,
          ),
    [askingLead, mentionables, mentionQuery],
  );
  const mentionOpen = mentionQuery !== null && draft.content.length > 0;
  const mentionSelectionKey = JSON.stringify([
    mentionOpen,
    mentionQuery?.start ?? null,
    mentionQuery?.query ?? null,
    mentionMatches.map(({ kind, id }) => [kind, id]),
  ]);
  const [mentionSelection, setMentionSelection] = useState({ key: mentionSelectionKey, index: 0 });
  if (mentionSelection.key !== mentionSelectionKey) {
    setMentionSelection({ key: mentionSelectionKey, index: 0 });
  }
  const mentionIndex = mentionSelection.key === mentionSelectionKey ? mentionSelection.index : 0;
  const selectMentionIndex = (index: number) =>
    setMentionSelection({ key: mentionSelectionKey, index });
  useLayoutEffect(() => {
    if (caretAfterPick.current === null) return;
    const caret = caretAfterPick.current;
    caretAfterPick.current = null;
    textarea.current?.focus();
    textarea.current?.setSelectionRange(caret, caret);
  }, [draft.content]);

  function placeMention(participant: RoomParticipantRead, query: RoomMentionQuery) {
    caretAfterPick.current = draft.pickMention(query, participant);
    setMentionQuery(null);
    setPendingAdd(null);
    setAddError(null);
  }

  function pickMention(participant: RoomParticipantRead) {
    if (mentionQuery === null) return;
    if (!participant.is_member && participant.can_add) {
      setAddError(null);
      setPendingAdd({ participant, query: mentionQuery });
      return;
    }
    if (participant.can_mention) placeMention(participant, mentionQuery);
  }

  async function addAndMention() {
    if (pendingAdd === null) return;
    setAddError(null);
    try {
      const added = await addParticipant.add({
        kind: pendingAdd.participant.kind,
        id: pendingAdd.participant.id,
      });
      if (added !== null) placeMention(added, pendingAdd.query);
    } catch (failure) {
      setAddError(getErrorMessage(failure, tErrors, t("mentionAddFailed")));
    }
  }

  const submit = () => {
    if (canSend)
      void draft.submit(askingLead && leadPolicy?.can_ask ? leadPolicy.revision : undefined);
  };
  return (
    <form
      data-tour="chat-team-composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="panel composer-box min-w-0 rounded-2xl p-3 sm:p-4"
    >
      <FileDropOverlay
        active={drop.isDragging}
        title={tInput("dropFilesAttach")}
        hint={tInput("dropMaxSize", { max: chatMaxUploadSizeMb })}
      />
      {(draft.attachments.length > 0 || draft.pendingUploads.length > 0) && (
        <AttachmentRow count={draft.attachments.length + draft.pendingUploads.length}>
          {draft.attachments.map((file) => (
            <AttachmentCard
              key={file.id}
              file={file}
              onRemove={draft.locked ? undefined : () => draft.removeAttachment(file.id)}
            />
          ))}
          {draft.pendingUploads.map((file) => (
            <PendingAttachmentCard key={file.id} name={file.name} size={file.size} />
          ))}
        </AttachmentRow>
      )}
      {draft.reply &&
        (draft.locked ? (
          <ReplyQuote reply={draft.reply} align="start" />
        ) : (
          <ReplyingTo reply={draft.reply} onCancel={draft.clearReply} />
        ))}
      <Textarea
        ref={textarea}
        value={draft.content}
        onBeforeInput={(event) => {
          const target = event.currentTarget;
          const input = event.nativeEvent as InputEvent;
          mentionEditBeforeInput.current = {
            content: target.value,
            selectionStart: target.selectionStart,
            selectionEnd: target.selectionEnd,
            inputType: input.inputType,
          };
        }}
        onChange={(event) => {
          const next = event.currentTarget.value;
          const caret = event.currentTarget.selectionStart;
          const selectionEnd = event.currentTarget.selectionEnd;
          const beforeInput = mentionEditBeforeInput.current;
          mentionEditBeforeInput.current = null;
          draft.setContent(next, {
            caret,
            selectionEnd,
            ...(beforeInput?.content === draft.content
              ? {
                  previousSelectionStart: beforeInput.selectionStart,
                  previousSelectionEnd: beforeInput.selectionEnd,
                  inputType: beforeInput.inputType,
                }
              : {}),
          });
          setMentionQuery(roomMentionAt(next, caret, selectionEnd));
          setPendingAdd(null);
          onTyping();
        }}
        onPaste={(event) => {
          const files = Array.from(event.clipboardData.files);
          if (files.length === 0) return;
          event.preventDefault();
          void uploadFiles(files);
        }}
        onKeyDown={(event) => {
          // A key that did not produce input must not leave its beforeinput snapshot
          // available for a later edit. The matching beforeinput below refreshes it.
          mentionEditBeforeInput.current = null;
          if (mentionOpen) {
            if (event.key === "ArrowDown" && mentionMatches.length > 0) {
              event.preventDefault();
              selectMentionIndex((mentionIndex + 1) % mentionMatches.length);
              return;
            }
            if (event.key === "ArrowUp" && mentionMatches.length > 0) {
              event.preventDefault();
              selectMentionIndex(
                (mentionIndex - 1 + mentionMatches.length) % mentionMatches.length,
              );
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setMentionQuery(null);
              setPendingAdd(null);
              return;
            }
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              const selected = mentionMatches[mentionIndex];
              if (selected) {
                event.preventDefault();
                pickMention(selected);
                return;
              }
            }
          }
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        aria-label={inThread ? thread("message") : t("message")}
        placeholder={inThread ? thread("placeholder") : t("placeholder")}
        aria-expanded={mentionOpen}
        aria-controls={mentionOpen ? mentionListId : undefined}
        aria-activedescendant={
          mentionOpen && mentionMatches.length > 0 ? `${mentionListId}-${mentionIndex}` : undefined
        }
        maxLength={20000}
        disabled={draft.locked || pendingAdd !== null}
        className="mb-3 min-h-20 resize-y border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
      {mentionOpen && (
        <RoomMentionPalette
          id={mentionListId}
          items={mentionMatches}
          selectedIndex={mentionIndex}
          onSelectIndex={selectMentionIndex}
          onPick={pickMention}
          isLoading={isLoading}
          failed={error !== null}
          onRetry={() => void refetch()}
        />
      )}
      {pendingAdd !== null && (
        <div
          className="border-border/70 bg-background mb-3 rounded-lg border p-3"
          role="alertdialog"
        >
          <p className="text-sm font-medium">
            {tParticipants("historyRoomTitle", { name: pendingAdd.participant.name })}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {tParticipants("historyRoomDescription", { name: pendingAdd.participant.name })}
          </p>
          {addError && (
            <p className="text-destructive mt-2 text-xs" role="alert">
              {addError}
            </p>
          )}
          <div className="mt-3 flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setPendingAdd(null)}>
              {tCommon("cancel")}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={addParticipant.isAdding}
              onClick={() => void addAndMention()}
            >
              {addParticipant.isAdding ? t("addingAndMention") : t("addAndMention")}
            </Button>
          </div>
        </div>
      )}
      {draft.uploadError && (
        <div
          className="text-destructive mb-2 flex items-center justify-between gap-2 text-xs"
          role="alert"
        >
          <span>{draft.uploadError}</span>
          <Button type="button" size="sm" variant="ghost" onClick={draft.clearUploadError}>
            {t("discardFailedUpload")}
          </Button>
        </div>
      )}
      {draft.error && (
        <p className="text-destructive mb-2 text-xs" role="alert">
          {draft.error}
        </p>
      )}
      {draft.retrying && <p className="text-muted-foreground mb-2 text-xs">{t("retryHint")}</p>}
      <div className="flex items-center justify-between gap-2">
        {(allowLead || askingLead) && (
          <Button
            type="button"
            size="sm"
            variant={askingLead ? "secondary" : "ghost"}
            disabled={
              draft.locked ||
              (!askingLead && (!allowLead || !leadPolicy?.can_ask || hasAgentMentions))
            }
            aria-pressed={askingLead}
            onClick={() => (askingLead ? draft.setMessageIntent() : draft.setAskLead())}
          >
            <MessageCircleQuestion className="size-3.5" aria-hidden />
            {routing("askLead")}
          </Button>
        )}
        <div className="flex items-center gap-2">
          {actionsSlot}
          <input
            ref={fileInput}
            type="file"
            accept={CHAT_FILE_ACCEPT}
            multiple
            disabled={draft.locked || isUploading}
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              void uploadFiles(files);
            }}
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            disabled={draft.locked || isUploading}
            onClick={() => fileInput.current?.click()}
            aria-label={tInput("attachFile")}
            title={tInput("attachFile")}
          >
            <Paperclip className="size-4" aria-hidden />
          </Button>
          <Button type="submit" size="sm" disabled={!canSend}>
            <Send className="size-3.5" aria-hidden />
            {draft.sending
              ? t("posting")
              : draft.retrying
                ? t("retryPost")
                : askingLead
                  ? routing("askLead")
                  : inThread
                    ? thread("post")
                    : t("post")}
          </Button>
        </div>
      </div>
      {hasAgentMentions && (
        <p className="text-muted-foreground mt-2 text-xs">{t("askLeadAgentConflict")}</p>
      )}
      {!askingLead && <p className="text-muted-foreground mt-2 text-xs">{t("mentionHint")}</p>}
      {askingLead && allowLead && (
        <p className="text-muted-foreground mt-1 text-xs">
          {routing(leadPolicy?.lead?.current === false ? "pinnedLeadHint" : "askLeadHint")}
        </p>
      )}
    </form>
  );
}
