import type { WorkspaceFile } from "./sandbox-workspaces-api";

function segments(path: string): string[] {
  return path.split("/").filter((part) => part !== "" && part !== ".");
}

export interface WorkspaceTreeNode<T extends WorkspaceFile> {
  label: string;
  path: string;
  isDir: boolean;
  children: WorkspaceTreeNode<T>[];
  /** The listing's own row, for a file. Absent for a folder. */
  file?: T;
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
export function treeOf<T extends WorkspaceFile>(files: T[]): WorkspaceTreeNode<T>[] {
  const roots: WorkspaceTreeNode<T>[] = [];
  const byPath = new Map<string, WorkspaceTreeNode<T>>();

  const folder = (parts: string[]): WorkspaceTreeNode<T>[] => {
    let siblings = roots;
    let walked = "";
    for (const part of parts) {
      walked = walked === "" ? part : `${walked}/${part}`;
      let node = byPath.get(walked);
      if (node === undefined || !node.isDir) {
        node = { label: part, path: walked, isDir: true, children: [] };
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
    const label = parts[parts.length - 1] as string;
    const siblings = folder(parts.slice(0, -1));
    const node: WorkspaceTreeNode<T> = { label, path: file.path, isDir: false, children: [], file };
    byPath.set(segments(file.path).join("/"), node);
    siblings.push(node);
  }

  const order = (nodes: WorkspaceTreeNode<T>[]): WorkspaceTreeNode<T>[] => {
    // Folders above files, each alphabetical - the order every file manager uses,
    // and the one that puts what can be opened where a reader looks first.
    nodes.sort(
      (left, right) =>
        Number(right.isDir) - Number(left.isDir) || left.label.localeCompare(right.label),
    );
    for (const node of nodes) order(node.children);
    return nodes;
  };
  return order(roots);
}
