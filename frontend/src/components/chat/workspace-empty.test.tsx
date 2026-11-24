import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceEmpty } from "./workspace-empty";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";

beforeEach(() => useBrowserPanelStore.getState().openSurface("browser"));

it("does not invent a start action when a chat has no sender", () => {
  render(<WorkspaceEmpty surface="browser" reason="unknown" />);
  expect(screen.queryByRole("button", { name: "Ask agent to open browser" })).toBeNull();
  fireEvent.submit(screen.getByRole("textbox", { name: "Website address" }).closest("form")!);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent(/configuration is not available/);
});

it("supports the narrow-screen close control and leaves Escape to dialogs or consumed events", async () => {
  const start = vi.fn();
  const view = render(<WorkspaceEmpty surface="computer" reason={null} onStart={start} />);
  const panel = screen.getByRole("complementary", { name: "Computer" });
  expect(panel).toHaveClass("fixed");
  expect(panel.className).toContain("@min-[900px]/browser-layout:relative");
  expect(screen.getByRole("separator", { name: "Resize workspace panel" })).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Enter" });
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  document.body.append(dialog);
  fireEvent.keyDown(dialog, { key: "Escape" });
  dialog.remove();
  const consumed = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
  consumed.preventDefault();
  window.dispatchEvent(consumed);
  expect(useBrowserPanelStore.getState().surface).toBe("browser");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(useBrowserPanelStore.getState().surface).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Close workspace panel" }));
  expect(start).not.toHaveBeenCalled();
  view.unmount();
});
