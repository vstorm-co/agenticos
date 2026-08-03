"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, Download, Folder, Info, Search } from "lucide-react";

import { FileIcon, isPreviewable } from "./file-tile";
import { Button, Input, Skeleton } from "@/components/ui";
import {
  downloadWorkspaceFile,
  useWorkspaceBytes,
  useWorkspaceFile,
  useWorkspaceFiles,
} from "@/hooks";
import { cn } from "@/lib/utils";
import type { WorkspaceFile } from "@/lib/sandbox-workspaces-api";

interface WorkspaceExplorerProps {
  workspaceId: string;
}

/** Bytes as a person reads them. */
function size(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** The path's segments, without the empties a leading slash produces. */
function segments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

interface Level {
  folders: string[];
  files: WorkspaceFile[];
}

/**
 * What sits directly inside one folder.
 *
 * Derived rather than fetched per directory: the listing already carries every path,
 * so walking into a folder is a filter and not a request. Which is also why search
 * can be immediate - it has the whole tree in hand.
 */
export function levelAt(files: WorkspaceFile[], prefix: string[]): Level {
  const folders = new Set<string>();
  const here: WorkspaceFile[] = [];
  for (const file of files) {
    const parts = segments(file.path);
    if (parts.length <= prefix.length) continue;
    if (prefix.some((part, index) => parts[index] !== part)) continue;
    if (parts.length === prefix.length + 1) {
      if (!file.is_dir) here.push(file);
      else folders.add(parts[prefix.length] as string);
    } else {
      folders.add(parts[prefix.length] as string);
    }
  }
  return {
    folders: [...folders].sort(),
    files: here.sort((left, right) => left.path.localeCompare(right.path)),
  };
}

/**
 * The files of one workspace, folder by folder.
 *
 * A page rather than a row that expands, because a workspace with a `skills/`
 * directory and a couple of reports is a tree, and a flat list of every path inside
 * a table cell is not something anybody can navigate.
 *
 * Search is over the whole tree and not the current folder: "where is that CSV" is
 * the question somebody opens this to answer, and making them walk the folders to
 * ask it would be the same failure the flat list has in the other direction. It
 * matches on the path, so a folder name narrows to its contents for free.
 */
export function WorkspaceExplorer({ workspaceId }: WorkspaceExplorerProps) {
  const { files, isLoading, error } = useWorkspaceFiles(workspaceId);
  const [prefix, setPrefix] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<string | null>(null);

  // Memoised, because it is the dependency of the two memos below: `?? []` builds a
  // fresh array on every render, which would recompute both of them every time.
  const all = useMemo(() => files?.items ?? [], [files]);
  const searching = query.trim() !== "";
  const matches = useMemo(
    () =>
      all
        .filter(
          (file) => !file.is_dir && file.path.toLowerCase().includes(query.trim().toLowerCase()),
        )
        .sort((left, right) => left.path.localeCompare(right.path)),
    [all, query],
  );
  const level = useMemo(() => levelAt(all, prefix), [all, prefix]);

  if (isLoading) return <Skeleton className="h-40 w-full" />;

  if (error !== null)
    return (
      <div className="text-destructive flex items-start gap-2 text-sm">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>{error}</p>
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* A breadcrumb rather than a back button: a workspace nests three deep at
            most, and the useful move is usually to the root or to the folder above
            it, both of which a breadcrumb offers in one click. */}
        <nav aria-label="Folders" className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
          <button
            type="button"
            onClick={() => setPrefix([])}
            className={cn("hover:underline", prefix.length === 0 && "font-medium")}
          >
            All files
          </button>
          {prefix.map((part, index) => (
            <span key={`${part}${index}`} className="flex items-center gap-1">
              <ChevronRight className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
              <button
                type="button"
                onClick={() => setPrefix(prefix.slice(0, index + 1))}
                className={cn("hover:underline", index === prefix.length - 1 && "font-medium")}
              >
                {part}
              </button>
            </span>
          ))}
        </nav>

        <div className="relative w-full sm:w-64">
          <Search
            className="text-muted-foreground absolute top-1/2 left-2 h-3.5 w-3.5 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={query}
            aria-label="Search files by name"
            placeholder="Search every folder"
            onChange={(event) => setQuery(event.target.value)}
            className="pl-7"
          />
        </div>
      </div>

      {files?.unreadable_reason != null && (
        <div className="text-muted-foreground flex items-start gap-2 text-xs">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>{files.unreadable_reason}</p>
        </div>
      )}

      {searching ? (
        matches.length === 0 ? (
          <p className="text-muted-foreground py-8 text-center text-sm">
            Nothing in this workspace matches “{query.trim()}”.
          </p>
        ) : (
          <FileList
            files={matches}
            workspaceId={workspaceId}
            opened={opened}
            onOpen={setOpened}
            showFullPath
          />
        )
      ) : (
        <>
          {level.folders.length === 0 && level.files.length === 0 && (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {files?.unreadable_reason == null
                ? "This folder is empty."
                : "Nothing could be listed here."}
            </p>
          )}

          {level.folders.length > 0 && (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {level.folders.map((folder) => (
                <li key={folder}>
                  <button
                    type="button"
                    onClick={() => setPrefix([...prefix, folder])}
                    className="border-border hover:bg-accent/60 flex w-full items-center gap-2 rounded-lg border p-3 text-left"
                  >
                    <Folder className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-sm">{folder}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {level.files.length > 0 && (
            <FileList
              files={level.files}
              workspaceId={workspaceId}
              opened={opened}
              onOpen={setOpened}
            />
          )}
        </>
      )}
    </div>
  );
}

interface FileListProps {
  files: WorkspaceFile[];
  workspaceId: string;
  opened: string | null;
  onOpen: (path: string | null) => void;
  showFullPath?: boolean;
}

/** The files at one level, as tiles, each openable and downloadable. */
function FileList({ files, workspaceId, opened, onOpen, showFullPath }: FileListProps) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {files.map((file) => (
        <li key={file.path} className="border-border rounded-lg border">
          <div className="flex items-center gap-2 p-3">
            <FileIcon path={file.path} className="text-muted-foreground h-4 w-4 shrink-0" />
            <button
              type="button"
              onClick={() => onOpen(opened === file.path ? null : file.path)}
              aria-expanded={opened === file.path}
              className="min-w-0 flex-1 truncate text-left font-mono text-xs hover:underline"
              title={file.path}
            >
              {showFullPath ? file.path : (file.path.split("/").pop() ?? file.path)}
            </button>
            <span className="text-muted-foreground shrink-0 text-[11px]">{size(file.size)}</span>
            <button
              type="button"
              aria-label={`Download ${file.path}`}
              onClick={() => void downloadWorkspaceFile(workspaceId, file.path)}
              className="text-muted-foreground hover:text-foreground shrink-0 rounded-md p-1"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </div>
          {opened === file.path && <Preview workspaceId={workspaceId} path={file.path} />}
        </li>
      ))}
    </ul>
  );
}

/** One file, as a picture when it is one and as text when it is not. */
function Preview({ workspaceId, path }: { workspaceId: string; path: string }) {
  if (isPreviewable(path)) return <ImagePreview workspaceId={workspaceId} path={path} />;
  return <TextPreview workspaceId={workspaceId} path={path} />;
}

function ImagePreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  const { url, isLoading, error } = useWorkspaceBytes(workspaceId, path);

  if (isLoading) return <Skeleton className="m-3 h-32" />;
  if (error !== null) return <p className="text-destructive px-3 pb-3 text-xs">{error}</p>;
  if (url === null) return null;

  return (
    <div className="px-3 pb-3">
      {/* A plain `img` and not `next/image`: the source is a blob URL made in this
          browser from bytes fetched with the organization header, and the optimizer
          would need a URL it could fetch server-side - which is exactly the request
          that would arrive without that header. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={path} className="max-h-64 w-full rounded-md object-contain" />
    </div>
  );
}

function TextPreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  const { file, isLoading, error } = useWorkspaceFile(workspaceId, path);

  if (isLoading) return <Skeleton className="m-3 h-24" />;
  if (error !== null)
    return (
      <div className="px-3 pb-3">
        <p className="text-destructive text-xs">{error}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => void downloadWorkspaceFile(workspaceId, path)}
        >
          <Download className="h-3.5 w-3.5" />
          Download it instead
        </Button>
      </div>
    );
  if (file === null) return null;

  return (
    <pre className="bg-muted mx-3 mb-3 max-h-64 overflow-auto rounded-md p-2 text-[11px] whitespace-pre-wrap">
      {file.content}
    </pre>
  );
}
