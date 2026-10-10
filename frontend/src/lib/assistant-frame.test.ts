import { describe, expect, it } from "vitest";

import { inAssistantFrame, isAssistantFramePath } from "./assistant-frame";

describe("isAssistantFramePath", () => {
  it("recognises the frame with or without a locale prefix", () => {
    expect(isAssistantFramePath("/assistant-frame")).toBe(true);
    expect(isAssistantFramePath("/pl/assistant-frame")).toBe(true);
    expect(isAssistantFramePath("/pl")).toBe(false);
    expect(isAssistantFramePath("/agents")).toBe(false);
    expect(isAssistantFramePath("/assistant-frame/x")).toBe(false);
  });
});

describe("inAssistantFrame", () => {
  it("is false in the top-level console", () => {
    expect(inAssistantFrame()).toBe(false);
  });
});
