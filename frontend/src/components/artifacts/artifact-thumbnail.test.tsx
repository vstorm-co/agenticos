import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactThumbnail } from "./artifact-thumbnail";

const useArtifactViewMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
}));

type ObserverCallback = (
  entries: { isIntersecting: boolean; contentRect: { width: number } }[],
) => void;

/** Records each observer's callback so a test can say when the card came into view. */
function installObservers() {
  const seen: { intersection?: ObserverCallback; resize?: ObserverCallback } = {};
  class FakeIntersection {
    constructor(callback: ObserverCallback) {
      seen.intersection = callback;
    }
    observe() {}
    disconnect() {}
  }
  class FakeResize {
    constructor(callback: ObserverCallback) {
      seen.resize = callback;
    }
    observe() {}
    disconnect() {}
  }
  vi.stubGlobal("IntersectionObserver", FakeIntersection);
  vi.stubGlobal("ResizeObserver", FakeResize);
  return seen;
}

describe("ArtifactThumbnail", () => {
  beforeEach(() => useArtifactViewMock.mockReset());
  afterEach(() => vi.unstubAllGlobals());

  it("mints no address and loads no page until the card nears the viewport", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    vi.stubGlobal("ResizeObserver", undefined);
    useArtifactViewMock.mockReturnValue({ data: undefined });

    const { container } = render(<ArtifactThumbnail artifactId="a1" title="Report" />);

    expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", null, false);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("loads the page, inert and sandboxed, once near, scaled to fit, and fades it in", () => {
    const seen = installObservers();
    useArtifactViewMock.mockReturnValue({ data: undefined });
    const { container, rerender } = render(<ArtifactThumbnail artifactId="a1" title="Report" />);

    act(() => seen.intersection?.([{ isIntersecting: false, contentRect: { width: 0 } }]));
    expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", null, false);
    act(() => seen.intersection?.([{ isIntersecting: true, contentRect: { width: 0 } }]));
    expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", null, true);

    useArtifactViewMock.mockReturnValue({ data: { url: "https://content.test/t" } });
    rerender(<ArtifactThumbnail artifactId="a1" title="Report" />);
    act(() => seen.resize?.([{ isIntersecting: false, contentRect: { width: 640 } }]));
    act(() => seen.resize?.([]));

    const frame = container.querySelector("iframe")!;
    // Script, so a chart a library draws is on the card (#1968), and nothing
    // else: no dialogs over the grid, no popups, never this console's origin.
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame).toHaveAttribute("tabindex", "-1");
    expect(frame).toHaveAttribute("aria-hidden", "true");
    expect(frame.style.transform).toBe("scale(0.5)");
    expect(frame).toHaveAttribute("data-loaded", "false");

    fireEvent.load(frame);

    expect(frame).toHaveAttribute("data-loaded", "true");
    expect(screen.getByTitle("Report")).toBe(frame);
  });

  it("unmounts the page when the card leaves the viewport, and paints it again on return", () => {
    const seen = installObservers();
    useArtifactViewMock.mockReturnValue({
      data: { url: "https://content.test/t" },
      isError: false,
    });
    const { container } = render(<ArtifactThumbnail artifactId="a1" title="Report" />);

    act(() => seen.intersection?.([{ isIntersecting: true, contentRect: { width: 0 } }]));
    fireEvent.load(container.querySelector("iframe")!);
    expect(container.querySelector("[data-unavailable]")).toBeNull();

    // A scripted page in a card nobody can see is stopped, not left running.
    act(() => seen.intersection?.([{ isIntersecting: false, contentRect: { width: 0 } }]));
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("[data-unavailable]")).not.toBeNull();

    act(() => seen.intersection?.([{ isIntersecting: true, contentRect: { width: 0 } }]));
    expect(container.querySelector("iframe")).toHaveAttribute("data-loaded", "false");
  });

  it("ignores an observer call that reports no entry", () => {
    const seen = installObservers();
    useArtifactViewMock.mockReturnValue({ data: undefined });
    render(<ArtifactThumbnail artifactId="a1" title="Report" />);
    act(() => seen.intersection?.([]));
    expect(useArtifactViewMock).toHaveBeenLastCalledWith("a1", null, false);
  });

  it("stops pulsing once the address is refused, rather than loading forever", () => {
    const seen = installObservers();
    useArtifactViewMock.mockReturnValue({ data: undefined, isError: false });
    const { container, rerender } = render(<ArtifactThumbnail artifactId="a1" title="Report" />);
    act(() => seen.intersection?.([{ isIntersecting: true, contentRect: { width: 0 } }]));
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    useArtifactViewMock.mockReturnValue({ data: undefined, isError: true });
    rerender(<ArtifactThumbnail artifactId="a1" title="Report" />);

    expect(container.querySelector("[data-unavailable='true']")).not.toBeNull();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
    expect(container.querySelector("iframe")).toBeNull();
  });
});
