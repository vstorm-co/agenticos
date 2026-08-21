"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Download,
  Folder,
  FolderOpen,
  Info,
  Search,
} from "lucide-react";

import { FileContent, FileIcon } from "@/components/files";
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { hasSourceView, resolveFileKind } from "@/lib/file-kinds";
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

/** One entry of the tree, with whatever sits inside it. */
export interface TreeNode {
  name: string;
  /** The full path, which is the identity a folder is remembered open by. */
  path: string;
  isDir: boolean;
  children: TreeNode[];
  /** The listing's own row, for a file. Absent for a folder. */
  file?: WorkspaceFile;
}

/**
 * The listing as a tree, built once from the flat paths.
 *
 * Derived rather than fetched per directory: the listing carries every path, so
 * opening a folder is a state change and not a request - which is also why search
 * can be immediate.
 *
 * A folder exists here because something is inside it, whether or not the host
 * returned a directory entry of its own: a listing that names `uploads/x.pdf` and
 * nothing else still has an `uploads`, and a tree built only from `is_dir` rows
 * would hide the file under a folder it never drew.
 */
export function treeOf(files: WorkspaceFile[]): TreeNode[] {
  const roots: TreeNode[] = [];
  const byPath = new Map<string, TreeNode>();

  const folder = (parts: string[]): TreeNode[] => {
    let siblings = roots;
    let walked = "";
    for (const part of parts) {
      walked = walked === "" ? part : `${walked}/${part}`;
      let node = byPath.get(walked);
      if (node === undefined || !node.isDir) {
        node = { name: part, path: walked, isDir: true, children: [] };
        byPath.set(walked, node);
        siblings.push(node);
      }
      siblings = node.children;
    }
    return siblings;
  };

  // Directories first, so a folder that *is* in the listing keeps its own row
  // rather than being invented by the file underneath it.
  for (const file of [...files].sort((left, right) => Number(right.is_dir) - Number(left.is_dir))) {
    const parts = segments(file.path);
    if (parts.length === 0) continue;
    if (file.is_dir) {
      folder(parts);
      continue;
    }
    const name = parts[parts.length - 1] as string;
    const siblings = folder(parts.slice(0, -1));
    const node: TreeNode = { name, path: file.path, isDir: false, children: [], file };
    byPath.set(segments(file.path).join("/"), node);
    siblings.push(node);
  }

  const order = (nodes: TreeNode[]): TreeNode[] => {
    // Folders above files, each alphabetical - the order every file manager uses,
    // and the one that puts what can be opened where a reader looks first.
    nodes.sort(
      (left, right) =>
        Number(right.isDir) - Number(left.isDir) || left.name.localeCompare(right.name),
    );
    for (const node of nodes) order(node.children);
    return nodes;
  };
  return order(roots);
}

/** How many files a tree holds, for deciding whether to open all of it. */
function countFiles(nodes: TreeNode[]): number {
  return nodes.reduce((total, node) => total + (node.isDir ? countFiles(node.children) : 1), 0);
}

/**
 * Every folder in a tree small enough to show whole.
 *
 * A workspace nests three deep at most and usually holds a handful of files, so a
 * tree that starts closed hides the only thing on the page - which is what the
 * drill-down did: `uploads` was one click away from being the only visible row.
 * Past the ceiling the top level alone opens, because a thousand rows rendered at
 * once is a different failure.
 */
const OPEN_ALL_UP_TO = 200;

function initiallyOpen(nodes: TreeNode[]): Set<string> {
  const open = new Set<string>();
  const walk = (items: TreeNode[], deep: boolean) => {
    for (const node of items) {
      if (!node.isDir) continue;
      open.add(node.path);
      if (deep) walk(node.children, deep);
    }
  };
  walk(nodes, countFiles(nodes) <= OPEN_ALL_UP_TO);
  return open;
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
  // Which folders are open, by path. A set rather than a prefix: the tree shows
  // every level at once, so "where am I" is not a single place any more.
  const [open, setOpen] = useState<Set<string> | null>(null);
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
  const tree = useMemo(() => treeOf(all), [all]);
  // Null until the listing arrives, so the first render of a tree opens it rather
  // than an effect opening it a frame later.
  const opened = open ?? initiallyOpen(tree);

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
    // A column that fills what the page gives it: the two panes were 300 px tall
    // under 600 px of empty page, because `min-h-[24rem]` was the only height in
    // the chain and nothing above it passed one down.
    <div className="flex min-h-0 flex-1 flex-col gap-4">
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
      {/* `min-h-0` on both the grid and its children, or a flex child's default
          minimum is its content and the panes grow the page instead of scrolling. */}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[20rem_1fr]">
        <div className="border-border bg-card flex min-h-0 min-w-0 flex-col gap-3 overflow-y-auto rounded-xl border p-3">
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
          ) : tree.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-xs">
              {files?.unreadable_reason == null ? t("folderEmpty") : t("nothingListed")}
            </p>
          ) : (
            /* A tree, open where the reader left it. The drill-down it replaces
               showed one level and a breadcrumb, so a workspace whose only folder
               was `uploads` opened on a list of one row and hid every file it
               held - and moving between two folders meant walking up and back
               down. */
            <ul role="tree" aria-label={t("folders")} className="min-w-0">
              {tree.map((node) => (
                <TreeRow
                  key={node.path}
                  node={node}
                  depth={0}
                  open={opened}
                  selected={selected}
                  source={source}
                  onSelect={setSelected}
                  onToggle={(path: string) =>
                    setOpen((): Set<string> => {
                      const next = new Set(opened);
                      if (!next.delete(path)) next.add(path);
                      return next;
                    })
                  }
                />
              ))}
            </ul>
          )}
        </div>

        <div className="border-border bg-card flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border">
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
                {/* Every format with two renderings, which `hasSourceView` is the
                    one answer to - HTML, CSV and JSON all have tags, delimiters or
                    unformatted text worth reading, and limiting this to markdown
                    took that away from the surface that replaced `FileViewer`. */}
                {hasSourceView(kind) && (
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

/**
 * One row of the tree, and whatever is under it.
 *
 * Indented by depth rather than nested in padded boxes: an indent is what says
 * "inside", and a box inside a box inside a box eats the width a path needs.
 * `role="tree"` and `aria-expanded` because that is what this is - a reader on a
 * screen reader gets a tree rather than a list of buttons whose meaning is in
 * their left margin.
 */
function TreeRow({
  node,
  depth,
  open,
  selected,
  source,
  onSelect,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  open: Set<string>;
  selected: string | null;
  source: FileSource;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const t = useTranslations("sandboxes.workspaces");
  const tc = useTranslations("common");
  const isOpen = open.has(node.path);
  // Inline, because the depth is data: a Tailwind class built by interpolation is
  // a class the compiler never sees and never emits.
  const indent = { paddingLeft: `${depth * 0.75 + 0.5}rem` };

  if (!node.isDir) {
    return (
      // The same three parts `FileList` uses, for the same reason: the button is
      // named by the file and nothing else, so a size does not become part of what
      // a screen reader announces - and the download does not need the file opened
      // first.
      <li
        role="treeitem"
        aria-selected={selected === node.path}
        className="flex items-center gap-1"
      >
        <button
          type="button"
          onClick={() => onSelect(node.path)}
          aria-current={selected === node.path}
          style={indent}
          title={node.path}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-md py-1.5 pr-2 text-left",
            selected === node.path ? "bg-accent" : "hover:bg-accent/60",
          )}
        >
          <FileIcon name={node.name} className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate font-mono text-xs">{node.name}</span>
        </button>
        <span className="text-muted-foreground shrink-0 text-[11px]">
          {node.file?.size == null ? "—" : formatBytes(node.file.size)}
        </span>
        <button
          type="button"
          aria-label={tc("downloadNamed", { name: node.path })}
          onClick={() => void workspaceFileAccess(source, node.path).download()}
          className="text-muted-foreground hover:text-foreground shrink-0 rounded-md p-1"
        >
          <Download className="h-3.5 w-3.5" />
        </button>
      </li>
    );
  }

  return (
    // `aria-selected` on a folder too: the role requires it, and a folder in this
    // tree is never the selection - what is read on the right is always a file.
    <li role="treeitem" aria-expanded={isOpen} aria-selected={false}>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onToggle(node.path)}
          style={indent}
          className="hover:bg-accent/60 flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left"
        >
          <ChevronRight
            className={cn(
              "text-muted-foreground h-3.5 w-3.5 shrink-0 transition-transform",
              isOpen && "rotate-90",
            )}
            aria-hidden
          />
          {isOpen ? (
            <FolderOpen className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            <Folder className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
          )}
          <span className="min-w-0 flex-1 truncate text-xs font-medium">{node.name}</span>
        </button>
        <span className="text-muted-foreground/70 shrink-0 pr-2 text-[10px]">
          {t("fileCount", { count: node.children.filter((child) => !child.isDir).length })}
        </span>
      </div>

      {isOpen && (
        <ul role="group">
          {node.children.map((child) => (
            <TreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              open={open}
              selected={selected}
              source={source}
              onSelect={onSelect}
              onToggle={onToggle}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
