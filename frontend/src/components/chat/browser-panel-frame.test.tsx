import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserPanelFrame } from "./browser-panel-frame";

function panel() {
  return render(
    <BrowserPanelFrame>
      {({ fullscreen, toggleFullscreen }) => (
        <button onClick={toggleFullscreen}>{fullscreen ? "dock" : "expand"}</button>
      )}
    </BrowserPanelFrame>,
  );
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("resizes by keyboard within bounds and keeps its width across expansion", () => {
  const view = panel();
  const resize = screen.getByRole("separator");
  expect(resize).toHaveAttribute("aria-valuenow", "55");
  fireEvent.keyDown(resize, { key: "ArrowLeft" });
  expect(resize).toHaveAttribute("aria-valuenow", "57");
  fireEvent.keyDown(resize, { key: "ArrowRight" });
  expect(resize).toHaveAttribute("aria-valuenow", "55");
  fireEvent.keyDown(resize, { key: "Home" });
  fireEvent.keyDown(resize, { key: "ArrowRight" });
  expect(resize).toHaveAttribute("aria-valuenow", "35");
  fireEvent.keyDown(resize, { key: "End" });
  fireEvent.keyDown(resize, { key: "ArrowLeft" });
  expect(resize).toHaveAttribute("aria-valuenow", "65");
  fireEvent.keyDown(resize, { key: "Enter" });
  expect(resize).toHaveAttribute("aria-valuenow", "65");
  fireEvent.click(screen.getByText("expand"));
  expect(screen.queryByRole("separator")).toBeNull();
  expect(view.container.querySelector("aside")).toHaveAttribute("data-browser-panel", "fullscreen");
  fireEvent.click(screen.getByText("dock"));
  expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "65");
  fireEvent(screen.getByRole("separator"), new MouseEvent("dblclick", { bubbles: true }));
  expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "55");
});
it("bounds pointer resizing and removes the native blocker when the drag ends", () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  const capture = vi.fn();
  const view = panel();
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(
    new DOMRect(0, 0, 1000, 700),
  );
  const resize = screen.getByRole("separator");
  Object.defineProperty(resize, "setPointerCapture", { value: capture });
  fireEvent.pointerMove(resize, { clientX: 0 });
  fireEvent.pointerDown(resize, { button: 2 });
  expect(capture).not.toHaveBeenCalled();
  fireEvent.pointerDown(resize, { button: 0 });
  expect(view.container.querySelector("[data-native-browser-blocked]")).toBeInTheDocument();
  fireEvent.pointerMove(resize, { clientX: 500 });
  expect(resize).toHaveAttribute("aria-valuenow", "50");
  fireEvent.pointerMove(resize, { clientX: -500 });
  expect(resize).toHaveAttribute("aria-valuenow", "65");
  vi.mocked(Element.prototype.getBoundingClientRect).mockReturnValue(new DOMRect());
  fireEvent.pointerMove(resize, { clientX: 500 });
  expect(resize).toHaveAttribute("aria-valuenow", "65");
  for (const end of ["pointerUp", "pointerCancel", "lostPointerCapture"] as const) {
    fireEvent.pointerDown(resize, { button: 0 });
    act(() => fireEvent[end](resize));
    expect(view.container.querySelector("[data-native-browser-blocked]")).toBeNull();
  }
  vi.unstubAllGlobals();
});
