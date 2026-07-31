import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BUILTIN_COMMAND_LIST, isBuiltinEnabled, useSlashCommands } from "./use-slash-commands";
import * as api from "@/lib/slash-commands-api";
import type { UserSlashCommandRecord } from "@/lib/slash-commands-api";

vi.mock("@/lib/slash-commands-api", () => ({
  listSlashCommands: vi.fn(),
  createCustomCommand: vi.fn(),
  updateSlashCommand: vi.fn(),
  upsertBuiltinOverride: vi.fn(),
  deleteSlashCommand: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

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

async function hook(records: UserSlashCommandRecord[] = []) {
  vi.mocked(api.listSlashCommands).mockResolvedValue(records);
  const rendered = renderHook(() => useSlashCommands(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

beforeEach(() => vi.clearAllMocks());

/**
 * A person's slash commands, built-ins included.
 *
 * Two row shapes share one list and the difference is the whole thing: a custom
 * command carries a prompt, and a built-in override carries only a flag. So an
 * override is upserted *by name* rather than appended - a second row for the same
 * built-in would leave the effective list depending on which one the merge
 * happened to see last.
 *
 * The effective list is what the composer renders: the shipped built-ins, minus
 * the ones somebody switched off, plus their own.
 */
describe("useSlashCommands", () => {
  it("offers the shipped built-ins to somebody who has configured nothing", async () => {
    const result = await hook([]);

    expect(result.current.records).toEqual([]);
    expect(result.current.commands.length).toBe(BUILTIN_COMMAND_LIST.length);
  });

  it("adds a person's own commands to the built-ins", async () => {
    const result = await hook([record()]);

    expect(result.current.commands.map((command) => command.name)).toContain("standup");
  });

  it("drops a built-in somebody switched off", async () => {
    const first = BUILTIN_COMMAND_LIST[0]!.name;

    const result = await hook([override(first, false)]);

    expect(result.current.commands.map((command) => command.name)).not.toContain(first);
  });

  it("says what went wrong when the list could not be read", async () => {
    // The settings page shows this sentence; "Failed to load" would hide a 403.
    vi.mocked(api.listSlashCommands).mockRejectedValue(new Error("Not authenticated"));
    const { result } = renderHook(() => useSlashCommands(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not authenticated"));
  });

  it("still says something went wrong when the failure is not an error", async () => {
    // A rejected fetch can throw a string; the page still needs a sentence.
    vi.mocked(api.listSlashCommands).mockRejectedValue("boom");
    const { result } = renderHook(() => useSlashCommands(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Failed to load commands"));
  });

  it("says nothing went wrong when nothing did", async () => {
    const result = await hook([]);

    expect(result.current.error).toBeNull();
  });

  it("adds a created command to the list it just read", async () => {
    const result = await hook([]);
    vi.mocked(api.createCustomCommand).mockResolvedValue(record());

    await act(async () => {
      await result.current.createCustom({ name: "standup", prompt: "Summarise yesterday." });
    });

    await waitFor(() => expect(result.current.records).toHaveLength(1));
    expect(result.current.commands.map((command) => command.name)).toContain("standup");
  });

  it("lets a refused creation through, because the form has a field to blame", async () => {
    // A name already taken belongs beside the name field, not in a toast that
    // says "failed".
    const result = await hook([]);
    vi.mocked(api.createCustomCommand).mockRejectedValue(new Error("That name is taken"));

    await expect(result.current.createCustom({ name: "standup", prompt: "x" })).rejects.toThrow(
      "That name is taken",
    );
  });

  it("patches an edited command in place", async () => {
    const result = await hook([record()]);
    vi.mocked(api.updateSlashCommand).mockResolvedValue(record({ name: "daily" }));

    await act(async () => {
      await result.current.updateCustom("sc-1", { name: "daily" });
    });

    expect(api.updateSlashCommand).toHaveBeenCalledWith("sc-1", { name: "daily" });
    await waitFor(() => expect(result.current.records[0]?.name).toBe("daily"));
  });

  it("adds the first override for a built-in rather than nothing", async () => {
    const first = BUILTIN_COMMAND_LIST[0]!.name;
    const result = await hook([]);
    vi.mocked(api.upsertBuiltinOverride).mockResolvedValue(override(first, false));

    await act(async () => {
      await result.current.setBuiltinEnabled(first, false);
    });

    await waitFor(() => expect(result.current.records).toHaveLength(1));
    expect(result.current.commands.map((command) => command.name)).not.toContain(first);
  });

  it("replaces an existing override instead of adding a second row for it", async () => {
    // Two rows for one built-in leave the effective list depending on which the
    // merge saw last.
    const first = BUILTIN_COMMAND_LIST[0]!.name;
    const result = await hook([override(first, false)]);
    vi.mocked(api.upsertBuiltinOverride).mockResolvedValue(override(first, true));

    await act(async () => {
      await result.current.setBuiltinEnabled(first, true);
    });

    await waitFor(() => expect(result.current.records[0]?.is_enabled).toBe(true));
    expect(result.current.records).toHaveLength(1);
  });

  it("does not mistake a custom command for an override of the same name", async () => {
    // Both can be called `standup`; only the one with no prompt is the override.
    const result = await hook([record({ name: "standup" })]);
    vi.mocked(api.upsertBuiltinOverride).mockResolvedValue(override("standup", false));

    await act(async () => {
      await result.current.setBuiltinEnabled("standup", false);
    });

    await waitFor(() => expect(result.current.records).toHaveLength(2));
  });

  it("drops a removed command from the list", async () => {
    const result = await hook([record(), record({ id: "sc-2", name: "review" })]);
    vi.mocked(api.deleteSlashCommand).mockResolvedValue(undefined);

    await act(async () => {
      await result.current.remove("sc-2");
    });

    await waitFor(() => expect(result.current.records.map((row) => row.id)).toEqual(["sc-1"]));
  });

  it("refetches on demand", async () => {
    const result = await hook([]);

    await act(async () => {
      await result.current.refresh();
    });

    expect(api.listSlashCommands).toHaveBeenCalledTimes(2);
  });
});

describe("isBuiltinEnabled", () => {
  it("is on for a built-in nobody has touched", () => {
    // Absence of a row is the default, and the default is on.
    expect(isBuiltinEnabled("summarise", [])).toBe(true);
  });

  it("follows the override when there is one", () => {
    expect(isBuiltinEnabled("summarise", [override("summarise", false)])).toBe(false);
    expect(isBuiltinEnabled("summarise", [override("summarise", true)])).toBe(true);
  });

  it("ignores a custom command that happens to share the name", () => {
    expect(isBuiltinEnabled("summarise", [record({ name: "summarise", is_enabled: false })])).toBe(
      true,
    );
  });
});
