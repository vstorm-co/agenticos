import { expect, it } from "vitest";
import { capabilityGroups } from "./capability-groups";
import type { CapabilityCatalogEntry } from "@/types/agents";
import { unboundBinding } from "./agent-spec";

function entry(
  id: string,
  category = "analysis",
  recommended: boolean | null = null,
): CapabilityCatalogEntry {
  return {
    id,
    name: id,
    category,
    recommended: recommended ? unboundBinding(id) : null,
    requires_secret: null,
    description: "",
    tools: [],
    contracts: [],
    config_schema: {},
    scopes: [],
    side_effecting: false,
    voice: "live",
  };
}

it("puts work first, keeps installed harnesses together, and leaves tuning last", () => {
  const groups = capabilityGroups(
    [
      entry("compaction"),
      entry("thinking", "reasoning"),
      entry("coding_agent"),
      entry("sandbox"),
      entry("external_acp"),
      entry("charts"),
      entry("future", "new"),
      entry("other", "another"),
    ],
    new Set(),
  );
  expect(groups.map((group) => group.name)).toEqual([
    "basics",
    "outputs",
    "delegation",
    "another",
    "new",
    "advanced",
  ]);
  expect(groups[2]?.entries.map((item) => item.id)).toEqual(["coding_agent", "external_acp"]);
  expect(groups.at(-1)?.entries.map((item) => item.id)).toEqual(["compaction", "thinking"]);
});

it("sorts enabled, then recommended, then names within the same group", () => {
  const groups = capabilityGroups(
    [
      entry("charts"),
      entry("visuals", "analysis", true),
      entry("artifacts"),
      entry("image_generation"),
    ],
    new Set(["image_generation"]),
  );
  expect(groups[0]?.entries.map((item) => item.id)).toEqual([
    "image_generation",
    "visuals",
    "artifacts",
    "charts",
  ]);
  expect(capabilityGroups([], new Set())).toEqual([]);
});
