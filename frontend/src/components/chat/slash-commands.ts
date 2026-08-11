/**
 * Slash command registry - drives the `/command` palette in <ChatInput>.
 *
 * Two layers:
 *   - BUILTIN_COMMANDS below - defined in code, shared across every user.
 *     Some are "client" actions (clear chat, open settings); others send a
 *     canned prompt as a user message.
 *   - User-defined commands fetched from `/api/me/slash-commands`. Always
 *     "send-as-message" - they're just shortcuts for prompts the user types
 *     a lot. Settings page lets users disable individual built-ins, too.
 *
 * `mergeWithUserCommands()` fuses the two - that's what <ChatContainer> hands
 * down to <ChatInput>. It takes the caller's `chat.commands` translator, because the
 * built-ins hold keys rather than sentences (#446).
 */

import type { Translate } from "@/lib/agent-step-captions";
import type { UserSlashCommandRecord } from "@/lib/slash-commands-api";

export type SlashCommandAction =
  | { kind: "client"; run: (ctx: SlashCommandContext) => void }
  | { kind: "send-as-message"; replaceWith: string };

export interface SlashCommand {
  /** No leading slash - e.g. "clear", "regen". */
  name: string;
  /** One-line description shown in the palette, ready to render. */
  description: string;
  /** Optional alias slugs that also resolve to this command. */
  aliases?: string[];
  action: SlashCommandAction;
  /** Marks user-defined entries so the UI can label/edit them differently. */
  source?: "builtin" | "custom";
}

/**
 * A built-in before its copy has been resolved.
 *
 * Two shapes rather than one because only half of a `SlashCommand`'s text is copy: a
 * built-in's description is a message in the catalog, and a custom command's is a
 * preview of the prompt its owner typed. A module cannot call a translator, so the
 * built-ins hold keys under `chat.commands` and `mergeWithUserCommands` resolves them
 * (#446).
 *
 * `replaceWith` is a key too: it becomes the reader's own message in the transcript,
 * so a Polish reader must not find an English sentence there over their own name - and
 * an agent answers in the language it was asked in.
 */
export interface BuiltinSlashCommand {
  name: string;
  descriptionKey: string;
  aliases?: string[];
  action:
    | { kind: "client"; run: (ctx: SlashCommandContext) => void }
    | { kind: "send-as-message"; replaceWithKey: string };
}

export interface SlashCommandContext {
  /** Clear all messages from the chat. */
  clearChat: () => void;
  /** Trigger a regeneration of the last assistant turn (no-op if none). */
  regenerateLast: () => void;
  /** Open the model picker / chat settings panel. */
  openSettings: () => void;
}

export const BUILTIN_COMMANDS: BuiltinSlashCommand[] = [
  {
    name: "clear",
    descriptionKey: "clearDescription",
    aliases: ["reset"],
    action: { kind: "client", run: (ctx) => ctx.clearChat() },
  },
  {
    name: "regen",
    descriptionKey: "regenDescription",
    aliases: ["regenerate", "retry"],
    action: { kind: "client", run: (ctx) => ctx.regenerateLast() },
  },
  {
    name: "settings",
    descriptionKey: "settingsDescription",
    action: { kind: "client", run: (ctx) => ctx.openSettings() },
  },
  {
    name: "summarize",
    descriptionKey: "summarizeDescription",
    action: { kind: "send-as-message", replaceWithKey: "summarizePrompt" },
  },
  {
    name: "explain",
    descriptionKey: "explainDescription",
    action: { kind: "send-as-message", replaceWithKey: "explainPrompt" },
  },
];

/** One built-in with its copy resolved against `chat.commands`. */
export function resolveBuiltin(command: BuiltinSlashCommand, t: Translate): SlashCommand {
  return {
    name: command.name,
    description: t(command.descriptionKey),
    aliases: command.aliases,
    action:
      command.action.kind === "client"
        ? command.action
        : { kind: "send-as-message", replaceWith: t(command.action.replaceWithKey) },
    source: "builtin",
  };
}

/**
 * Merge built-ins with the user's overrides + custom commands.
 *
 *   - Built-in disabled by user → dropped from the result.
 *   - User-defined custom command → appended (always "send-as-message").
 *   - Custom commands marked is_enabled=false → dropped.
 *
 * Pass an empty array for `userRecords` (e.g. before the API responds) to
 * get plain BUILTIN_COMMANDS.
 */
export function mergeWithUserCommands(
  userRecords: UserSlashCommandRecord[],
  t: Translate,
): SlashCommand[] {
  const overridesByName = new Map<string, UserSlashCommandRecord>();
  const customs: SlashCommand[] = [];

  for (const r of userRecords) {
    if (r.prompt === null) {
      // Built-in override row - only the is_enabled flag matters.
      overridesByName.set(r.name, r);
    } else if (r.is_enabled) {
      customs.push({
        name: r.name,
        description: previewPrompt(r.prompt),
        action: { kind: "send-as-message", replaceWith: r.prompt },
        source: "custom",
      });
    }
  }

  const builtins = BUILTIN_COMMANDS.filter((c) => {
    const ovr = overridesByName.get(c.name);
    return ovr ? ovr.is_enabled : true;
  }).map((command) => resolveBuiltin(command, t));

  return [...builtins, ...customs];
}

/** Truncate a stored prompt for the palette description line. */
function previewPrompt(prompt: string): string {
  const oneLine = prompt.replace(/\s+/g, " ").trim();
  return oneLine.length > 80 ? oneLine.slice(0, 77) + "…" : oneLine;
}

/**
 * Filter commands by a query - matches name + aliases by prefix, falls back
 * to substring on description.
 */
export function searchCommands(commands: SlashCommand[], query: string): SlashCommand[] {
  const q = query.toLowerCase().replace(/^\/+/, "");
  if (!q) return commands;
  const prefix = commands.filter((c) =>
    [c.name, ...(c.aliases ?? [])].some((s) => s.startsWith(q)),
  );
  if (prefix.length > 0) return prefix;
  return commands.filter(
    (c) =>
      c.name.includes(q) ||
      c.aliases?.some((a) => a.includes(q)) ||
      c.description.toLowerCase().includes(q),
  );
}
