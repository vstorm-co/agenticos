import { expect, it } from "vitest";
import type { BundlePreview, BundleResource } from "./portability-api";
import { plannedOmissions } from "./bundle-review";

function preview(
  kind: string,
  paths: (string | number)[][],
  definition: Record<string, unknown> = {},
): BundlePreview {
  const root: BundleResource = {
    key: `${kind}/root`,
    kind,
    name: "Root",
    source_id: null,
    source_parent_id: null,
    source_version: null,
    definition,
    references: paths.map((path) => ({
      path,
      target: "secret/one",
      is_key: false,
      destination_field: "id",
    })),
    included: ["definition"],
  };
  return {
    bundle: {
      format: "agenticos.bundle",
      format_version: 1,
      roots: [root.key],
      resources: [root],
      assets: [],
    },
    options: [],
  };
}
it("summarizes whole owned binding removals once while leaving kept resources alone", () => {
  const data = preview(
    "workflow",
    [
      ["graph", "nodes", 0, "config", "agent", "agent_id"],
      ["graph", "nodes", 0, "config", "agent", "version_id"],
      ["graph", "bindings", 1, "source", "table_id"],
    ],
    { omitted: [["graph", "bindings", 0]] },
  );
  expect(
    plannedOmissions(data, {
      "workflow/root": { action: "create" },
      "secret/one": { action: "skip" },
    }),
  ).toEqual({
    "workflow/root": [
      ["graph", "bindings", 0],
      ["graph", "nodes", 0, "config", "agent"],
      ["graph", "bindings", 1],
    ],
  });
  expect(
    plannedOmissions(data, {
      "workflow/root": { action: "reuse", destination_id: "existing" },
      "secret/one": { action: "skip" },
    }),
  ).toEqual({});
});
it("ignores malformed hint data and keeps unknown fields as explicit reference paths", () => {
  const data = preview(
    "workflow",
    [
      ["settings", "error_workflow_id"],
      ["graph", "nodes", 0, "config", "inline", "mcp_servers", 0, "connection_id"],
    ],
    { omitted: ["not a path", [], [false], [0, -1]] },
  );
  expect(
    plannedOmissions(data, {
      "workflow/root": { action: "create" },
      "secret/one": { action: "skip" },
    }),
  ).toEqual({
    "workflow/root": [
      ["settings", "error_workflow_id"],
      ["graph", "nodes", 0, "config", "inline", "mcp_servers", 0],
    ],
  });
  const empty = preview("context", [["secret_id"]]);
  expect(
    plannedOmissions(empty, {
      "context/root": { action: "create" },
      "secret/one": { action: "reuse", destination_id: "existing" },
    }),
  ).toEqual({});
});

it("offers destination pickers only for resource adapters implemented by the API", async () => {
  const { supportsImportDestination } = await import("./bundle-review");
  for (const kind of [
    "agent",
    "workflow",
    "knowledge_base",
    "local_service",
    "agent_version",
    "table",
  ])
    expect(supportsImportDestination(kind)).toBe(true);
  for (const kind of ["app", "project", "channel_bot", "embedding_endpoint"])
    expect(supportsImportDestination(kind)).toBe(false);
});

it("keeps non-agent references exact and removes only indexed agent bindings", () => {
  const { bundle: agent, ...rest } = preview("agent", [
    ["mcp_servers", 0, "connection_id"],
    ["capabilities", 0, "config", "mcp_servers", "specific"],
  ]);
  expect(
    plannedOmissions(
      { ...rest, bundle: agent },
      { "agent/root": { action: "create" }, "secret/one": { action: "skip" } },
    ),
  ).toEqual({
    "agent/root": [
      ["mcp_servers", 0],
      ["capabilities", 0, "config", "mcp_servers", "specific"],
    ],
  });
  const context = preview("context", [["secret_id"]]);
  expect(
    plannedOmissions(context, {
      "context/root": { action: "create" },
      "secret/one": { action: "skip" },
    }),
  ).toEqual({ "context/root": [["secret_id"]] });
});
