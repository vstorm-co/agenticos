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
 * never learns which it was handed. What kind of file it is and how it renders are
 * not here - they are `file-kinds.ts`, which answers that for every surface.
 */

import { readConversationFile, readConversationFileBytes } from "./conversation-workspace-api";
import { saveBlob, type FileAccess, type FileText } from "./file-access";
import { qk } from "./query-keys";
import { readWorkspaceBytes, readWorkspaceFile } from "./sandbox-workspaces-api";

/** Where a workspace file is read from. */
export type FileSource =
  | { readonly kind: "conversation"; readonly id: string }
  | { readonly kind: "workspace"; readonly id: string };

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

/**
 * One workspace file, as the shared viewer takes it.
 *
 * The download asks the route for `download=true` rather than saving the bytes a
 * preview already has: that is what makes the server answer `attachment`, and for
 * everything off its short inline list it is the only way the bytes come back at all.
 */
export function workspaceFileAccess(source: FileSource, path: string): FileAccess {
  return {
    textKey: textKey(source, path),
    bytesKey: bytesKey(source, path),
    readText: () => readFileText(source, path),
    readBytes: () => readFileBytes(source, path),
    download: async () => {
      const blob = await readFileBytes(source, path, { download: true });
      saveBlob(blob, path.split("/").filter(Boolean).pop() ?? "file");
    },
  };
}
