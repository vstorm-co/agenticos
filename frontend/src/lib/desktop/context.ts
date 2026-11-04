/**
 * What was in front when quick ask opened (`desktop/src-tauri/src/context.rs`):
 * the app, its window, the selected text, the clipboard and Finder's selected
 * files - shown in the panel as chips, and written into the question for the
 * ones left on.
 */

import { invokeShell, ShellError } from "@/lib/desktop/shell";

export interface ActiveContext {
  app: string | null;
  window: string | null;
  selection: string | null;
  clipboard: string | null;
  /** Finder's selection, by name. */
  files: string[];
  /** Whether the app may read other apps' selections and window titles. */
  accessibility: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const isText = (value: unknown): value is string | null =>
  value === null || typeof value === "string";

/** The shell's capture, or `ShellError` for a shape this console does not know. */
export function parseActiveContext(value: unknown): ActiveContext {
  if (isRecord(value)) {
    const { app, window, selection, clipboard, files, accessibility } = value;
    if (
      isText(app) &&
      isText(window) &&
      isText(selection) &&
      isText(clipboard) &&
      Array.isArray(files) &&
      files.every((name) => typeof name === "string") &&
      typeof accessibility === "boolean"
    ) {
      return { app, window, selection, clipboard, files, accessibility };
    }
  }
  throw new ShellError("malformed", "what was in front");
}

/** The words a question carries with it, each under a heading saying where it came from. */
export interface ContextPassage {
  heading: string;
  text: string;
}

/**
 * The question, then each passage as a quotation under its heading - so the
 * agent, and anyone reading the conversation later, can tell the person's own
 * words from what they brought along.
 */
export function withContext(question: string, passages: readonly ContextPassage[]): string {
  const quoted = passages.map(
    ({ heading, text }) =>
      `${heading}\n${text
        .split("\n")
        .map((line) => `> ${line}`)
        .join("\n")}`,
  );
  return [question, ...quoted].join("\n\n");
}

/** The captured Finder selection as files to attach - the only files the shell will read. */
export async function takeContextFiles(): Promise<File[]> {
  const value = await invokeShell("take_context_files");
  if (!Array.isArray(value)) throw new ShellError("malformed", "the selected files");
  return value.map((item: unknown) => {
    if (isRecord(item) && typeof item.name === "string" && typeof item.data === "string") {
      const binary = atob(item.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      return new File([bytes], item.name);
    }
    throw new ShellError("malformed", "a selected file");
  });
}

export async function openAccessibilitySettings(): Promise<void> {
  await invokeShell("open_accessibility_settings");
}
