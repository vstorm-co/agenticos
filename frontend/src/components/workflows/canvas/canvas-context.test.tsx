import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  type CanvasInteraction,
  CanvasInteractionProvider,
  useCanvasInteraction,
} from "./canvas-context";

describe("useCanvasInteraction", () => {
  it("throws when a node renders outside the provider", () => {
    // Silence React's error-boundary console noise for the expected throw.
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderHook(() => useCanvasInteraction())).toThrow(/CanvasInteractionProvider/);
    spy.mockRestore();
  });

  it("returns the interaction supplied by the provider", () => {
    const value: CanvasInteraction = {
      readOnly: false,
      connectSource: null,
      beginConnect: vi.fn(),
      completeConnect: vi.fn(),
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <CanvasInteractionProvider value={value}>{children}</CanvasInteractionProvider>
    );
    const { result } = renderHook(() => useCanvasInteraction(), { wrapper });
    expect(result.current).toBe(value);
  });
});
