import { describe, expect, it, vi } from "vitest";

import { BUILTIN_COMMANDS, mergeWithUserCommands, searchCommands } from "./slash-commands";
import type { UserSlashCommandRecord } from "@/lib/slash-commands-api";

function record(overrides: Partial<UserSlashCommandRecord> = {}): UserSlashCommandRecord {
  return {
    id: "sc-1",
    name: "standup",
    prompt: "Summarise yesterday.",
    is_enabled: true,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** An override row: same table, no prompt, only a flag. */
function override(name: string, isEnabled: boolean): UserSlashCommandRecord {
  return record({ id: `ovr-${name}`, name, prompt: null, is_enabled: isEnabled });
}

const names = (commands: { name: string }[]) => commands.map((command) => command.name);

/**
 * The `/command` palette.
 *
 * Two layers fused into one list: built-ins defined in code, and a person's own
 * shortcuts fetched from the API. The distinction that matters is not where they
 * came from but what they do - a `client` command runs locally (clear the chat,
 * open settings) and a `send-as-message` command replaces what was typed with a
 * canned prompt. A custom command is always the second kind, because it *is* a
 * prompt.
 */
describe("the built-in commands", () => {
  it("gives every one a name, a description and something to do", () => {
    for (const command of BUILTIN_COMMANDS) {
      expect(command.name, command.name).toMatch(/^[a-z]+$/);
      expect(command.description.length, command.name).toBeGreaterThan(0);
      expect(command.source, command.name).toBe("builtin");
    }
  });

  it("has no two commands answering to the same word", () => {
    // Including aliases: two commands matching `/retry` would run whichever the
    // filter happened to return first.
    const words = BUILTIN_COMMANDS.flatMap((command) => [command.name, ...(command.aliases ?? [])]);

    expect(new Set(words).size).toBe(words.length);
  });

  it("runs the local action for each client command, and nothing else", () => {
    // Three commands, three different things, and each one has to reach its own
    // handler - `/clear` opening the settings panel is the kind of mix-up a
    // shared context makes easy.
    const context = {
      clearChat: vi.fn(),
      regenerateLast: vi.fn(),
      openSettings: vi.fn(),
    };
    const run = (name: string) => {
      const action = BUILTIN_COMMANDS.find((command) => command.name === name)!.action;
      if (action.kind !== "client") throw new Error(`${name} is not a client command`);
      action.run(context);
    };

    run("clear");
    expect(context.clearChat).toHaveBeenCalledTimes(1);
    expect(context.regenerateLast).not.toHaveBeenCalled();

    run("regen");
    expect(context.regenerateLast).toHaveBeenCalledTimes(1);

    run("settings");
    expect(context.openSettings).toHaveBeenCalledTimes(1);
  });

  it("sends a real prompt for each canned command", () => {
    // These are typed into the composer on the person's behalf, so an empty one
    // would send a blank turn.
    for (const command of BUILTIN_COMMANDS) {
      if (command.action.kind !== "send-as-message") continue;
      expect(command.action.replaceWith.length, command.name).toBeGreaterThan(20);
    }
  });
});

describe("merging in a person's own commands", () => {
  it("is the built-ins alone before the API has answered", () => {
    expect(mergeWithUserCommands([])).toEqual(BUILTIN_COMMANDS);
  });

  it("drops a built-in somebody switched off", () => {
    const first = BUILTIN_COMMANDS[0]!.name;

    expect(names(mergeWithUserCommands([override(first, false)]))).not.toContain(first);
  });

  it("keeps a built-in whose override says it is on", () => {
    // An override row exists for both answers; only `is_enabled` decides.
    const first = BUILTIN_COMMANDS[0]!.name;

    expect(names(mergeWithUserCommands([override(first, true)]))).toContain(first);
  });

  it("appends a custom command as a prompt to send", () => {
    const merged = mergeWithUserCommands([record()]);

    expect(merged.at(-1)).toMatchObject({
      name: "standup",
      source: "custom",
      action: { kind: "send-as-message", replaceWith: "Summarise yesterday." },
    });
  });

  it("drops a custom command somebody switched off", () => {
    expect(names(mergeWithUserCommands([record({ is_enabled: false })]))).not.toContain("standup");
  });

  it("keeps the built-ins first, so the list does not reorder as commands are added", () => {
    const merged = mergeWithUserCommands([record()]);

    expect(names(merged).slice(0, BUILTIN_COMMANDS.length)).toEqual(names(BUILTIN_COMMANDS));
  });

  it("describes a custom command by its prompt, flattened to one line", () => {
    // The palette row is one line; a prompt with newlines in it would break the
    // layout of every row after it.
    const merged = mergeWithUserCommands([
      record({ prompt: "  Summarise\n\n  yesterday's   standup  " }),
    ]);

    expect(merged.at(-1)?.description).toBe("Summarise yesterday's standup");
  });

  it("truncates a long prompt rather than letting it fill the palette", () => {
    const merged = mergeWithUserCommands([record({ prompt: "x".repeat(200) })]);

    expect(merged.at(-1)?.description).toHaveLength(78);
    expect(merged.at(-1)?.description.endsWith("…")).toBe(true);
  });

  it("leaves a prompt at the limit alone", () => {
    const merged = mergeWithUserCommands([record({ prompt: "y".repeat(80) })]);

    expect(merged.at(-1)?.description).toBe("y".repeat(80));
  });
});

describe("searching the palette", () => {
  const commands = mergeWithUserCommands([record({ name: "standup" })]);

  it("offers everything before anything is typed", () => {
    expect(searchCommands(commands, "")).toEqual(commands);
  });

  it("ignores the slash somebody is still typing", () => {
    // The composer passes the raw token, `/` and all.
    expect(names(searchCommands(commands, "/cle"))).toEqual(["clear"]);
    expect(names(searchCommands(commands, "//cle"))).toEqual(["clear"]);
  });

  it("matches an alias as readily as a name", () => {
    // `/retry` is what people type for `regen`.
    expect(names(searchCommands(commands, "retry"))).toEqual(["regen"]);
  });

  it("prefers what starts with the query over what merely contains it", () => {
    // Typing `s` should offer `settings` and `summarize`, not everything whose
    // description happens to mention a setting.
    const matched = names(searchCommands(commands, "s"));

    expect(matched).toContain("settings");
    expect(matched).toContain("summarize");
    expect(matched).not.toContain("clear");
  });

  it("falls back to a substring, and then to the description", () => {
    // Nothing starts with "gen", so the fallback is what finds `regen`; and
    // nothing is called "conversation", so only a description can match.
    expect(names(searchCommands(commands, "gen"))).toContain("regen");
    expect(names(searchCommands(commands, "conversation"))).toContain("summarize");
  });

  it("matches an alias by substring too", () => {
    expect(names(searchCommands(commands, "etry"))).toContain("regen");
  });

  it("is case-insensitive, because a composer capitalises", () => {
    expect(names(searchCommands(commands, "CLE"))).toEqual(["clear"]);
    expect(names(searchCommands(commands, "CONVERSATION"))).toContain("summarize");
  });

  it("offers nothing rather than everything for a query that matches nothing", () => {
    // An unfiltered palette under a typed query reads as a filter that is not
    // working.
    expect(searchCommands(commands, "zzz")).toEqual([]);
  });

  it("finds a person's own command by name", () => {
    expect(names(searchCommands(commands, "stand"))).toEqual(["standup"]);
  });
});
