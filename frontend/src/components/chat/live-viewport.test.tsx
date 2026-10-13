import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LiveViewport } from "./live-viewport";
import type { Browse } from "@/lib/browse";

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "c1",
    goal: "sign in",
    maxSteps: 25,
    url: "https://example.test/login",
    title: "Login",
    steps: [],
    image: "data:image/jpeg;base64,AAA",
    imageStep: 1,
    outcome: null,
    detail: null,
    ...overrides,
  };
}

/** The picture drawn at half its own size, at (100, 50) on the screen. */
function drawnAtHalfSize() {
  const img = screen.getByRole("img");
  Object.defineProperty(img, "naturalWidth", { value: 1024 });
  img.getBoundingClientRect = () => ({ left: 100, top: 50, width: 512 }) as DOMRect;
}

function setup(holding: boolean, overrides: Partial<Browse> = {}) {
  const onCommand = vi.fn();
  render(<LiveViewport browse={browse(overrides)} holding={holding} onCommand={onCommand} />);
  return { onCommand, surface: screen.getByRole("application") };
}

describe("LiveViewport - the agent's page, and the page itself while it is yours", () => {
  it("says it is waiting before the first picture", () => {
    render(<LiveViewport browse={browse({ image: null })} holding={false} onCommand={vi.fn()} />);
    expect(screen.getByText(/Waiting for the first view/)).toBeInTheDocument();
  });

  it("only shows the page to somebody watching", () => {
    const { onCommand, surface } = setup(false);

    fireEvent.click(screen.getByRole("img"));
    fireEvent.keyDown(surface, { key: "a" });
    fireEvent.wheel(surface, { deltaY: 100 });
    fireEvent.paste(surface, { clipboardData: { getData: () => "secret" } });

    expect(surface).toHaveAccessibleName("The agent's browser");
    expect(surface).toHaveAttribute("tabindex", "-1");
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("lands a click on the same point of the agent's page, whatever size it is drawn at", () => {
    const { onCommand } = setup(true);
    drawnAtHalfSize();

    fireEvent.click(screen.getByRole("img"), { clientX: 110, clientY: 60 });

    expect(onCommand).toHaveBeenCalledWith({ type: "click", x: 20, y: 20 });
  });

  it("types printable keys and presses the named ones", () => {
    const { onCommand, surface } = setup(true);

    fireEvent.keyDown(surface, { key: "a" });
    fireEvent.keyDown(surface, { key: "Enter" });
    fireEvent.keyDown(surface, { key: "Shift" });
    // A shortcut is the viewer's own browser's, not the agent's page's.
    fireEvent.keyDown(surface, { key: "c", metaKey: true });

    expect(onCommand.mock.calls).toEqual([
      [{ type: "type", text: "a" }],
      [{ type: "key", key: "Enter" }],
    ]);
  });

  it("pastes as typing and scrolls the page it holds", () => {
    const { onCommand, surface } = setup(true);

    fireEvent.paste(surface, { clipboardData: { getData: () => "hunter2" } });
    fireEvent.paste(surface, { clipboardData: { getData: () => "" } });
    fireEvent.wheel(surface, { deltaY: 120.4 });

    expect(onCommand.mock.calls).toEqual([
      [{ type: "type", text: "hunter2" }],
      [{ type: "scroll", dy: 120 }],
    ]);
    expect(surface).toHaveAccessibleName(/you have control/);
  });

  it("draws no frame of its own inside a window, and marks the held page from inside", () => {
    const { rerender } = render(
      <LiveViewport browse={browse()} holding={false} onCommand={vi.fn()} flush />,
    );
    expect(screen.getByRole("application")).not.toHaveClass("rounded-xl");
    expect(screen.getByRole("application")).not.toHaveClass("ring-1");

    rerender(<LiveViewport browse={browse()} holding onCommand={vi.fn()} flush />);
    expect(screen.getByRole("application")).toHaveClass("ring-inset");
  });
});
