import { describe, expect, it } from "vitest";

import { inAssistantFrame, isConsoleFramePath } from "./assistant-frame";

describe("isConsoleFramePath", () => {
  it("recognises the frame with or without a locale prefix", () => {
    expect(isConsoleFramePath("/assistant-frame")).toBe(true);
    expect(isConsoleFramePath("/pl/assistant-frame")).toBe(true);
    expect(isConsoleFramePath("/pl")).toBe(false);
    expect(isConsoleFramePath("/agents")).toBe(false);
    expect(isConsoleFramePath("/assistant-frame/x")).toBe(false);
  });

  it("recognises the Builder's test frame", () => {
    expect(isConsoleFramePath("/agent-test-frame")).toBe(true);
    expect(isConsoleFramePath("/de/agent-test-frame")).toBe(true);
  });
});

describe("inAssistantFrame", () => {
  it("is false in the top-level console", () => {
    expect(inAssistantFrame()).toBe(false);
  });
});
