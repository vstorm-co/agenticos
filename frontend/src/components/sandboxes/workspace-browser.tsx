"use client";

import { useMemo, useState } from "react";
import { Download } from "lucide-react";

import { Badge, Button, DataTable, ListCard, Skeleton, type Column } from "@/components/ui";
import Link from "next/link";

import { FileIcon, FileViewer } from "@/components/files";
import { useAllWorkspaceFiles, useSandboxWorkspaces } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { workspaceFileAccess } from "@/lib/workspace-files";
import { formatBytes } from "@/lib/utils";
import type { FlatFile, WorkspaceSummary } from "@/lib/sandbox-workspaces-api";
import { useTranslations } from "next-intl";

/** One file's identity across workspaces: the same path exists in several. */
function key(file: { workspace_id: string; path: string }): string {
  return `${file.workspace_id}${file.path}`;
}

/** When it was last touched, roughly. */
function used(when: string | null, t: (key: string, values?: Record<string, number>) => string) {
  if (when === null) return t("usedNever");
  const days = Math.floor((Date.now() - new Date(when).getTime()) / 86_400_000);
  if (days <= 0) return t("usedToday");
  if (days === 1) return t("usedYesterday");
  return t("usedDaysAgo", { days });
}

/**
 * The workspaces this reader can see, and the files in one.
 *
 * A workspace is scratch space, so a list of them is a list of what the agents are
 * *holding* — which is the question this answers and the conversation panel cannot:
 * a `run`-scoped workspace never had a conversation and an `agent`-scoped one
 * belongs to all of them, so neither is reachable from a chat.
 *
 * Which workspaces appear is the backend's decision, not this component's: an
 * operator sees the organization's, and everybody else sees the ones they are part
 * of. That is why this is no longer gated in the nav — a person's own files are not
 * an operator surface.
 *
 * `access_label` is a column and not decoration. Under `agent` scope one workspace
 * is shared by everybody who talks to that agent, and a table of paths with no
 * statement of who can see them is the wrong thing to hand somebody auditing this.
 */
export function WorkspaceBrowser() {
  const t = useTranslations("sandboxes.workspaces");
  const { workspaces, isLoading, error } = useSandboxWorkspaces();
  const [flat, setFlat] = useState(false);

  const columns = useMemo<Column<WorkspaceSummary>[]>(
    () => [
      {
        key: "agent",
        header: t("agent"),
        sortable: true,
        sortValue: (workspace) => workspace.agent_name,
        cell: (workspace) => <span className="font-medium">{workspace.agent_name}</span>,
      },
      {
        key: "conversation",
        header: t("conversation"),
        cell: (workspace) => (
          <span className="text-muted-foreground block max-w-48 truncate text-xs">
            {/* A conversation-scoped workspace has exactly one chat; a
                shared one has however many the agent has answered in,
                and that number is the difference between "my files" and
                "everybody's". */}
            {workspace.conversation_title ??
              (workspace.conversations > 0
                ? t("conversationCount", { count: workspace.conversations })
                : "—")}
          </span>
        ),
      },
      {
        key: "whoCanSeeIt",
        header: t("whoCanSeeIt"),
        cell: (workspace) => (
          <span className="text-muted-foreground text-xs">{workspace.access_label}</span>
        ),
      },
      {
        key: "backend",
        header: t("backend"),
        cell: (workspace) => (
          <Badge variant="outline">{workspace.backend === "state" ? "stored" : "container"}</Badge>
        ),
      },
      {
        key: "size",
        header: t("size"),
        sortable: true,
        sortValue: (workspace) => (workspace.backend === "state" ? workspace.bytes_total : null),
        cell: (workspace) => (
          <span className="text-muted-foreground text-xs">
            {/* Only meaningful for a stored workspace: a container's
                files are on its host volume and this column is the
                JSONB document's size. */}
            {workspace.backend === "state" ? formatBytes(workspace.bytes_total) : t("host")}
          </span>
        ),
      },
      {
        key: "lastUsed",
        header: t("lastUsed"),
        cell: (workspace) => (
          <span className="text-muted-foreground text-xs">{used(workspace.last_used_at, t)}</span>
        ),
      },
      {
        key: "files",
        header: t("files"),
        align: "right",
        cell: (workspace) => (
          /* A page, not a panel below the table. A workspace with a
             `skills/` directory is a tree, and it is worth having a
             URL somebody can send. */
          <Button variant="ghost" size="sm" asChild>
            <Link
              href={ROUTES.WORKSPACE_DETAIL(workspace.id)}
              aria-label={t("filesOf", { agent: workspace.agent_name })}
            >
              {t("open")}
            </Link>
          </Button>
        ),
      },
    ],
    [t],
  );

  return (
    <div className="space-y-4">
      <ListCard
        title={t("workspacesHeading")}
        counted={isLoading ? null : t("whatAgentsAreKeeping")}
        controls={
          /* Two questions, not two designs: "which workspaces exist" is a table
             of rows, and "who is holding a copy of that CSV" is a flat list of
             files. The second cannot be answered by opening the first one row at
             a time, which is what this exists for. */
          <div className="flex shrink-0 gap-1">
            <Button
              variant={flat ? "ghost" : "secondary"}
              size="sm"
              aria-pressed={!flat}
              onClick={() => setFlat(false)}
            >
              {t("byWorkspace")}
            </Button>
            <Button
              variant={flat ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={flat}
              onClick={() => setFlat(true)}
            >
              {t("allFiles")}
            </Button>
          </div>
        }
        contentClassName="p-0"
      >
        {flat ? (
          <FlatFiles />
        ) : (
          <DataTable<WorkspaceSummary>
            columns={columns}
            rows={workspaces}
            getRowKey={(workspace) => workspace.id}
            loading={isLoading}
            error={error}
            empty={t("noAgentKeepingFiles")}
            className="rounded-none border-0 bg-transparent"
          />
        )}
      </ListCard>
    </div>
  );
}

/**
 * Every file at once, with the workspace each came from named beside it.
 *
 * The bound and the failures are shown rather than logged: a shorter list reads as
 * fewer files, so "we stopped looking" and "one host did not answer" have to be on
 * screen or the list is quietly a lie.
 */
function FlatFiles() {
  const t = useTranslations("sandboxes");
  const tc = useTranslations("common");
  const { listing, isLoading, error } = useAllWorkspaceFiles(true);
  const [opened, setOpened] = useState<FlatFile | null>(null);

  if (isLoading) return <Skeleton className="m-5 h-24" />;
  if (error !== null) return <p className="text-destructive px-5 py-4 text-sm">{error}</p>;
  if (listing === null) return null;

  if (listing.items.length === 0)
    return (
      <p className="text-muted-foreground px-5 py-8 text-center text-sm">
        {t("noAgentHoldingFile")}
      </p>
    );

  return (
    <div className="space-y-3 p-5">
      {/* Tiles rather than rows, and each one carries the thing a row could not:
          the icon for what kind of file it is, the agent holding it, who else can
          see it, and a way to get it onto this machine. */}
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {listing.items.map((file) => (
          <li key={key(file)} className="border-border rounded-lg border">
            <div className="flex items-start gap-2 p-3">
              <FileIcon
                name={file.path}
                className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0"
              />
              <div className="min-w-0 flex-1 space-y-1">
                {/* The path opens the file, here, rather than only linking to the
                    workspace it lives in - "who is holding a copy of that CSV" is
                    usually followed by "what is in it". The workspace is one click
                    away on the line below, for the times it is not. */}
                <button
                  type="button"
                  onClick={() => setOpened(file)}
                  className="block w-full truncate text-left font-mono text-xs hover:underline"
                  title={file.path}
                >
                  {file.path}
                </button>
                <p className="text-muted-foreground truncate text-[11px]">
                  <Link
                    href={ROUTES.WORKSPACE_DETAIL(file.workspace_id)}
                    className="hover:underline"
                  >
                    {file.agent_name}
                  </Link>{" "}
                  · {file.access_label} · {file.size == null ? "—" : formatBytes(file.size)}
                </p>
              </div>
              <button
                type="button"
                aria-label={tc("downloadNamed", { name: file.path })}
                onClick={() =>
                  void workspaceFileAccess(
                    { kind: "workspace", id: file.workspace_id },
                    file.path,
                  ).download()
                }
                className="text-muted-foreground hover:text-foreground shrink-0 rounded-md p-1"
              >
                <Download className="h-3.5 w-3.5" />
              </button>
            </div>
          </li>
        ))}
      </ul>
      {opened !== null && (
        <FileViewer
          file={{
            name: opened.path.split("/").filter(Boolean).pop() ?? opened.path,
            path: opened.path,
            size: opened.size,
          }}
          access={workspaceFileAccess({ kind: "workspace", id: opened.workspace_id }, opened.path)}
          onClose={() => setOpened(null)}
        />
      )}
      {(listing.truncated || listing.unreadable > 0) && (
        <p className="text-muted-foreground text-xs">
          {listing.truncated && t("readSoManyWorkspaces", { count: listing.workspaces_read })}
          {listing.unreadable > 0 && t("someUnreadable", { count: listing.unreadable })}
        </p>
      )}
    </div>
  );
}
