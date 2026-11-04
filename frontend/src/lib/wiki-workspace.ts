import { readConversationWorkspace } from "./conversation-workspace-api";
import { listLocalFiles } from "./desktop/commands";
import { listProjectFiles } from "./projects-api";
import { readWorkspaceFiles, type WorkspaceFile } from "./sandbox-workspaces-api";
import { readFileText, type FileSource } from "./workspace-files";
import { buildWikiGraph, parseWikiPage, type WikiGraph, WIKI_RELATION_LIMITS } from "./wiki-graph";

export const WIKI_LIMITS = { pages: 200, fileBytes: 256 * 1024, totalBytes: 8 * 1024 * 1024 };

export interface WikiSnapshot extends WikiGraph {
  files: WorkspaceFile[];
  skipped: string[];
  failed: string[];
  truncated: boolean;
}

async function listing(source: FileSource) {
  switch (source.kind) {
    case "project":
      return listProjectFiles(source.id);
    case "workspace":
      return readWorkspaceFiles(source.id);
    case "conversation":
      return readConversationWorkspace(source.id);
    case "local":
      return listLocalFiles(source.root).then((items) => ({
        items: items.map((file): WorkspaceFile => ({
          path: file.path,
          size: file.size,
          is_dir: file.is_dir,
          modified_at: file.modified === null ? null : new Date(file.modified * 1000).toISOString(),
        })),
        truncated: items.length >= 500,
        unreadable_reason: null,
      }));
  }
}

/** Links never cause reads: only paths returned by the authorized listing are scanned. */
export async function readWikiWorkspace(
  source: FileSource,
  signal: AbortSignal,
): Promise<WikiSnapshot> {
  signal.throwIfAborted();
  const files = await listing(source);
  signal.throwIfAborted();
  if (files.unreadable_reason) throw new Error(files.unreadable_reason);
  const markdown = files.items
    .filter((file) => !file.is_dir && /\.md$/i.test(file.path))
    .sort((a, b) => a.path.localeCompare(b.path));
  const selected: Pick<WorkspaceFile, "path" | "size">[] = [];
  const skipped: string[] = [];
  let bytes = 0;
  for (const file of markdown) {
    // Unknown sizes reserve a full page; a large preview is not a complete note.
    const size = file.size ?? WIKI_LIMITS.fileBytes;
    if (
      selected.length >= WIKI_LIMITS.pages ||
      size > WIKI_LIMITS.fileBytes ||
      bytes + size > WIKI_LIMITS.totalBytes
    )
      skipped.push(file.path);
    else {
      selected.push(file);
      bytes += size;
    }
  }
  const results: (ReturnType<typeof parseWikiPage> | null)[] = Array.from(
    { length: selected.length },
    () => null,
  );
  const failed: string[] = [];
  const pending = selected.entries();
  let loadedBytes = 0;
  let remainingLinks: number = WIKI_RELATION_LIMITS.graph;
  // Four in flight, including on refresh. Abort stops queued reads after navigation.
  await Promise.all(
    Array.from({ length: Math.min(4, selected.length) }, async () => {
      for (const [index, file] of pending) {
        signal.throwIfAborted();
        try {
          const text = await readFileText(source, file.path);
          signal.throwIfAborted();
          const size = new TextEncoder().encode(text.content).length;
          if (
            text.truncated ||
            size > WIKI_LIMITS.fileBytes ||
            loadedBytes + size > WIKI_LIMITS.totalBytes
          )
            skipped.push(file.path);
          else {
            loadedBytes += size;
            const page = parseWikiPage(file.path, text.content, remainingLinks);
            remainingLinks -= page.links.length;
            results[index] = page;
          }
        } catch (error) {
          signal.throwIfAborted();
          // Revocation must remove the whole previous graph, not retain its cached pages.
          if (
            typeof error === "object" &&
            error !== null &&
            "status" in error &&
            (error.status === 401 || error.status === 403)
          )
            throw error;
          failed.push(file.path);
        }
      }
    }),
  );
  const graph = buildWikiGraph(results.filter((page) => page !== null));
  return {
    ...graph,
    files: files.items,
    skipped: skipped.sort(),
    failed: failed.sort(),
    truncated: files.truncated || graph.relationshipsTruncated,
  };
}
