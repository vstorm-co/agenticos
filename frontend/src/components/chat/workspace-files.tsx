"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, FileText, FolderOpen, Info, X } from "lucide-react";

import { Button, Skeleton } from "@/components/ui";
import { useConversationFile, useConversationWorkspace } from "@/hooks";
import { cn } from "@/lib/utils";

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
 * agent keeps nothing — so it is a toggle in the corner now, and the count on it is
 * what tells somebody there is anything to open.
 *
 * `owner_label` is shown and is not decoration. Under `agent` scope one workspace is
 * shared by everybody who talks to that agent, so somebody opens a chat and finds a
 * file they never created — and without a line saying whose files these are, the
 * reasonable reading is that something leaked.
 */
export function WorkspaceFiles({ conversationId, revision }: WorkspaceFilesProps) {
  const { workspace, isLoading, error, refresh } = useConversationWorkspace(conversationId);
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState<string | null>(null);

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
      <div className="absolute top-3 right-3 z-10">
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <FolderOpen className="h-4 w-4" aria-hidden />
          Files
          {files.length > 0 && <span className="text-muted-foreground">{files.length}</span>}
        </Button>
      </div>
    );

  return (
    <aside className="border-border w-72 shrink-0 space-y-3 border-l p-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <FolderOpen className="h-4 w-4" aria-hidden />
            Files
          </p>
          <button
            type="button"
            aria-label="Close the file panel"
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
              <> · {size(workspace.bytes_total)} stored</>
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
        <p className="text-muted-foreground text-xs">
          Nothing yet. Files the agent writes, and anything you attach, appear here.
        </p>
      )}

      {files.length > 0 && (
        <ul className="space-y-0.5">
          {files.map((file) => (
            <li key={file.path}>
              <button
                type="button"
                onClick={() => setReading(reading === file.path ? null : file.path)}
                aria-expanded={reading === file.path}
                className={cn(
                  "hover:bg-accent/60 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left",
                  reading === file.path && "bg-accent",
                )}
              >
                <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate font-mono text-xs">{file.path}</span>
                <span className="text-muted-foreground shrink-0 text-[11px]">
                  {size(file.size)}
                </span>
              </button>
              {reading === file.path && (
                <FileContents conversationId={conversationId} path={file.path} />
              )}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

interface FileContentsProps {
  conversationId: string;
  path: string;
}

/**
 * One file, as text.
 *
 * Text only, which is the API's limit rather than this component's: a workspace can
 * hold a PNG an agent produced, and serving that would mean deciding content types
 * and disposition headers — a download path with its own threat model.
 */
function FileContents({ conversationId, path }: FileContentsProps) {
  const { file, isLoading, error } = useConversationFile(conversationId, path);

  if (isLoading) return <Skeleton className="mt-1 h-16 w-full" />;
  if (error !== null) return <p className="text-destructive mt-1 px-2 text-xs">{error}</p>;
  if (file === null) return null;

  return (
    <div className="mt-1 space-y-1">
      <pre className="bg-muted max-h-64 overflow-auto rounded-md p-2 text-[11px] whitespace-pre-wrap">
        {file.content}
      </pre>
      {file.truncated && (
        <p className="text-muted-foreground px-2 text-[11px]">
          Shortened. The agent reads the whole file.
        </p>
      )}
      <Button
        variant="ghost"
        size="sm"
        className="w-full"
        onClick={() => navigator.clipboard.writeText(file.content)}
      >
        Copy
      </Button>
    </div>
  );
}
