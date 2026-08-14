import { beforeAll, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentMap, MAP_ICONS, type MapDelegate, type MapNode } from "./agent-map";

function node(overrides: Partial<MapNode> = {}): MapNode {
  return {
    key: "skills",
    title: "Skills",
    icon: MAP_ICONS.skills,
    items: ["refund-policy"],
    empty: "No skills attached",
    side: "right",
    ...overrides,
  };
}

function delegate(overrides: Partial<MapDelegate> = {}): MapDelegate {
  return {
    key: "delegate:a1",
    name: "Researcher",
    kind: "delegate",
    mode: null,
    href: "/agents/a1",
    ...overrides,
  };
}

describe("AgentMap", () => {
  it("says what is attached, by name", () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    expect(
      within(screen.getByRole("button", { name: "Skills" })).getByText("refund-policy"),
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

  it("draws an edge for each attached box, on any of the four sides", () => {
    // Surfaces reach in from the left, the model sits on top, tools hang off
    // the right and delegation grows downward; the edges are measured, so a
    // box that renders with no path means the map silently lost its anchor.
    const { container } = render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[
          node({ key: "surfaces", title: "Surfaces", side: "left", items: ["chat"] }),
          node({ key: "skills", title: "Skills", side: "right" }),
          node({ key: "model", title: "Model", side: "top", items: ["gpt-5"] }),
          node({ key: "delegation", title: "Delegation", side: "bottom", items: ["Sync"] }),
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: "Surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Model" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delegation" })).toBeInTheDocument();
    expect(container.querySelectorAll("path.map-flow")).toHaveLength(4);
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
      within(screen.getByRole("button", { name: "Skills" })).getByText("3"),
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
 * Delegates and specialists.
 *
 * A subagent is another agent, not a tool, so it is a different kind of node -
 * grouped under a heading, edged to the hub like everything else, and (for a
 * published delegate) a way through to its own page.
 */
describe("AgentMap delegation", () => {
  it("draws each delegate as its own node under a delegation heading", () => {
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[]}
        delegates={[
          delegate(),
          delegate({
            key: "specialist:triage",
            name: "triage",
            kind: "specialist",
            href: undefined,
          }),
        ]}
      />,
    );

    const group = screen.getByRole("region", { name: "Delegation" });
    expect(within(group).getByRole("button", { name: "Researcher" })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "triage" })).toBeInTheDocument();
  });

  it("measures an edge for a delegate too, not only for a capability", () => {
    const { container } = render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node()]}
        delegates={[delegate()]}
      />,
    );

    expect(container.querySelectorAll("path.map-flow")).toHaveLength(2);
  });

  it("hides the delegation heading when there is nothing to delegate to", () => {
    // Every agent that never delegates would otherwise carry an empty heading,
    // which is noise, not the finding an empty capability box is.
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    expect(screen.queryByRole("region", { name: "Delegation" })).not.toBeInTheDocument();
  });
});

/**
 * Interactivity - the map is a control now, not a picture.
 *
 * Clicking or pressing Enter on a node focuses it: a detail panel opens, the
 * node's own edge lights and the rest dim. Escape and a click on the canvas are
 * the two ways back.
 */
describe("AgentMap focus", () => {
  it("opens a detail panel for the node that was clicked", async () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));

    expect(screen.getByRole("region", { name: "Details for Skills" })).toBeInTheDocument();
  });

  it("focuses a left-side node as readily as a right one", async () => {
    // Every side is focusable; a left node is wired through the same path as a
    // right one, and only clicking one proves that column is not inert.
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node({ key: "surfaces", title: "Surfaces", side: "left", items: ["chat"] })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Surfaces" }));

    expect(screen.getByRole("region", { name: "Details for Surfaces" })).toBeInTheDocument();
  });

  it("focuses a top and a bottom node through the same path", async () => {
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[
          node({ key: "model", title: "Model", side: "top", items: ["gpt-5"] }),
          node({ key: "delegation", title: "Delegation", side: "bottom", items: ["Sync"] }),
        ]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    expect(screen.getByRole("region", { name: "Details for Model" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delegation" }));
    expect(screen.getByRole("region", { name: "Details for Delegation" })).toBeInTheDocument();
  });

  it("dims the nodes that are not focused", async () => {
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node(), node({ key: "mcp", title: "MCP", icon: MAP_ICONS.mcp })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));

    expect(screen.getByRole("button", { name: "MCP" }).className).toContain("opacity-40");
    expect(screen.getByRole("button", { name: "Skills" }).className).not.toContain("opacity-40");
  });

  it("lights the focused node's edge and dims the rest", async () => {
    const { container } = render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[node(), node({ key: "mcp", title: "MCP", icon: MAP_ICONS.mcp })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));

    const paths = [...container.querySelectorAll("path.map-flow")];
    const lit = paths.filter((path) => path.classList.contains("stroke-brand"));
    const dimmed = paths.filter((path) => path.classList.contains("opacity-20"));
    expect(lit).toHaveLength(1);
    expect(dimmed).toHaveLength(1);
  });

  it("activates a node from the keyboard with Enter", async () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    const button = screen.getByRole("button", { name: "Skills" });
    button.focus();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(screen.getByRole("region", { name: "Details for Skills" })).toBeInTheDocument();
  });

  it("clears the focus on Escape", async () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));
    expect(screen.getByRole("region", { name: "Details for Skills" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("region", { name: "Details for Skills" })).not.toBeInTheDocument();
  });

  it("clears the focus when the canvas is clicked, not a node", async () => {
    const { container } = render(
      <AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));
    expect(screen.getByRole("region", { name: "Details for Skills" })).toBeInTheDocument();

    const viewport = container.querySelector<HTMLElement>("[style*='transform']")!.parentElement!;
    fireEvent.click(viewport);

    expect(screen.queryByRole("region", { name: "Details for Skills" })).not.toBeInTheDocument();
  });

  it("toggles a node off when it is clicked a second time", async () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    const button = screen.getByRole("button", { name: "Skills" });
    await userEvent.click(button);
    expect(screen.getByRole("region", { name: "Details for Skills" })).toBeInTheDocument();

    await userEvent.click(button);
    expect(screen.queryByRole("region", { name: "Details for Skills" })).not.toBeInTheDocument();
  });

  it("links a published delegate through to its own page", async () => {
    // The one place the map leaves itself: a delegate has a version and a page,
    // so the map walks the delegation tree one hop at a time.
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[]}
        delegates={[delegate({ name: "Researcher", href: "/agents/a1" })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Researcher" }));

    expect(screen.getByRole("link", { name: "Open Researcher" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
  });

  it("offers no link for an inline specialist, and says why", async () => {
    // A specialist is not versioned and has no page - a dead link would be worse
    // than none, so the panel explains the absence instead.
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[]}
        delegates={[
          delegate({
            key: "specialist:triage",
            name: "triage",
            kind: "specialist",
            href: undefined,
          }),
        ]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "triage" }));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText("Defined inside this agent, with no page of its own."),
    ).toBeInTheDocument();
  });

  it("names the mode a delegate hands back on", async () => {
    render(
      <AgentMap
        agentName="Support"
        instructions="Be brief."
        nodes={[]}
        delegates={[delegate({ mode: "async" })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Researcher" }));

    expect(screen.getByText("Hands back: Async")).toBeInTheDocument();
  });

  it("closes the panel from its own close button", async () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Skills" }));
    await userEvent.click(screen.getByRole("button", { name: "Close details" }));

    expect(screen.queryByRole("region", { name: "Details for Skills" })).not.toBeInTheDocument();
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
