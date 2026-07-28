/**
 * A folder tree built from a flat list of paths.
 *
 * There are no folder rows and deliberately no folder table: a folder is a
 * prefix that some file has. That is what makes an empty folder impossible -
 * which is the honest model, because a skill's files are read by name and a
 * folder nothing is in is a folder the agent can never ask for.
 */

export interface TreeFile {
  kind: "file";
  /** The full path, which is the resource's name. */
  path: string;
  /** The last segment - what the row shows. */
  label: string;
  id: string;
  sizeBytes: number;
}

export interface TreeFolder {
  kind: "folder";
  /** The path of the folder itself, so it can be expanded by identity. */
  path: string;
  label: string;
  children: TreeNode[];
}

export type TreeNode = TreeFile | TreeFolder;

export interface PathEntry {
  id: string;
  name: string;
  size_bytes: number;
}

/**
 * The tree, folders before files and each group in name order.
 *
 * Folders first because that is how every file browser anyone has used
 * behaves, and a tree that sorts otherwise reads as unsorted.
 */
export function buildTree(entries: PathEntry[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const entry of entries) {
    const segments = entry.name.split("/").filter(Boolean);
    if (segments.length === 0) continue;

    let level = root;
    let prefix = "";

    for (const segment of segments.slice(0, -1)) {
      prefix = prefix ? `${prefix}/${segment}` : segment;
      const existing = level.find(
        (node): node is TreeFolder => node.kind === "folder" && node.label === segment,
      );
      if (existing) {
        level = existing.children;
        continue;
      }
      const folder: TreeFolder = { kind: "folder", path: prefix, label: segment, children: [] };
      level.push(folder);
      level = folder.children;
    }

    level.push({
      kind: "file",
      path: entry.name,
      label: segments[segments.length - 1]!,
      id: entry.id,
      sizeBytes: entry.size_bytes,
    });
  }

  return sortNodes(root);
}

function sortNodes(nodes: TreeNode[]): TreeNode[] {
  for (const node of nodes) {
    if (node.kind === "folder") sortNodes(node.children);
  }
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
    return a.label.localeCompare(b.label);
  });
  return nodes;
}

/** Every folder path in the tree - what "expand all" needs to know. */
export function folderPaths(nodes: TreeNode[]): string[] {
  return nodes.flatMap((node) =>
    node.kind === "folder" ? [node.path, ...folderPaths(node.children)] : [],
  );
}

/**
 * How a file should be shown, from its extension alone.
 *
 * The extension is all there is: the content is stored as text with no media
 * type beside it, because what the model receives is text either way.
 */
export type Preview = "markdown" | "html" | "code" | "text";

const BY_EXTENSION: Record<string, Preview> = {
  md: "markdown",
  markdown: "markdown",
  mdx: "markdown",
  html: "html",
  htm: "html",
  py: "code",
  js: "code",
  ts: "code",
  tsx: "code",
  jsx: "code",
  json: "code",
  yaml: "code",
  yml: "code",
  toml: "code",
  sh: "code",
  bash: "code",
  sql: "code",
  css: "code",
  csv: "code",
};

export function previewKind(path: string): Preview {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return BY_EXTENSION[extension] ?? "text";
}

/** The language label a highlighted block is introduced by. */
export function languageOf(path: string): string {
  return path.split(".").pop()?.toLowerCase() ?? "text";
}
