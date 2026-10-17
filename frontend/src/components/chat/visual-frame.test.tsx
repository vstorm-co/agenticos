import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualFrame } from "./visual-frame";

vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ artifactUrl: "https://content.example.com" }),
}));

/** An observer that reports the panel as `width` wide the moment it is watched. */
function panelOf(width: number) {
  return class {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(target: Element) {
      this.callback(
        [{ target, contentRect: { width } } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      );
    }
    unobserve() {}
    disconnect() {}
  };
}

function frameOf(): HTMLIFrameElement {
  return document.querySelector("iframe") as HTMLIFrameElement;
}

/** What the frame is clipped to: the size it is drawn at. */
function sizerOf(): HTMLElement {
  return frameOf().parentElement as HTMLElement;
}

/** The box the drawing sits in, which scrolls when it is zoomed past it. */
function boxOf(): HTMLElement {
  return sizerOf().parentElement as HTMLElement;
}

/** The frame saying something to the console, as its own window. */
function say(data: unknown) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", { data, source: frameOf().contentWindow as Window }),
    );
  });
}

const original = global.ResizeObserver;

describe("VisualFrame", () => {
  beforeEach(() => {
    global.ResizeObserver = panelOf(600) as unknown as typeof ResizeObserver;
  });
  afterEach(() => {
    global.ResizeObserver = original;
    vi.useRealTimers();
  });

  it("frames the renderer on the content origin under the app sandbox", () => {
    render(<VisualFrame kind="svg" title="Flow" content="" done={false} height={480} />);
    const frame = frameOf();
    expect(frame.getAttribute("src")).toBe(
      "https://content.example.com/api/v1/artifact-content/visual-frame",
    );
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-modals");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("scrolling")).toBe("no");
  });

  it("posts the drawing as it grows, then once more as final", () => {
    const { rerender } = render(
      <VisualFrame kind="html" title="T" content="<p>a" done={false} height={480} />,
    );
    const posted = vi.spyOn(frameOf().contentWindow as Window, "postMessage");

    say({ type: "agenticos:visual-ready" });
    expect(posted).toHaveBeenLastCalledWith(
      expect.objectContaining({ phase: "stream", content: "<p>a" }),
      "*",
    );

    rerender(<VisualFrame kind="html" title="T" content="<p>ab</p>" done height={480} />);
    expect(posted).toHaveBeenLastCalledWith(
      { type: "agenticos:visual", phase: "final", kind: "html", title: "T", content: "<p>ab</p>" },
      "*",
    );
    const count = posted.mock.calls.length;
    rerender(<VisualFrame kind="html" title="T" content="<p>abc</p>" done height={480} />);
    expect(posted).toHaveBeenCalledTimes(count);
  });

  it("posts nothing before the renderer is ready, nor an empty drawing", () => {
    render(<VisualFrame kind="svg" title="T" content="" done={false} height={480} />);
    const posted = vi.spyOn(frameOf().contentWindow as Window, "postMessage");
    say({ type: "agenticos:visual-ready" });
    expect(posted).not.toHaveBeenCalled();
  });

  it("shows a page whole, shrunk only past the preview's height", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} />);
    const box = boxOf();
    expect(box.style.height).toBe("300px");

    say({ type: "agenticos:visual-size", height: 1120 });
    expect(frameOf().style.transform).toBe("scale(0.5)");
    expect(box.style.height).toBe("560px");
    expect(frameOf().style.width).toBe("600px");
  });

  it("holds a page that keeps growing itself", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} />);
    // The first report sets the height; four growths after it are believed.
    for (let height = 400; height <= 1000; height += 100) {
      say({ type: "agenticos:visual-size", height });
    }
    expect(frameOf().style.height).toBe("800px");
  });

  it("fits an SVG by its viewBox instead of measuring it", () => {
    render(<VisualFrame kind="svg" title="T" content="<svg/>" done height={480} aspect={2} />);
    expect(frameOf().style.width).toBe("280px");
    expect(frameOf().style.height).toBe("560px");
    expect(sizerOf().style.marginLeft).toBe("160px");
  });

  it("zooms an SVG by drawing it larger, in a box that scrolls", () => {
    render(
      <VisualFrame kind="svg" title="T" content="<svg/>" done height={480} aspect={2} zoom={2} />,
    );
    expect(frameOf().style.width).toBe("560px");
    expect(frameOf().style.height).toBe("1120px");
    expect(frameOf().style.transform).toBe("");
    expect(sizerOf().style.marginLeft).toBe("20px");
    expect(boxOf().style.height).toBe("560px");
    expect(boxOf().className).toContain("overflow-auto");
  });

  it("zooms a page by scaling it, clipped to what it shows", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} zoom={1.5} />);
    say({ type: "agenticos:visual-size", height: 1120 });
    expect(frameOf().style.transform).toBe("scale(0.75)");
    expect(sizerOf().style.width).toBe("450px");
    expect(sizerOf().style.height).toBe("840px");
    expect(sizerOf().style.marginLeft).toBe("75px");
  });

  it("keeps a page that fits unscrolled", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} zoom={0.5} />);
    expect(boxOf().className).toContain("overflow-hidden");
    expect(sizerOf().style.width).toBe("300px");
  });

  it("waits for the panel's width before showing anything", () => {
    global.ResizeObserver = original;
    render(<VisualFrame kind="svg" title="T" content="<svg/>" done height={300} aspect={1} />);
    expect(frameOf().style.visibility).toBe("hidden");
    expect(boxOf().style.height).toBe("300px");
  });

  it("fills its parent full screen", () => {
    render(<VisualFrame kind="svg" title="T" content="<svg/>" done height={300} fill />);
    expect(frameOf().style.width).toBe("100%");
    expect(frameOf().style.height).toBe("100%");
    expect(frameOf().getAttribute("scrolling")).toBeNull();
    expect(boxOf().className).toContain("overflow-hidden");
  });

  it("zooms full screen: an SVG drawn larger, a page scaled", () => {
    const { rerender } = render(
      <VisualFrame kind="svg" title="T" content="<svg/>" done height={300} fill zoom={2} />,
    );
    expect(sizerOf().style.width).toBe("200%");
    expect(frameOf().style.width).toBe("100%");
    expect(boxOf().className).toContain("overflow-auto");

    rerender(<VisualFrame kind="html" title="T" content="<p/>" done height={300} fill zoom={2} />);
    expect(frameOf().style.width).toBe("50%");
    expect(frameOf().style.transform).toBe("scale(2)");
  });

  it("passes the drawing's errors, its rendering and its SVG on", () => {
    const onError = vi.fn();
    const onRendered = vi.fn();
    const onSvg = vi.fn();
    render(
      <VisualFrame
        kind="svg"
        title="T"
        content="<svg/>"
        done
        height={300}
        onError={onError}
        onRendered={onRendered}
        onSvg={onSvg}
      />,
    );
    say({ type: "agenticos:visual-svg", markup: "<svg/>" });
    say({ type: "agenticos:visual-svg", markup: 3 });
    expect(onSvg).toHaveBeenCalledTimes(1);
    expect(onSvg).toHaveBeenCalledWith("<svg/>");
    say({ type: "agenticos:visual-error", message: "boom" });
    say({ type: "agenticos:visual-error", message: 3 });
    say({ type: "agenticos:visual-rendered" });
    say({ type: "agenticos:visual-size", height: "tall" });
    say("not an object");
    say(null);
    expect(onError).toHaveBeenCalledWith("boom");
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onRendered).toHaveBeenCalledTimes(1);
  });

  it("listens only to its own frame", () => {
    const onError = vi.fn();
    render(<VisualFrame kind="svg" title="T" content="" done height={300} onError={onError} />);
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", { data: { type: "agenticos:visual-error", message: "x" } }),
      );
    });
    expect(onError).not.toHaveBeenCalled();
  });

  it("takes down a finished drawing that stops beating, but not in a hidden tab", () => {
    vi.useFakeTimers();
    const onStall = vi.fn();
    render(
      <VisualFrame kind="html" title="T" content="<p/>" done height={300} onStall={onStall} />,
    );
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => vi.advanceTimersByTime(20_000));
    expect(onStall).not.toHaveBeenCalled();

    visibility.mockReturnValue("visible");
    say({ type: "agenticos:visual-alive" });
    act(() => vi.advanceTimersByTime(6000));
    expect(onStall).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(4000));
    expect(onStall).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
  });

  it("asks before opening a link the drawing asks for", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} />);
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    say({ type: "agenticos:open-link", href: "https://example.com/" });
    expect(screen.getByText("https://example.com/")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open/i }));
    expect(opened).toHaveBeenCalledWith("https://example.com/", "_blank", "noopener,noreferrer");
    opened.mockRestore();
  });

  it("closes the question without opening anything", () => {
    render(<VisualFrame kind="html" title="T" content="<p/>" done height={300} />);
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    say({ type: "agenticos:open-link", href: "https://example.com/" });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(opened).not.toHaveBeenCalled();
    opened.mockRestore();
  });
});
