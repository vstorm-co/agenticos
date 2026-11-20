import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { renderToString } from "react-dom/server";
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
  it("renders a stable placeholder on the server before browser capabilities are known", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const html = renderToString(<ViewportVisualFrame {...props} />);
    expect(html).not.toContain("<iframe");
    expect(html).toContain("height:400px");
  });

  it("opens an unseen drawing from the workspace and keeps it mounted after closing", () => {
    const { container, rerender } = render(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).toBeNull();

    rerender(<ViewportVisualFrame {...props} active fill />);
    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();

    rerender(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).toBe(frame);
    expect(lifecycle.mount).toHaveBeenCalledTimes(1);
    expect(lifecycle.unmount).not.toHaveBeenCalled();
  });

  it("mounts lazily and preserves the same iframe and interaction state across scrolling", () => {
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
    const frame = container.querySelector("iframe");
    act(() => observer.emit(box, false));
    expect(container.querySelector("iframe")).toBe(frame);
    expect(lifecycle.unmount).not.toHaveBeenCalled();
    act(() => observer.emit(box, true));
    expect(container.querySelector("iframe")).toBe(frame);
    expect(lifecycle.mount).toHaveBeenCalledTimes(1);
    unmount();
    expect(observer.disconnect).toHaveBeenCalledTimes(1);
  });

  it("keeps a streaming drawing and an opened workspace on the same live iframe", () => {
    const { container, rerender } = render(<ViewportVisualFrame {...props} done={false} />);
    const box = container.firstElementChild!;
    expect(container.querySelector("iframe")).not.toBeNull();
    act(() => Visibility.instances[0]!.emit(box, false));
    expect(container.querySelector("iframe")).not.toBeNull();
    const frame = container.querySelector("iframe");
    rerender(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).toBe(frame);
    act(() => Visibility.instances[0]!.emit(box, true));
    expect(container.querySelector("iframe")).not.toBeNull();
    rerender(<ViewportVisualFrame {...props} active fill />);
    expect(container.querySelector("iframe")).toBe(frame);
    rerender(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).toBe(frame);
    expect(lifecycle.mount).toHaveBeenCalledTimes(1);
  });

  it("still displays the drawing when the observer API is unavailable", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const { container } = render(<ViewportVisualFrame {...props} />);
    expect(container.querySelector("iframe")).not.toBeNull();
  });
});
