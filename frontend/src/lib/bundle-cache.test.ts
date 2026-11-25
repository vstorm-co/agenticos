import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { invalidateImportedResources } from "./bundle-cache";
import { qk } from "./query-keys";

it("marks newly imported catalogs stale without discarding unrelated conversation state", async () => {
  const client = new QueryClient();
  client.setQueryData(qk.kb.list(), ["Old KB"]);
  client.setQueryData(["conversation", "current"], { text: "Keep this conversation" });
  await invalidateImportedResources(client, {
    roots: { "workflow/root": "new" },
    created: { "knowledge_base/new": "new-kb" },
    reused: {},
    skipped: [],
  });
  expect(client.getQueryState(qk.kb.list())?.isInvalidated).toBe(true);
  expect(client.getQueryState(["conversation", "current"])?.isInvalidated).toBe(false);
  expect(client.getQueryData(["conversation", "current"])).toEqual({
    text: "Keep this conversation",
  });
});

it("refreshes each supported created catalog once and ignores reference-only kinds", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  await invalidateImportedResources(client, {
    roots: { "agent/root": "a" },
    created: Object.fromEntries(
      [
        "agent",
        "workflow",
        "context",
        "skill",
        "skill_version",
        "skill_fork",
        "model_profile",
        "knowledge_base",
        "mcp_connection",
        "unsupported",
      ].map((kind) => [`${kind}/new`, kind]),
    ),
    reused: {},
    skipped: [],
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.kb.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.providers.modelProfiles() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpServers.entries() });
  expect(
    invalidate.mock.calls.filter(
      ([args]) => JSON.stringify(args?.queryKey) === JSON.stringify(qk.skills.all()),
    ),
  ).toHaveLength(1);
});
