/**
 * Reading one workspace file, whichever surface is asking.
 *
 * Two surfaces show the same files: the panel beside a chat, and the Workspaces
 * screen. They reach them through different routes because they authorise different
 * callers - a chat is authorised by fetching the conversation, which somebody it was
 * shared with passes, and the Workspaces screen is authorised per workspace row - so
 * the *address* differs while everything after it must not. Opening a file has to
 * mean the same thing in both, down to which types render in place and which only
 * download.
 *
 * This is where the two addresses meet: a `FileSource` names one, and the viewer
 * above never learns which it was handed.
 */

import { readConversationFile, readConversationFileBytes } from "./conversation-workspace-api";
import { qk } from "./query-keys";
import { readWorkspaceBytes, readWorkspaceFile } from "./sandbox-workspaces-api";

/** Where a workspace file is read from. */
export type FileSource =
  | { readonly kind: "conversation"; readonly id: string }
  | { readonly kind: "workspace"; readonly id: string };

/** One file's text. The two routes answer the same shape, deliberately. */
export interface FileText {
  path: string;
  content: string;
  /** Whether the answer was shortened. The agent still reads the whole file. */
  truncated: boolean;
}

export function readFileText(source: FileSource, path: string): Promise<FileText> {
  return source.kind === "conversation"
    ? readConversationFile(source.id, path)
    : readWorkspaceFile(source.id, path);
}

export function readFileBytes(
  source: FileSource,
  path: string,
  options: { download?: boolean } = {},
): Promise<Blob> {
  return source.kind === "conversation"
    ? readConversationFileBytes(source.id, path, options)
    : readWorkspaceBytes(source.id, path, options);
}

export function textKey(source: FileSource, path: string) {
  return source.kind === "conversation"
    ? qk.conversationWorkspace.file(source.id, path)
    : qk.sandboxWorkspaces.file(source.id, path);
}

export function bytesKey(source: FileSource, path: string) {
  return source.kind === "conversation"
    ? qk.conversationWorkspace.bytes(source.id, path)
    : qk.sandboxWorkspaces.bytes(source.id, path);
}

const TEXT_SUFFIXES = new Set([
  "txt",
  "md",
  "markdown",
  "csv",
  "tsv",
  "json",
  "jsonl",
  "yaml",
  "yml",
  "toml",
  "ini",
  "cfg",
  "conf",
  "env",
  "log",
  "sql",
  "py",
  "js",
  "ts",
  "tsx",
  "jsx",
  "html",
  "htm",
  "css",
  "scss",
  "xml",
  "svg",
  "sh",
  "bash",
  "zsh",
  "rs",
  "go",
  "java",
  "kt",
  "rb",
  "php",
  "c",
  "h",
  "cpp",
  "hpp",
  "patch",
  "diff",
]);

/** The suffix, lowercased, without the dot. Empty for a file that has none. */
export function suffixOf(path: string): string {
  const name = path.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

/**
 * Whether to ask for this file's text rather than its bytes.
 *
 * It decides which *request* to make and nothing else. Whether what came back can be
 * displayed is the server's answer, read off the response's type: the API decides
 * what may be shown inline - raster images and PDFs, never SVG or HTML - and a second
 * list of suffixes making that call in the client is a second answer that drifts the
 * first time either moves.
 *
 * An unknown suffix asks for bytes, which is the safe way round: a text file arrives
 * as an offered download, where guessing the other way renders a binary as mojibake.
 */
export function isTextual(path: string): boolean {
  return TEXT_SUFFIXES.has(suffixOf(path));
}

/** Whether a file's text is worth rendering as well as showing as source. */
export function isMarkdown(path: string): boolean {
  return ["md", "markdown"].includes(suffixOf(path));
}
