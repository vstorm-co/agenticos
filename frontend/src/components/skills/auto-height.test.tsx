import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AutoHeight } from "./auto-height";

describe("AutoHeight", () => {
  it("holds its children's measured height and follows it when they resize", () => {
    let resized: ResizeObserverCallback = () => undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          resized = callback;
        }
        observe = vi.fn();
        disconnect = disconnect;
      },
    );
    const offset = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(40);

    const { unmount } = render(
      <AutoHeight>
        <p>Note</p>
      </AutoHeight>,
    );
    const outer = screen.getByText("Note").parentElement?.parentElement as HTMLElement;
    expect(outer.style.height).toBe("40px");

    offset.mockReturnValue(120);
    act(() => resized([], {} as ResizeObserver));
    expect(outer.style.height).toBe("120px");

    unmount();
    expect(disconnect).toHaveBeenCalled();
    offset.mockRestore();
    vi.unstubAllGlobals();
  });
});
