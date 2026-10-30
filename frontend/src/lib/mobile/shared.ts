/**
 * "Share → AgenticOS" (#2097): what another app shared with the phone app,
 * read from it (`mobile/src-tauri/src/share.rs`) and turned into the files and
 * words the chat's composer takes.
 */

import { invokeShell, ShellError } from "@/lib/desktop/shell";

export interface SharedContent {
  text: string;
  files: File[];
  /** Files that could not be carried over - too large, or unreadable - by name. */
  refused: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function decode(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function parseFile(value: unknown): File {
  if (isRecord(value)) {
    const { name, mimeType, data } = value;
    if (typeof name === "string" && typeof mimeType === "string" && typeof data === "string") {
      return new File([decode(data)], name, { type: mimeType });
    }
  }
  throw new ShellError("malformed", "a shared file");
}

/** The app's answer to `take_shared`: nothing, or what was shared. */
export function parseShared(value: unknown): SharedContent | null {
  if (value === null) return null;
  if (isRecord(value)) {
    const { text, files, refused } = value;
    if (typeof text === "string" && Array.isArray(files) && isStrings(refused)) {
      return { text, files: files.map(parseFile), refused };
    }
  }
  throw new ShellError("malformed", "what was shared");
}

export async function takeShared(): Promise<SharedContent | null> {
  return parseShared(await invokeShell("take_shared"));
}
