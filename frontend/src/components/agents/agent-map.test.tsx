import { beforeAll, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentMap, MAP_ICONS, type MapNode } from "./agent-map";

function node(overrides: Partial<MapNode> = {}): MapNode {
  return {
    key: "skills",
    title: "Skills",
    icon: MAP_ICONS.skills,
    items: ["refund-policy"],
    empty: "No skills attached",
    side: "out",
    ...overrides,
  };
}

describe("AgentMap", () => {
  it("says what is attached, by name", () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    expect(
      within(screen.getByRole("group", { name: "Skills" })).getByText("refund-policy"),
    ).toBeInTheDocument();
  });

  it("names an empty box rather than hiding it", () => {
    // The whole reason to open the map before publishing: the thing nobody
    // attached is invisible in a column of collapsed forms.
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node({ items: [] })]} />);

    expect(screen.getByText("No skills attached")).toBeInTheDocument();
  });

  it("says an agent has no instructions instead of drawing an empty panel", () => {
    // A blank centre reads as a rendering failure, and "no instructions" is a
    // finding - that agent answers as whatever the model felt like.
    render(<AgentMap agentName="Support" instructions="   " nodes={[]} />);

    expect(screen.getByText("No instructions written")).toBeInTheDocument();
  });

  it("draws an edge for each attached box, on the side it was given", () => {
    // Inputs feed the agent from the left and outputs hang off the right; the
    // edges are measured, so a box that renders with no path means the map
    // silently lost its anchor.
    const { container } = render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[
          node({ key: "channels", title: "Channels", side: "in", items: ["slack"] }),
          node({ key: "skills", title: "Skills", side: "out" }),
        ]}
      />,
    );

    expect(screen.getByRole("group", { name: "Channels" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Skills" })).toBeInTheDocument();
    expect(container.querySelectorAll("path.map-flow")).toHaveLength(2);
  });

  it("counts the items in a box that has any", () => {
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node({ items: ["a", "b", "c"] })]}
      />,
    );

    expect(
      within(screen.getByRole("group", { name: "Skills" })).getByText("3"),
    ).toBeInTheDocument();
  });

  it("forgets a box that is detached, so a stale anchor cannot outlive it", () => {
    // The ref map is keyed by node key and never cleared wholesale; without the
    // detach branch a removed box keeps measuring against a node that is gone.
    const { container, rerender } = render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node(), node({ key: "mcp", title: "MCP", icon: MAP_ICONS.mcp })]}
      />,
    );
    expect(container.querySelectorAll("path.map-flow")).toHaveLength(2);

    rerender(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    expect(container.querySelectorAll("path.map-flow")).toHaveLength(1);
  });
});

/**
 * Pan and zoom.
 *
 * One transform on the content rather than a re-layout: the edges are measured
 * in the content's own coordinates, so the same transform carries them along and
 * nothing has to be re-measured while somebody drags.
 *
 * The transform is read off the style attribute, which is the only place it
 * exists - there is no state a test can inspect and no class that changes.
 */
describe("AgentMap pan and zoom", () => {
  beforeAll(() => {
    // jsdom has neither, and the map observes its own size to place the edges.
    globalThis.ResizeObserver ??= class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });

  function draw() {
    const { container } = render(
      <AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />,
    );
    // The transformed content is the element carrying the inline transform.
    const content = container.querySelector<HTMLElement>("[style*='transform']")!;
    const viewport = content.parentElement!;
    return { content, viewport };
  }

  /**
   * jsdom implements neither PointerEvent nor `clientX` on a synthesised pointer
   * event, so a `fireEvent.pointerMove` arrives with no coordinates and the pan
   * arithmetic reads NaN. A MouseEvent carries the coordinates; React reads the
   * pointer id off the native event either way.
   */
  function pointer(
    target: HTMLElement,
    type: "pointerdown" | "pointermove" | "pointerup" | "pointercancel",
    init: { pointerId: number; clientX?: number; clientY?: number },
  ) {
    const event = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      clientX: init.clientX ?? 0,
      clientY: init.clientY ?? 0,
    });
    Object.defineProperty(event, "pointerId", { value: init.pointerId });
    fireEvent(target, event);
  }

  it("starts unzoomed and unpanned", () => {
    const { content } = draw();

    expect(content.style.transform).toBe("translate(0px, 0px) scale(1)");
  });

  it("zooms in from the centre", async () => {
    const { content } = draw();

    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(content.style.transform).toContain("scale(1.25)");
  });

  it("zooms out from the centre", async () => {
    const { content } = draw();

    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));

    expect(content.style.transform).toContain("scale(0.8)");
  });

  it("resets the view, so a lost map can be found again", async () => {
    const { content } = draw();

    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset view" }));

    expect(content.style.transform).toBe("translate(0px, 0px) scale(1)");
  });

  it("will not zoom past its limits, however many times it is asked", async () => {
    // Without a clamp, a held button walks the scale to zero or to infinity and
    // the map disappears with no way back except the reset.
    const { content } = draw();
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });

    for (let index = 0; index < 20; index += 1) await userEvent.click(zoomOut);

    const scale = Number(/scale\(([\d.]+)\)/.exec(content.style.transform)![1]);
    expect(scale).toBeGreaterThan(0);
  });

  it("pans with a pointer drag", () => {
    const { content, viewport } = draw();
    // jsdom does not implement pointer capture.
    viewport.setPointerCapture = vi.fn();

    pointer(viewport, "pointerdown", { pointerId: 1, clientX: 100, clientY: 100 });
    pointer(viewport, "pointermove", { pointerId: 1, clientX: 150, clientY: 130 });

    expect(content.style.transform).toContain("translate(50px, 30px)");
  });

  it("ignores a move from a pointer that is not the one dragging", () => {
    // A second finger on a touchpad must not teleport the map.
    const { content, viewport } = draw();
    viewport.setPointerCapture = vi.fn();

    pointer(viewport, "pointerdown", { pointerId: 1, clientX: 100, clientY: 100 });
    pointer(viewport, "pointermove", { pointerId: 2, clientX: 400, clientY: 400 });

    expect(content.style.transform).toContain("translate(0px, 0px)");
  });

  it("ignores a move when nothing is being dragged", () => {
    const { content, viewport } = draw();

    pointer(viewport, "pointermove", { pointerId: 1, clientX: 400, clientY: 400 });

    expect(content.style.transform).toContain("translate(0px, 0px)");
  });

  it("stops panning when the pointer is released", () => {
    const { content, viewport } = draw();
    viewport.setPointerCapture = vi.fn();

    pointer(viewport, "pointerdown", { pointerId: 1, clientX: 100, clientY: 100 });
    pointer(viewport, "pointerup", { pointerId: 1 });
    pointer(viewport, "pointermove", { pointerId: 1, clientX: 400, clientY: 400 });

    expect(content.style.transform).toContain("translate(0px, 0px)");
  });

  it("stops panning when the gesture is cancelled", () => {
    const { content, viewport } = draw();
    viewport.setPointerCapture = vi.fn();

    pointer(viewport, "pointerdown", { pointerId: 1, clientX: 100, clientY: 100 });
    pointer(viewport, "pointercancel", { pointerId: 1 });
    pointer(viewport, "pointermove", { pointerId: 1, clientX: 400, clientY: 400 });

    expect(content.style.transform).toContain("translate(0px, 0px)");
  });

  it("zooms on the wheel, and swallows the event", () => {
    // The listener is attached by hand because React registers `onWheel` as
    // passive, and a passive listener cannot stop the dialog behind the map from
    // scrolling while somebody zooms.
    const { content, viewport } = draw();

    const event = new WheelEvent("wheel", {
      deltaY: -100,
      clientX: 10,
      clientY: 10,
      cancelable: true,
      bubbles: true,
    });
    act(() => {
      viewport.dispatchEvent(event);
    });

    expect(event.defaultPrevented).toBe(true);
    expect(content.style.transform).toContain("scale(1.15)");
  });

  it("zooms out on a downward wheel", () => {
    const { content, viewport } = draw();

    act(() => {
      viewport.dispatchEvent(
        new WheelEvent("wheel", { deltaY: 100, clientX: 10, clientY: 10, cancelable: true }),
      );
    });

    expect(content.style.transform).not.toContain("scale(1)");
  });
});
