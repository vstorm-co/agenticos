"use client";

import type { ReactNode } from "react";
import { Send } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Textarea } from "@/components/ui";
import { StartTeamRoom } from "@/components/projects/start-team-room";
import { useAgents } from "@/hooks/use-agents";
import { useProject } from "@/hooks/use-projects";
import { useRoomRequests } from "@/hooks/use-room";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { getErrorMessage } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import { ReplyingTo, ReplyQuote } from "./reply-quote";
import { TeamRoomQueue } from "./team-room-queue";
import { roomResponders, TeamRoomResponder } from "./team-room-responder";

interface RoomComposerProps {
  conversationId: string | null;
  projectId: string;
  readOnly: boolean;
  onTyping: () => void;
  actionsSlot?: ReactNode;
}

export function TeamRoomComposer(props: RoomComposerProps) {
  const draft = useRoomDraft(props.conversationId);
  return <RoomComposer {...props} draft={draft} />;
}

export function RoomComposer({
  conversationId,
  projectId,
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
  const { project, isLoading: loadingProject } = useProject(projectId);
  const { agents } = useAgents();
  const canPost = !readOnly && !requests.isError && requests.data?.can_post === true;
  if (conversationId === null) {
    return project?.can_use && !readOnly ? (
      <div className="py-3 text-center">
        <StartTeamRoom key={projectId} projectId={projectId} />
      </div>
    ) : (
      <p className="text-muted-foreground py-3 text-center text-xs">
        {t(loadingProject ? "checking" : "readOnly")}
      </p>
    );
  }
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
          draft={draft}
          agents={roomResponders(agents)}
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
  draft,
  agents,
  onTyping,
  actionsSlot,
  inThread,
}: {
  draft: ReturnType<typeof useRoomDraft>;
  agents: readonly Agent[];
  onTyping: () => void;
  actionsSlot?: ReactNode;
  inThread: boolean;
}) {
  const t = useTranslations("chat.teamRoom");
  const thread = useTranslations("chat.roomThread");
  const available = draft.agentId === null || agents.some((agent) => agent.id === draft.agentId);
  const canSend =
    !draft.sending && draft.content.trim().length > 0 && (draft.retrying || available);
  return (
    <form
      data-tour="chat-team-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSend) void draft.submit();
      }}
      className="panel composer-box min-w-0 rounded-2xl p-3 sm:p-4"
    >
      {draft.reply &&
        (draft.locked ? (
          <ReplyQuote reply={draft.reply} align="start" />
        ) : (
          <ReplyingTo reply={draft.reply} onCancel={draft.clearReply} />
        ))}
      <Textarea
        value={draft.content}
        onChange={(event) => {
          draft.setContent(event.target.value);
          onTyping();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (canSend) void draft.submit();
          }
        }}
        aria-label={inThread ? thread("message") : t("message")}
        placeholder={inThread ? thread("placeholder") : t("placeholder")}
        maxLength={20000}
        disabled={draft.locked}
        className="mb-3 min-h-20 resize-y border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
      {draft.error && (
        <p className="text-destructive mb-2 text-xs" role="alert">
          {draft.error}
        </p>
      )}
      {draft.retrying && <p className="text-muted-foreground mb-2 text-xs">{t("retryHint")}</p>}
      <div className="flex items-center justify-between gap-2">
        <TeamRoomResponder
          agents={agents}
          value={draft.agentId}
          onChange={draft.setAgentId}
          disabled={draft.locked}
        />
        <div className="flex items-center gap-2">
          {actionsSlot}
          <Button type="submit" size="sm" disabled={!canSend}>
            <Send className="size-3.5" aria-hidden />
            {draft.sending
              ? t("posting")
              : draft.retrying
                ? t("retryPost")
                : inThread
                  ? thread("post")
                  : t("post")}
          </Button>
        </div>
      </div>
      <p className="text-muted-foreground mt-2 text-xs">{t("responderHint")}</p>
    </form>
  );
}
