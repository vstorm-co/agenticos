import { beforeEach, describe, expect, it, vi } from "vitest";

import * as commands from "./slash-commands-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/**
 * A person's slash commands.
 *
 * Two row shapes share one table: a custom `/shortcut` carries a prompt, and a
 * built-in override carries only an on/off flag. They are created at different
 * endpoints for that reason - posting an override as a custom command would
 * store a command with no prompt, which nothing can run.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "sc-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "sc-1" });
  vi.mocked(apiClient.put).mockResolvedValue({ id: "sc-1" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "sc-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("slash command API", () => {
  it("unwraps the list", async () => {
    await expect(commands.listSlashCommands()).resolves.toEqual([{ id: "sc-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/me/slash-commands");
  });

  it("creates a custom command where a prompt belongs", async () => {
    await commands.createCustomCommand({ name: "standup", prompt: "Summarise yesterday." });

    expect(apiClient.post).toHaveBeenCalledWith("/me/slash-commands/custom", {
      name: "standup",
      prompt: "Summarise yesterday.",
    });
  });

  it("switches a built-in off through the upsert, which is idempotent by name", async () => {
    // PUT rather than POST: turning the same built-in off twice must not create a
    // second row that contradicts the first.
    await commands.upsertBuiltinOverride({ name: "summarise", is_enabled: false });

    expect(apiClient.put).toHaveBeenCalledWith("/me/slash-commands/builtin", {
      name: "summarise",
      is_enabled: false,
    });
  });

  it("patches and deletes by id", async () => {
    await commands.updateSlashCommand("sc-1", { name: "daily" });
    expect(apiClient.patch).toHaveBeenCalledWith("/me/slash-commands/sc-1", { name: "daily" });

    await commands.deleteSlashCommand("sc-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/me/slash-commands/sc-1");
  });
});
