import { describe, expect, it } from "vitest";
import { graph, makeCatalog, makeDefinition, node } from "./fixtures";
import { resolveDefinitions } from "./topology";
import { rule9RequiredInputsBound } from "./rules";
const catalog = makeCatalog([
  makeDefinition({ id: "agent.run", config_schema: { type: "object" } }),
]);
describe("agent pin validation before testing", () => {
  it.each([{}, { agent: null }, { agent: { agent_id: "a", version_id: null } }])(
    "flags an incomplete catalog pin",
    (config) => {
      const value = graph({ entry: "a", nodes: [node("a", "agent.run", config)] });
      expect(rule9RequiredInputsBound(value, resolveDefinitions(value, catalog))).toContainEqual(
        expect.objectContaining({ field: "agent", code: "config-not-set" }),
      );
    },
  );
  it.each([{ agent: { agent_id: "a", version_id: "v" } }, { inline: { name: "Legacy" } }])(
    "accepts a full pin or a preserved legacy inline agent",
    (config) => {
      const value = graph({ entry: "a", nodes: [node("a", "agent.run", config)] });
      expect(rule9RequiredInputsBound(value, resolveDefinitions(value, catalog))).toEqual([]);
    },
  );
});
