import { useRef } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useTabIndicator } from "./use-tab-indicator";

function Strip({ selected }: { selected: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useTabIndicator(ref);
  return (
    <div ref={ref} data-testid="strip">
      <button role="tab" aria-selected={selected === "one"}>
        One
      </button>
      <button role="tab" aria-selected={selected === "two"}>
        Two
      </button>
    </div>
  );
}
afterEach(() => vi.restoreAllMocks());
it("moves to the selected tab, updates after resizing, and removes a missing selection", async () => {
  let width = 80;
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(() => width);
  vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.textContent === "Two" ? 100 : 0;
  });
  const callbacks: (() => void)[] = [];
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class implements ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        callbacks.push(() => callback([], this));
      }
      observe() {}
      unobserve() {}
      disconnect = disconnect;
    },
  );
  try {
    const view = render(<Strip selected="one" />);
    const strip = view.getByTestId("strip");
    expect(strip).toHaveAttribute("data-indicator-ready");
    expect(strip.style.getPropertyValue("--tab-x")).toBe("0px");
    view.rerender(<Strip selected="two" />);
    await waitFor(() => expect(strip.style.getPropertyValue("--tab-x")).toBe("100px"));
    width = 120;
    act(() => callbacks[0]?.());
    expect(strip.style.getPropertyValue("--tab-width")).toBe("120px");
    view.rerender(<Strip selected={null} />);
    await waitFor(() => expect(strip).not.toHaveAttribute("data-indicator-ready"));
    view.unmount();
    expect(disconnect).toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
  }
});

it("attaches when a conditional strip becomes available", () => {
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(80);
  function Conditional({ visible }: { visible: boolean }) {
    const ref = useRef<HTMLDivElement>(null);
    useTabIndicator(ref, visible);
    return visible ? (
      <div ref={ref} data-testid="conditional">
        <button aria-pressed>Selected</button>
      </div>
    ) : null;
  }
  const view = render(<Conditional visible={false} />);
  view.rerender(<Conditional visible />);
  expect(view.getByTestId("conditional")).toHaveAttribute("data-indicator-ready");
});
