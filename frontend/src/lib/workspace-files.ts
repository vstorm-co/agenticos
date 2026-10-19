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
import { readProjectBytes, readProjectText } from "./projects-api";
import { qk } from "./query-keys";
import { readWorkspaceBytes, readWorkspaceFile } from "./sandbox-workspaces-api";

/** Where a workspace file is read from. */
export type FileSource =
  | { readonly kind: "conversation"; readonly id: string }
  | { readonly kind: "workspace"; readonly id: string }
  | { readonly kind: "project"; readonly id: string };

export function readFileText(source: FileSource, path: string): Promise<FileText> {
  switch (source.kind) {
    case "conversation":
      return readConversationFile(source.id, path);
    case "project":
      return readProjectText(source.id, path);
    case "workspace":
      return readWorkspaceFile(source.id, path);
  }
}

export function readFileBytes(
  source: FileSource,
  path: string,
  options: { download?: boolean } = {},
): Promise<Blob> {
  switch (source.kind) {
    case "conversation":
      return readConversationFileBytes(source.id, path, options);
    case "project":
      return readProjectBytes(source.id, path, options);
    case "workspace":
      return readWorkspaceBytes(source.id, path, options);
  }
}

export function textKey(source: FileSource, path: string) {
  switch (source.kind) {
    case "conversation":
      return qk.conversationWorkspace.file(source.id, path);
    case "project":
      return qk.projects.file(source.id, path);
    case "workspace":
      return qk.sandboxWorkspaces.file(source.id, path);
  }
}

export function bytesKey(source: FileSource, path: string) {
  switch (source.kind) {
    case "conversation":
      return qk.conversationWorkspace.bytes(source.id, path);
    case "project":
      return qk.projects.bytes(source.id, path);
    case "workspace":
      return qk.sandboxWorkspaces.bytes(source.id, path);
  }
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

/** The id an attachment is filed under, ahead of its own name - `uploads/<8 hex>-<name>`. */
const UPLOAD_PREFIX = /^[0-9a-f]{8}-/;

/**
 * A workspace file as a person calls it: its own name, without the folders over it.
 *
 * An attachment is stored as `uploads/0d7d5756-handbook.pdf` - the hex keeps two
 * files called `handbook.pdf` apart - and that prefix is the platform's filing,
 * not the name the person gave it. Only an attachment loses it: an agent's own
 * file is named by the agent, hex and all.
 */
export function documentName(path: string, fromUpload: boolean): string {
  const base = path.split("/").filter(Boolean).pop() ?? path;
  return fromUpload ? base.replace(UPLOAD_PREFIX, "") || base : base;
}
