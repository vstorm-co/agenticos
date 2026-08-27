"use client";

import { type ReactNode } from "react";
import { ChevronRight, Folder, FolderOpen } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * What the tree needs of a node. Everything else is the caller's.
 *
 * `path` is the identity - what a folder is remembered open by, and what a file
 * is selected by - so it has to be unique across the tree. Both surfaces using
 * this build it from the file's own path, which is unique by construction.
 */
export interface PathTreeNode {
  label: string;
  path: string;
  isDir: boolean;
  children: PathTreeNode[];
}

interface PathTreeProps<N extends PathTreeNode> {
  nodes: N[];
  /** Names the tree for a reader who cannot see it. */
  label: string;
  /** The file that is open, by path. */
  selectedPath: string | null;
  onSelect: (node: N) => void;
  /**
   * Which folders are open, by path - and the caller's, not this component's.
   *
   * Held above rather than inside, because *when* the state should survive is
   * the caller's question and the two callers answer it differently. The
   * workspace explorer replaces this tree with a flat list while a search is
   * running, so state kept here would be discarded and the reader's folds reset
   * every time they cleared the box; and a skill computes openness as "every
   * folder except the ones collapsed", so a folder added after a collapse is
   * open, which a snapshot taken at mount cannot know.
   */
  openPaths: Set<string>;
  onToggleFolder: (path: string) => void;
  /** What a file's row says, inside the button that opens it: an icon and a name. */
  renderFile: (node: N, isSelected: boolean) => ReactNode;
  /**
   * Anything to the right of a file's name, *outside* the button that opens it.
   *
   * Outside because a control belongs there: the workspace's rows carry a
   * download, and a button inside a button is invalid - which is also why the
   * name button is named by the file alone, so a size never becomes part of what
   * a screen reader announces.
   */
  renderFileMeta?: (node: N) => ReactNode;
  /** Anything to the right of a folder's name - a count, a size. */
  renderFolderMeta?: (node: N) => ReactNode;
}

/**
 * A folder tree with one file open, shared by `/skills` and `/workspaces`.
 *
 * Both surfaces had their own: the same recursion, the same expand-collapse set
 * keyed on a folder's path, the same chevron and the same two folder icons,
 * written twice with two node shapes and two polarities of open state - one
 * holding what was collapsed, the other what was open (#137).
 *
 * What is shared is the mechanics and the semantics: indentation by depth,
 * `role="tree"` with `aria-expanded` on the folders, and one selected file. What
 * the rows *say* is the caller's - a skill file is a name, a workspace file is a
 * name, a size and a download - which is why the file row arrives as a render
 * prop rather than as five optional props.
 *
 * Indented rather than nested in padded boxes: an indent is what says "inside",
 * and a box inside a box inside a box eats the width a path needs. The depth is
 * data, so it is an inline style: a Tailwind class built by interpolation is a
 * class the compiler never sees and never emits.
 */
export function PathTree<N extends PathTreeNode>({
  nodes,
  label,
  selectedPath,
  onSelect,
  openPaths,
  onToggleFolder,
  renderFile,
  renderFileMeta,
  renderFolderMeta,
}: PathTreeProps<N>) {
  // Here rather than at each caller: a tree with nothing in it is nothing, and
  // a surface that wants to say something instead - the workspace explorer says
  // whether the folder is empty or the host would not answer - checks before it
  // gets here.
  if (nodes.length === 0) return null;
  return (
    <ul role="tree" aria-label={label} className="min-w-0">
      {nodes.map((node) => (
        <PathTreeRow
          key={rowKey(node)}
          node={node}
          depth={0}
          opened={openPaths}
          onToggle={onToggleFolder}
          selectedPath={selectedPath}
          onSelect={onSelect}
          renderFile={renderFile}
          renderFileMeta={renderFileMeta}
          renderFolderMeta={renderFolderMeta}
        />
      ))}
    </ul>
  );
}

/**
 * A key unique across the tree, which a path alone is not.
 *
 * A skill may hold a resource named `a` and another named `a/b.md`, and the
 * builder then makes sibling nodes - a file and a folder - whose `path` is `a`.
 * Two rows under one React key reconcile into one, so the kind is part of it.
 */
function rowKey(node: PathTreeNode): string {
  return `${node.isDir ? "d" : "f"}:${node.path}`;
}

function PathTreeRow<N extends PathTreeNode>({
  node,
  depth,
  opened,
  onToggle,
  selectedPath,
  onSelect,
  renderFile,
  renderFileMeta,
  renderFolderMeta,
}: {
  node: N;
  depth: number;
  opened: Set<string>;
  onToggle: (path: string) => void;
} & Pick<
  PathTreeProps<N>,
  "selectedPath" | "onSelect" | "renderFile" | "renderFileMeta" | "renderFolderMeta"
>) {
  const indent = { paddingLeft: `${depth * 0.75 + 0.5}rem` };

  if (!node.isDir) {
    const isSelected = selectedPath === node.path;
    return (
      <li role="treeitem" aria-selected={isSelected} className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onSelect(node)}
          aria-current={isSelected}
          title={node.path}
          style={indent}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-md py-1.5 pr-2 text-left",
            isSelected ? "bg-accent" : "hover:bg-accent/60",
          )}
        >
          {renderFile(node, isSelected)}
        </button>
        {renderFileMeta?.(node)}
      </li>
    );
  }

  const isOpen = opened.has(node.path);
  return (
    // `aria-selected` on a folder too: the role requires it, and a folder in this
    // tree is never the selection - what is read beside it is always a file.
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
          <span className="min-w-0 flex-1 truncate text-xs font-medium">{node.label}</span>
        </button>
        {renderFolderMeta?.(node)}
      </div>

      {isOpen && (
        <ul role="group">
          {node.children.map((child) => (
            <PathTreeRow
              key={rowKey(child)}
              node={child as N}
              depth={depth + 1}
              opened={opened}
              onToggle={onToggle}
              selectedPath={selectedPath}
              onSelect={onSelect}
              renderFile={renderFile}
              renderFileMeta={renderFileMeta}
              renderFolderMeta={renderFolderMeta}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
