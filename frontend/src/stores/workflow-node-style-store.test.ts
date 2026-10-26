import { beforeEach, describe, expect, it } from "vitest";

import { useWorkflowNodeStyleStore } from "./workflow-node-style-store";

beforeEach(() => {
  useWorkflowNodeStyleStore.setState({ style: "colour" });
});

describe("useWorkflowNodeStyleStore", () => {
  it("draws steps in colour until told otherwise", () => {
    expect(useWorkflowNodeStyleStore.getState().style).toBe("colour");
  });

  it("keeps the choice in this browser, under its own key", () => {
    useWorkflowNodeStyleStore.getState().setStyle("simple");

    expect(useWorkflowNodeStyleStore.getState().style).toBe("simple");
    expect(JSON.parse(localStorage.getItem("workflow-node-style-storage") ?? "{}")).toMatchObject({
      state: { style: "simple" },
    });
  });
});
