"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, FolderOpen, Info, X } from "lucide-react";

import { FileCard, FileViewer } from "@/components/files";
import { useConversationWorkspace } from "@/hooks";
import { useFilePreviewStore } from "@/stores";
import { getFileUrl } from "@/lib/file-api";
import { formatBytes } from "@/lib/utils";
import { workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import type { ConversationFile } from "@/lib/conversation-workspace-api";
import type { ChatMessageFile } from "@/types";

interface WorkspaceFilesProps {
  conversationId: string | null;
  /** Bumped when a turn ends, because a turn is what changes the files. */
  revision: number;
  /**
   * What people attached to this conversation, newest last.
   *
   * Listed beside what the agent wrote because "Files" in a chat means the files in
   * that chat, and somebody who has just dragged in a CSV looks for it here. Passed
   * in rather than fetched: the messages already carry their attachments, both live
   * and after a reload, so a request would be asking for what is on screen.
   *
   * They are also *not* the same thing as the workspace's `/uploads` copy. An agent
   * with a workspace gets one written there and can open it; an agent without one
   * gets nothing, and before this the panel had nothing to show either.
   */
  attachments: ChatMessageFile[];
}

/**
 * What the agent is keeping in this conversation, behind a button.
 *
 * **Closed by default, and that is the change.** A permanent third column took
 * space from the transcript in every conversation, including the ones where the
 * agent keeps nothing — so closed it is a strip holding one icon, and the count on
 * that icon is what says there is something to open.
 *
 * `owner_label` is shown and is not decoration. Under `agent` scope one workspace is
 * shared by everybody who talks to that agent, so somebody opens a chat and finds a
 * file they never created — and without a line saying whose files these are, the
 * reasonable reading is that something leaked.
 *
 * A file opens into the shared viewer rather than into a `<pre>` under its own row.
 * A 288-pixel column can list what the agent is keeping; it cannot show a report, a
 * chart or a PDF, and the panel used to answer "open this" with the first 60
 * characters of a line.
 */
export function WorkspaceFiles({ conversationId, revision, attachments }: WorkspaceFilesProps) {
  const t = useTranslations("chat.files");
  const { workspace, error, refresh } = useConversationWorkspace(conversationId);
  const openAttachment = useFilePreviewStore((state) => state.open);
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState<ConversationFile | null>(null);
  // The chat addresses files through its conversation, not through the workspace's
  // id: that route authorises by fetching the conversation, so somebody this chat
  // was shared with reaches the same files.
  const source = useMemo<FileSource | null>(
    () => (conversationId === null ? null : { kind: "conversation", id: conversationId }),
    [conversationId],
  );

  // Re-read when a turn ends rather than on a timer: the chat knows exactly when
  // the files could have changed, and a poll is wrong almost every time it fires.
  // In an effect and not during render - a refetch is a side effect, and React is
  // entitled to render this twice.
  useEffect(() => {
    void refresh();
  }, [revision, refresh]);

  if (conversationId === null) return null;

  // **Always drawn, once there is a conversation to draw it for.** It used to wait
  // for the listing to report a workspace, and the reasoning was about flicker: a
  // workspace has no row until a turn flushes one, so the button appeared as the id
  // arrived, vanished when the listing said `none`, and came back when the turn
  // ended - three states in one turn for a panel whose job is to sit still.
  //
  // Hiding it fixed the flicker by making the panel unreachable exactly when
  // somebody wants it. A turn that writes a file and then parks for approval has
  // not flushed anything, so the strip was absent for the whole time the file was
  // the thing on screen; a page reload was the only way to get it back. The same
  // gap swallowed uploads, which are written into the workspace before the agent
  // has done anything at all.
  //
  // A strip holding one icon costs 44 pixels and answers "does this agent keep
  // files" the moment somebody wonders. Flicker is solved where it belongs: the
  // count only appears once there is something to count, so the button itself never
  // changes shape.
  const files = workspace?.items.filter((file) => !file.is_dir) ?? [];

  // An attachment an agent *with* a workspace already holds is one file, not
  // two. `workspace_path` on the server names it from the first eight hex of the
  // file's id, so matching on that is exact rather than a guess about names - a
  // name match would collide the moment two people attach `report.csv`, which is
  // the case the id prefix exists to keep apart.
  //
  // Matched on the *last segment* rather than on a directory prefix: a listing
  // spells a path as the backend spells it - `./uploads/x` from a shell, `x`
  // from a glob, `/uploads/x` from a stored workspace - and a match anchored on
  // one of those showed the same file twice under the others (#1039).
  const stored = new Set(files.map((file) => file.path.split("/").filter(Boolean).pop() ?? ""));
  const unstored = attachments.filter((file) => {
    const prefix = file.id.replaceAll("-", "").slice(0, 8);
    return ![...stored].some((name) => name.startsWith(`${prefix}-`));
  });
  const count = files.length + unstored.length;

  if (!open)
    return (
      // A strip in the flow rather than something absolutely positioned over the
      // row: the sources and file-preview panels are columns on this same right
      // edge, and a floating button would sit on top of whichever one was open.
      <div className="border-border flex w-11 shrink-0 flex-col items-center border-l pt-3">
        <button
          type="button"
          aria-label={count === 0 ? t("show") : t("showWithCount", { count })}
          onClick={() => setOpen(true)}
          className="text-muted-foreground hover:text-foreground hover:bg-accent/60 relative rounded-md p-2"
        >
          <FolderOpen className="h-4 w-4" />
          {count > 0 && (
            <span className="bg-foreground text-background absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px]">
              {count}
            </span>
          )}
        </button>
      </div>
    );

  return (
    <aside className="border-border w-72 shrink-0 space-y-3 border-l p-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <FolderOpen className="h-4 w-4" aria-hidden />
            {t("title")}
          </p>
          <button
            type="button"
            aria-label={t("close")}
            onClick={() => setOpen(false)}
            className="text-muted-foreground hover:text-foreground rounded-md p-1"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {workspace !== null && workspace.backend !== "none" && (
          <p className="text-muted-foreground text-xs">
            {workspace.owner_label}
            {workspace.backend === "state" && workspace.bytes_total > 0 && (
              <> · {t("storedSuffix", { size: formatBytes(workspace.bytes_total) })}</>
            )}
          </p>
        )}
      </div>

      {error !== null && (
        <div className="text-destructive flex items-start gap-2 text-xs">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>{error}</p>
        </div>
      )}

      {/* Not red, and not beside "nothing yet". A host that keeps no files on disk
          is a configuration somebody chose, with a one-line fix this message names
          - and saying "no files" as well would be the second of two wrong answers. */}
      {workspace?.unreadable_reason != null && (
        <div className="text-muted-foreground flex items-start gap-2 text-xs">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>{workspace.unreadable_reason}</p>
        </div>
      )}

      {/* Two different answers, and they were one. "Nothing yet" is right for a
          workspace that is empty; for an agent that has none it describes a wait
          that will never end, since no turn is going to put a file there. */}
      {workspace !== null && workspace.unreadable_reason == null && count === 0 && (
        <p className="text-muted-foreground text-xs">
          {workspace.backend === "none" ? t("noWorkspace") : t("empty")}
        </p>
      )}

      {/* Tiles rather than rows. The name is what somebody scans for and the icon
          says what kind of thing it is before the name is read, which a 288-pixel
          column of monospace paths did not. */}
      {files.length > 0 && (
        <ul className="grid grid-cols-2 gap-2">
          {files.map((file) => (
            <li key={file.path}>
              <FileCard
                name={file.path.split("/").filter(Boolean).pop() ?? file.path}
                size={file.size}
                onOpen={() => setReading(file)}
                className="w-full"
              />
            </li>
          ))}
        </ul>
      )}

      {/* What people attached and the agent has no copy of. Its own group, under its
          own heading, because where a file came from changes what it means: the agent
          wrote the ones above and can read them back, while these are only in the
          chat - so an agent with no workspace can be *shown* one and cannot open it.
          Opened through the shared preview panel, which is what the attachment chips
          on the messages already use, rather than the workspace viewer that would
          have nothing to read. */}
      {unstored.length > 0 && (
        <div className="space-y-2">
          <p className="text-muted-foreground text-[11px] font-medium">{t("attached")}</p>
          <ul className="grid grid-cols-2 gap-2">
            {unstored.map((file) => (
              <li key={file.id}>
                <FileCard
                  name={file.filename}
                  mimeType={file.mime_type}
                  // An attachment is behind the same authenticated address the
                  // viewer reads it from, so the card can draw the picture rather
                  // than a grey glyph standing in for one. Nothing is fetched here
                  // - the browser loads what an `img` points at, and a chat holds
                  // a handful of attachments rather than a listing.
                  imageUrl={getFileUrl(file.id)}
                  onOpen={() => openAttachment(file)}
                  className="w-full"
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {source !== null && reading !== null && (
        <FileViewer
          file={{
            name: reading.path.split("/").filter(Boolean).pop() ?? reading.path,
            path: reading.path,
            size: reading.size,
            modifiedAt: reading.modified_at,
          }}
          access={workspaceFileAccess(source, reading.path)}
          onClose={() => setReading(null)}
        />
      )}
    </aside>
  );
}
