"use client";

import { useState } from "react";
import { AlertTriangle, FileText, FolderOpen } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";
import {
  useAllWorkspaceFiles,
  useSandboxWorkspaces,
  useWorkspaceFile,
  useWorkspaceFiles,
} from "@/hooks";
import type { WorkspaceSummary } from "@/lib/sandbox-workspaces-api";

/** Bytes as a person reads them. */
function size(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** When it was last touched, roughly. */
function used(when: string | null): string {
  if (when === null) return "never";
  const days = Math.floor((Date.now() - new Date(when).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
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
  const { workspaces, isLoading, error } = useSandboxWorkspaces();
  const [opened, setOpened] = useState<WorkspaceSummary | null>(null);
  const [flat, setFlat] = useState(false);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0 border-b px-5 py-4">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-sm">
              <FolderOpen className="h-4 w-4" aria-hidden />
              Workspaces
            </CardTitle>
            <CardDescription className="text-xs">
              What the agents are keeping. A workspace is scratch space — it is deleted with the
              conversation it belongs to, and is not a place to store anything durable.
            </CardDescription>
          </div>
          {/* Two questions, not two designs: "which workspaces exist" is a table
              of rows, and "who is holding a copy of that CSV" is a flat list of
              files. The second cannot be answered by opening the first one row at
              a time, which is what this exists for. */}
          <div className="flex shrink-0 gap-1">
            <Button
              variant={flat ? "ghost" : "secondary"}
              size="sm"
              aria-pressed={!flat}
              onClick={() => setFlat(false)}
            >
              By workspace
            </Button>
            <Button
              variant={flat ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={flat}
              onClick={() => setFlat(true)}
            >
              All files
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {flat && <FlatFiles />}

          {!flat && isLoading && (
            <div className="space-y-3 p-5">
              {[0, 1].map((row) => (
                <Skeleton key={row} className="h-10 w-full" />
              ))}
            </div>
          )}

          {!flat && error !== null && <p className="text-destructive px-5 py-4 text-sm">{error}</p>}

          {!flat && !isLoading && error === null && workspaces.length === 0 && (
            <p className="text-muted-foreground px-5 py-8 text-center text-sm">
              No agent is keeping files yet. One appears here the first time an agent with a
              workspace writes something.
            </p>
          )}

          {!flat && workspaces.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>Conversation</TableHead>
                    <TableHead>Who can see it</TableHead>
                    <TableHead>Backend</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Last used</TableHead>
                    <TableHead className="text-right">Files</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workspaces.map((workspace) => (
                    <TableRow key={workspace.id}>
                      <TableCell className="font-medium">{workspace.agent_name}</TableCell>
                      <TableCell className="text-muted-foreground max-w-48 truncate text-xs">
                        {/* A conversation-scoped workspace has exactly one chat; a
                            shared one has however many the agent has answered in,
                            and that number is the difference between "my files" and
                            "everybody's". */}
                        {workspace.conversation_title ??
                          (workspace.conversations > 0
                            ? `${workspace.conversations} conversations`
                            : "—")}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {workspace.access_label}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {workspace.backend === "state" ? "stored" : "container"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {/* Only meaningful for a stored workspace: a container's
                            files are on its host volume and this column is the
                            JSONB document's size. */}
                        {workspace.backend === "state"
                          ? size(workspace.bytes_total)
                          : "on the host"}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {used(workspace.last_used_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Files of ${workspace.agent_name}`}
                          onClick={() => setOpened(opened?.id === workspace.id ? null : workspace)}
                        >
                          {opened?.id === workspace.id ? "Hide" : "Open"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {!flat && opened !== null && <WorkspaceFilesCard workspace={opened} />}
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
  const { listing, isLoading, error } = useAllWorkspaceFiles(true);

  if (isLoading) return <Skeleton className="m-5 h-24" />;
  if (error !== null) return <p className="text-destructive px-5 py-4 text-sm">{error}</p>;
  if (listing === null) return null;

  if (listing.items.length === 0)
    return (
      <p className="text-muted-foreground px-5 py-8 text-center text-sm">
        No agent is holding a file yet.
      </p>
    );

  return (
    <div className="space-y-3 p-5">
      <ul className="divide-border divide-y text-sm">
        {listing.items.map((file) => (
          <li
            key={`${file.workspace_id}${file.path}`}
            className="flex items-center justify-between gap-3 py-2"
          >
            <span className="flex min-w-0 items-center gap-2">
              <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate font-mono text-xs">{file.path}</span>
            </span>
            <span className="flex shrink-0 items-center gap-3 text-xs">
              <span className="font-medium">{file.agent_name}</span>
              <span className="text-muted-foreground">{file.access_label}</span>
              <span className="text-muted-foreground">{size(file.size)}</span>
            </span>
          </li>
        ))}
      </ul>
      {(listing.truncated || listing.unreadable > 0) && (
        <p className="text-muted-foreground text-xs">
          {listing.truncated && `Read ${listing.workspaces_read} workspaces — there are more. `}
          {listing.unreadable > 0 &&
            `${listing.unreadable} could not be read; their host may be down.`}
        </p>
      )}
    </div>
  );
}

interface WorkspaceFilesCardProps {
  workspace: WorkspaceSummary;
}

/**
 * One workspace's files, and one file's text.
 *
 * Read only when opened, which is why the listing above carries none: this is a
 * request per workspace, and for a container-backed one it reads the host volume.
 */
function WorkspaceFilesCard({ workspace }: WorkspaceFilesCardProps) {
  const { files, isLoading, error } = useWorkspaceFiles(workspace.id);
  const [reading, setReading] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader className="space-y-1 border-b px-5 py-4">
        <CardTitle className="text-sm">{workspace.agent_name} — files</CardTitle>
        <CardDescription className="text-xs">{workspace.owner_label}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 p-5">
        {isLoading && <Skeleton className="h-16 w-full" />}

        {error !== null && (
          <div className="text-destructive flex items-start gap-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p>{error}</p>
          </div>
        )}

        {files !== null && files.items.length === 0 && (
          <p className="text-muted-foreground text-sm">
            This workspace is empty. It exists because an agent was given one, not because it has
            written anything.
          </p>
        )}

        {files !== null && files.items.length > 0 && (
          <ul className="divide-border divide-y text-sm">
            {files.items.map((file) => (
              <li key={file.path} className="flex items-center justify-between gap-3 py-2">
                <span className="flex min-w-0 items-center gap-2">
                  <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span className="truncate font-mono text-xs">{file.path}</span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="text-muted-foreground text-xs">{size(file.size)}</span>
                  {!file.is_dir && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Read ${file.path}`}
                      onClick={() => setReading(reading === file.path ? null : file.path)}
                    >
                      {reading === file.path ? "Close" : "Read"}
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}

        {reading !== null && <FileContents workspaceId={workspace.id} path={reading} />}
      </CardContent>
    </Card>
  );
}

interface FileContentsProps {
  workspaceId: string;
  path: string;
}

/**
 * One file, as text.
 *
 * Text only, which is the API's own limit rather than this component's: a workspace
 * can hold a PNG an agent produced, and serving it would mean deciding content
 * types and disposition headers — a download path with its own threat model.
 */
function FileContents({ workspaceId, path }: FileContentsProps) {
  const { file, isLoading, error } = useWorkspaceFile(workspaceId, path);

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (file === null) return null;

  return (
    <pre className="bg-muted max-h-80 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
      {file.content}
    </pre>
  );
}
