"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight, Download, Folder, Info, Search } from "lucide-react";

import { FileContent, FileIcon } from "@/components/files";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { resolveFileKind } from "@/lib/file-kinds";
import { useWorkspaceFiles } from "@/hooks";
import { cn, formatBytes } from "@/lib/utils";
import { workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import type { WorkspaceFile } from "@/lib/sandbox-workspaces-api";
import { useTranslations } from "next-intl";

interface WorkspaceExplorerProps {
  workspaceId: string;
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
 *
 * **Two panes, the shape the skills editor uses.** Opening a file used to raise the
 * shared dialog over the tree, which is right for a file reached from anywhere and
 * wrong here: reading a workspace means reading several files in turn, and a modal
 * closes the list every time. The tree stays on the left and the file renders
 * beside it, so moving between two files is one click rather than three (#1039).
 * `FileViewer` is still what the flat "all files" list opens - there, one file
 * *is* the whole errand.
 */
export function WorkspaceExplorer({ workspaceId }: WorkspaceExplorerProps) {
  const t = useTranslations("sandboxes.workspaces");
  const { files, isLoading, error } = useWorkspaceFiles(workspaceId);
  const [prefix, setPrefix] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  // A path rather than the row: the listing is refetched, and a held row would go
  // on rendering a file that has been overwritten since.
  const [selected, setSelected] = useState<string | null>(null);
  const [asSource, setAsSource] = useState(false);
  const source = useMemo<FileSource>(() => ({ kind: "workspace", id: workspaceId }), [workspaceId]);

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

  const chosen = selected === null ? null : (all.find((file) => file.path === selected) ?? null);
  const kind = chosen === null ? null : resolveFileKind(chosen.path);

  return (
    <div className="space-y-4">
      {/* Whose files these are and what holds them, on the page rather than only in
          the table that linked here. Under `agent` scope one workspace is shared by
          everybody who talks to that agent, so somebody opens this and finds a file
          they never created - and a tree of paths with no statement of who can see
          them is the wrong thing to hand somebody auditing it. */}
      {files !== null && (
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="outline">
            {files.backend === "state" ? t("stored") : t("container")}
          </Badge>
          <span>{files.owner_label}</span>
          {files.backend === "state" && files.bytes_total > 0 && (
            <span>{t("bytesStored", { size: formatBytes(files.bytes_total) })}</span>
          )}
        </div>
      )}

      {files?.unreadable_reason != null && (
        <div className="text-muted-foreground flex items-start gap-2 text-xs">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <p>{files.unreadable_reason}</p>
        </div>
      )}

      {/* The tree beside the file rather than a dialog over it. Stacked below `lg`,
          where two columns would each be too narrow to read a path in. */}
      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <div className="border-border bg-card min-w-0 space-y-3 rounded-xl border p-3">
          <div className="relative">
            <Search
              className="text-muted-foreground absolute top-1/2 left-2 h-3.5 w-3.5 -translate-y-1/2"
              aria-hidden
            />
            <Input
              value={query}
              aria-label={t("searchLabel")}
              placeholder={t("searchPlaceholder")}
              onChange={(event) => setQuery(event.target.value)}
              className="h-8 pl-7 text-xs"
            />
          </div>

          {/* A breadcrumb rather than a back button: a workspace nests three deep at
              most, and the useful move is usually to the root or to the folder above
              it, both of which a breadcrumb offers in one click. Hidden while
              searching, which is over the whole tree and so belongs to no folder. */}
          {!searching && (
            <nav
              aria-label={t("folders")}
              className="flex min-w-0 flex-wrap items-center gap-1 text-xs"
            >
              <button
                type="button"
                onClick={() => setPrefix([])}
                className={cn("hover:underline", prefix.length === 0 && "font-medium")}
              >
                {t("allFiles2")}
              </button>
              {prefix.map((part, index) => (
                <span key={`${part}${index}`} className="flex items-center gap-1">
                  <ChevronRight className="text-muted-foreground h-3 w-3" aria-hidden />
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
          )}

          {searching ? (
            matches.length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-xs">
                {t("noMatches", { query: query.trim() })}
              </p>
            ) : (
              <FileList
                source={source}
                files={matches}
                selected={selected}
                onSelect={setSelected}
                showFullPath
              />
            )
          ) : (
            <>
              {level.folders.length === 0 && level.files.length === 0 && (
                <p className="text-muted-foreground py-6 text-center text-xs">
                  {files?.unreadable_reason == null ? t("folderEmpty") : t("nothingListed")}
                </p>
              )}

              {level.folders.length > 0 && (
                <ul className="space-y-0.5">
                  {level.folders.map((folder) => (
                    <li key={folder}>
                      <button
                        type="button"
                        onClick={() => setPrefix([...prefix, folder])}
                        className="hover:bg-accent/60 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left"
                      >
                        <Folder
                          className="text-muted-foreground h-3.5 w-3.5 shrink-0"
                          aria-hidden
                        />
                        <span className="min-w-0 flex-1 truncate text-xs">{folder}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {level.files.length > 0 && (
                <FileList
                  source={source}
                  files={level.files}
                  selected={selected}
                  onSelect={setSelected}
                />
              )}
            </>
          )}
        </div>

        <div className="border-border bg-card flex min-h-[24rem] min-w-0 flex-col rounded-xl border">
          {chosen === null || kind === null ? (
            <p className="text-muted-foreground m-auto p-6 text-center text-sm">{t("pickAFile")}</p>
          ) : (
            <>
              <div className="border-border flex flex-wrap items-center gap-2 border-b px-3 py-2">
                <FileIcon name={chosen.path} className="text-muted-foreground h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={chosen.path}>
                  {chosen.path}
                </span>
                <span className="text-muted-foreground shrink-0 text-[11px]">
                  {chosen.size == null ? "—" : formatBytes(chosen.size)}
                </span>
                {/* Only where there are two renderings to choose between: the toggle
                    on a PNG or a spreadsheet would offer the same thing twice. */}
                {kind === "markdown" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-pressed={asSource}
                    onClick={() => setAsSource(!asSource)}
                  >
                    {asSource ? t("preview") : t("source")}
                  </Button>
                )}
              </div>
              {/* Keyed on the path, so moving between two files remounts the reader
                  rather than showing the previous one's bytes while the next load is
                  in flight. */}
              <div className="min-h-0 flex-1 overflow-auto p-3">
                <FileContent
                  key={chosen.path}
                  access={workspaceFileAccess(source, chosen.path)}
                  kind={kind}
                  name={chosen.path.split("/").filter(Boolean).pop() ?? chosen.path}
                  asSource={asSource}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface FileListProps {
  source: FileSource;
  files: WorkspaceFile[];
  selected: string | null;
  onSelect: (path: string) => void;
  showFullPath?: boolean;
}

/**
 * The files at one level, as rows, the chosen one marked.
 *
 * Downloading is on the row rather than beside the reader, and that is the point:
 * selecting a file reads it, and a 50 MB archive is a file somebody wants a copy of
 * without paying to load it first.
 */
function FileList({ source, files, selected, onSelect, showFullPath }: FileListProps) {
  const tc = useTranslations("common");
  return (
    <ul className="space-y-0.5">
      {files.map((file) => (
        <li key={file.path} className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onSelect(file.path)}
            aria-current={file.path === selected}
            className={cn(
              "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left",
              file.path === selected ? "bg-accent" : "hover:bg-accent/60",
            )}
            title={file.path}
          >
            <FileIcon name={file.path} className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
            {/* The button is named by the file and nothing else: a size inside it
                becomes part of what a screen reader announces and part of what a
                test has to match. */}
            <span className="min-w-0 flex-1 truncate font-mono text-xs">
              {showFullPath ? file.path : (file.path.split("/").pop() ?? file.path)}
            </span>
          </button>
          <span className="text-muted-foreground shrink-0 text-[11px]">
            {file.size == null ? "—" : formatBytes(file.size)}
          </span>
          <button
            type="button"
            aria-label={tc("downloadNamed", { name: file.path })}
            onClick={() => void workspaceFileAccess(source, file.path).download()}
            className="text-muted-foreground hover:text-foreground shrink-0 rounded-md p-1"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
        </li>
      ))}
    </ul>
  );
}
