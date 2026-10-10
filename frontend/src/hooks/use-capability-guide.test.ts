import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useCapabilityGuide } from "./use-capability-guide";

describe("useCapabilityGuide", () => {
  it("explains a capability with as many examples as it has", () => {
    const { result } = renderHook(() => useCapabilityGuide());

    const sandbox = result.current("sandbox");
    expect(sandbox?.name).toBe("Sandbox");
    expect(sandbox?.examples).toHaveLength(3);
    expect(result.current("media")?.examples).toHaveLength(1);
    expect(sandbox?.never).toMatch(/^Never reaches your computer/);
  });

  it("has nothing to say about a capability it has no words for", () => {
    const { result } = renderHook(() => useCapabilityGuide());

    expect(result.current("from_a_plugin")).toBeUndefined();
  });
});
