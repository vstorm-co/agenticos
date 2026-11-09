import { describe, expect, it } from "vitest";
import { toolLookupName } from "./tool-identity";
import { toolEntry } from "./tool-catalog";
import { isVisualTool, resolveVisual } from "./visuals";
import type { ToolCall } from "@/types/chat";

describe("the server-owned identity of a tool call", () => {
  it.each(["draw", "create_chart", "publish_artifact", "write_draft"])(
    "keeps the %s renderer after the model-facing name changes",
    (id) => {
      const renamed = { name: "my_operation", tool_id: id };
      expect(toolLookupName(renamed)).toBe(id);
      expect(toolEntry(toolLookupName(renamed))).toBe(toolEntry(id));
    },
  );

  it("falls back to names for old rows and ignores names for new external calls", () => {
    expect(toolLookupName({ name: "draw" })).toBe("draw");
    expect(toolLookupName({ name: "draw", tool_id: null, presentation_kind: null })).toBe("draw");
    const external = { name: "draw", tool_id: null, presentation_kind: "generic" as const };
    expect(toolEntry(toolLookupName(external))).toBeNull();
    expect(isVisualTool(toolLookupName(external))).toBe(false);
  });

  it("rebuilds a renamed drawing followed by a renamed revision", () => {
    const drawing: ToolCall = {
      id: "d",
      name: "sketch",
      tool_id: "draw",
      args: {
        title: "Tree",
        kind: "svg",
        content: "<svg><text>old</text></svg>",
      },
      status: "completed",
    };
    const revision: ToolCall = {
      id: "r",
      name: "adjust",
      tool_id: "revise_visual",
      args: {
        visual_id: "d",
        edits: [{ old: "old", new: "new" }],
      },
      status: "completed",
    };
    expect(
      resolveVisual(
        revision,
        new Map([
          ["d", drawing],
          ["r", revision],
        ]),
      )?.content,
    ).toContain("new");
  });
});
