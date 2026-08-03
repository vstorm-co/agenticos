"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, FolderOpen, Info, X } from "lucide-react";

import { FileIcon } from "@/components/sandboxes/file-tile";
import { WorkspaceFileViewer } from "@/components/sandboxes/file-viewer";
import { Skeleton } from "@/components/ui";
import { useConversationWorkspace } from "@/hooks";
import type { FileSource } from "@/lib/workspace-files";

interface WorkspaceFilesProps {
  conversationId: string | null;
  /** Bumped when a turn ends, because a turn is what changes the files. */
  revision: number;
}

/** Bytes as a person reads them. */
function size(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
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
export function WorkspaceFiles({ conversationId, revision }: WorkspaceFilesProps) {
  const t = useTranslations("chat.files");
  const { workspace, isLoading, error, refresh } = useConversationWorkspace(conversationId);
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
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
  // An agent with no workspace is the default, so a button would be a permanent
  // control that opens an empty box.
  if (!isLoading && error === null && (workspace === null || workspace.backend === "none"))
    return null;

  const files = workspace?.items.filter((file) => !file.is_dir) ?? [];

  if (!open)
    return (
      // A strip in the flow rather than something absolutely positioned over the
      // row: the sources and file-preview panels are columns on this same right
      // edge, and a floating button would sit on top of whichever one was open.
      <div className="border-border flex w-11 shrink-0 flex-col items-center border-l pt-3">
        <button
          type="button"
          aria-label={files.length === 0 ? t("show") : t("showWithCount", { count: files.length })}
          onClick={() => setOpen(true)}
          className="text-muted-foreground hover:text-foreground hover:bg-accent/60 relative rounded-md p-2"
        >
          <FolderOpen className="h-4 w-4" />
          {files.length > 0 && (
            <span className="bg-foreground text-background absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px]">
              {files.length}
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
        {workspace !== null && (
          <p className="text-muted-foreground text-xs">
            {workspace.owner_label}
            {workspace.backend === "state" && workspace.bytes_total > 0 && (
              <> · {t("storedSuffix", { size: size(workspace.bytes_total) })}</>
            )}
          </p>
        )}
      </div>

      {isLoading && <Skeleton className="h-16 w-full" />}

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

      {workspace !== null && workspace.unreadable_reason == null && files.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("empty")}</p>
      )}

      {/* Tiles rather than rows. The name is what somebody scans for and the icon
          says what kind of thing it is before the name is read, which a 288-pixel
          column of monospace paths did not. */}
      {files.length > 0 && (
        <ul className="grid grid-cols-2 gap-2">
          {files.map((file) => (
            <li key={file.path}>
              <button
                type="button"
                onClick={() => setReading(file.path)}
                title={file.path}
                className="border-border hover:bg-accent/60 flex h-full w-full flex-col items-start gap-1.5 rounded-lg border p-2.5 text-left"
              >
                <FileIcon path={file.path} className="text-muted-foreground h-4 w-4" />
                <span className="w-full truncate font-mono text-[11px]">
                  {file.path.split("/").filter(Boolean).pop() ?? file.path}
                </span>
                <span className="text-muted-foreground text-[10px]">{size(file.size)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {source !== null && reading !== null && (
        <WorkspaceFileViewer source={source} path={reading} onClose={() => setReading(null)} />
      )}
    </aside>
  );
}
