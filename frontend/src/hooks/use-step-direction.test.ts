import { renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useStepDirection } from "./use-step-direction";

it("tracks forward, backward and skipped steps without replaying on ordinary updates", () => {
  const { result, rerender } = renderHook(({ index }) => useStepDirection(index), {
    initialProps: { index: 0 },
  });
  expect(result.current).toBe("forward");
  rerender({ index: 3 });
  expect(result.current).toBe("forward");
  rerender({ index: 1 });
  expect(result.current).toBe("backward");
  rerender({ index: 1 });
  expect(result.current).toBe("backward");
  rerender({ index: 2 });
  expect(result.current).toBe("forward");
});
