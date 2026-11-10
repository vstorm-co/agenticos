import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { usePanZoom } from "./use-pan-zoom";

function viewportOf(width: number, height: number): HTMLDivElement {
  const element = document.createElement("div");
  element.getBoundingClientRect = () =>
    ({ x: 0, y: 0, top: 0, left: 0, right: width, bottom: height, width, height }) as DOMRect;
  return element;
}

describe("usePanZoom", () => {
  it("zooms from the viewport's centre, keeping that point still", () => {
    const { result } = renderHook(() => usePanZoom());
    result.current.viewport.current = viewportOf(200, 100);

    act(() => result.current.zoomFromCentre(2));

    expect(result.current.view).toEqual({ scale: 2, x: -100, y: -50 });
  });

  it("holds the scale within its bounds", () => {
    const { result } = renderHook(() => usePanZoom());
    result.current.viewport.current = viewportOf(200, 100);

    act(() => result.current.zoomFromCentre(100));

    expect(result.current.view.scale).toBe(2.5);
  });

  it("resets to the home it was given, not to the origin", () => {
    const home = { x: 12, y: -8, scale: 0.5 };
    const { result } = renderHook(() => usePanZoom(home));
    result.current.viewport.current = viewportOf(200, 100);
    act(() => result.current.zoomFromCentre(2));

    act(() => result.current.resetView());

    expect(result.current.view).toEqual(home);
  });

  it("leaves the view alone before there is a viewport to measure", () => {
    const { result } = renderHook(() => usePanZoom());

    act(() => result.current.zoomFromCentre(2));

    expect(result.current.view).toEqual({ x: 0, y: 0, scale: 1 });
  });
});
