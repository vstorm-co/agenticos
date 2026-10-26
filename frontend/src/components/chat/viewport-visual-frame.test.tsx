import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ViewportVisualFrame } from "./viewport-visual-frame";

const lifecycle = vi.hoisted(() => ({ mount: vi.fn(), unmount: vi.fn() }));
vi.mock("./visual-frame", () => ({
  VisualFrame: ({ title }: { title: string }) => {
    useEffect(() => {
      lifecycle.mount();
      return () => lifecycle.unmount();
    }, []);
    return <iframe title={title} />;
  },
}));

class Visibility implements IntersectionObserver {
  static instances: Visibility[] = [];
  readonly root = null;
  readonly rootMargin: string;
  readonly scrollMargin = "";
  readonly thresholds = [0];
  target: Element | null = null;
  disconnect = vi.fn();
  unobserve = vi.fn();
  takeRecords = () => [];
  constructor(
    private readonly callback: IntersectionObserverCallback,
    options?: IntersectionObserverInit,
  ) {
    this.rootMargin = options?.rootMargin ?? "0px";
    Visibility.instances.push(this);
  }
  observe(target: Element) {
    this.target = target;
  }
  emit(target: Element, isIntersecting: boolean) {
    const rect = target.getBoundingClientRect();
    this.callback(
      [
        {
          target,
          isIntersecting,
          intersectionRatio: Number(isIntersecting),
          boundingClientRect: rect,
          intersectionRect: rect,
          rootBounds: null,
          time: 0,
        },
      ],
      this,
    );
  }
}

class Size implements ResizeObserver {
  static instances: Size[] = [];
  disconnect = vi.fn();
  unobserve = vi.fn();
  observe = vi.fn();
  constructor(private readonly callback: ResizeObserverCallback) {
    Size.instances.push(this);
  }
  emit(target: Element, height: number) {
    const rect = new DOMRect(0, 0, 600, height);
    this.callback(
      [
        {
          target,
          contentRect: rect,
          borderBoxSize: [],
          contentBoxSize: [],
          devicePixelContentBoxSize: [],
        },
      ],
      this,
    );
  }
}

const props = { kind: "svg" as const, title: "Flow", content: "<svg/>", done: true, height: 400 };
beforeEach(() => {
  vi.clearAllMocks();
  Visibility.instances = [];
  Size.instances = [];
  vi.stubGlobal("IntersectionObserver", Visibility);
  vi.stubGlobal("ResizeObserver", Size);
});
afterEach(() => vi.unstubAllGlobals());

describe("visual frames in history", () => {
  it("mounts near the viewport, preserves the measured footprint, and releases resources offscreen", () => {
    const { container, unmount } = render(<ViewportVisualFrame {...props} />);
    const box = container.firstElementChild!;
    const observer = Visibility.instances[0]!;
    expect(container.querySelector("iframe")).toBeNull();
    expect(box).toHaveStyle({ height: "400px" });
    act(() => observer.emit(document.createElement("div"), true));
    expect(container.querySelector("iframe")).toBeNull();
    act(() => observer.emit(box, true));
    expect(container.querySelector("iframe")).not.toBeNull();
    const resize = Size.instances.at(-1)!;
    act(() => {
      resize.emit(document.createElement("div"), 999);
      resize.emit(box, 0);
      resize.emit(box, 275);
    });
    act(() => observer.emit(box, false));
    expect(container.querySelector("iframe")).toBeNull();
    expect(box).toHaveStyle({ height: "275px" });
    expect(lifecycle.unmount).toHaveBeenCalledTimes(1);
    expect(resize.disconnect).toHaveBeenCalledTimes(1);
    act(() => observer.emit(box, true));
    expect(lifecycle.mount).toHaveBeenCalledTimes(2);
    unmount();
    expect(observer.disconnect).toHaveBeenCalledTimes(1);
  });

  it("keeps a streaming drawing live and suspends the inline copy while fullscreen is open", () => {
    const { container, rerender } = render(<ViewportVisualFrame {...props} done={false} />);
    const box = container.firstElementChild!;
    expect(container.querySelector("iframe")).not.toBeNull();
    act(() => Visibility.instances[0]!.emit(box, false));
    expect(container.querySelector("iframe")).not.toBeNull();
    rerender(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).toBeNull();
    act(() => Visibility.instances[0]!.emit(box, true));
    expect(container.querySelector("iframe")).not.toBeNull();
    rerender(<ViewportVisualFrame {...props} suspended />);
    expect(container.querySelector("iframe")).toBeNull();
    rerender(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).not.toBeNull();
  });

  it("still displays the drawing when the observer API is unavailable", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const { container } = render(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).not.toBeNull();
  });
});
