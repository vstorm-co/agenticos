import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { createRef } from "react";
import { NativeBrowser } from "./native-browser";
import type { NativeBrowserState } from "@/lib/desktop/browser";

const native = vi.hoisted(() => ({
  state: null as NativeBrowserState | null,
  error: null as string | null,
  send: vi.fn(),
}));
vi.mock("@/hooks/use-native-browser", () => ({
  useNativeBrowser: () => ({ ...native, viewport: createRef<HTMLDivElement>() }),
}));
beforeEach(() => {
  native.state = null;
  native.error = null;
  native.send.mockReset().mockResolvedValue(true);
});
it("navigates and hands control between the native page and the agent", async () => {
  const close = vi.fn();
  const view = render(<NativeBrowser id="tab" onClose={close} />);
  fireEvent.click(screen.getByRole("button", { name: "Take over" }));
  expect(native.send).toHaveBeenLastCalledWith("take_over");
  const address = screen.getByRole("textbox", { name: "Website address" });
  fireEvent.change(address, { target: { value: "example.test/new" } });
  fireEvent.submit(address.closest("form")!);
  expect(native.send).toHaveBeenLastCalledWith("navigate", "https://example.test/new");
  for (const [name, command] of [
    ["Back", "back"],
    ["Forward", "forward"],
    ["Reload", "reload"],
  ]) {
    fireEvent.click(screen.getByRole("button", { name }));
    expect(native.send).toHaveBeenLastCalledWith(command);
  }
  native.state = { url: "https://example.test/new", title: "New", held: true };
  native.error = "Tab closed";
  view.rerender(<NativeBrowser id="tab" onClose={close} />);
  fireEvent.click(screen.getByRole("button", { name: "Return to agent" }));
  expect(native.send).toHaveBeenLastCalledWith("give_back");
  expect(screen.getByRole("alert")).toHaveTextContent("Tab closed");
  fireEvent.click(screen.getByRole("button", { name: "Close the browser panel" }));
  expect(close).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Close tab" }));
  expect(native.send).toHaveBeenLastCalledWith("close");
  await waitFor(() => expect(close).toHaveBeenCalledTimes(2));
});

it("keeps the panel open when closing the tab fails", async () => {
  native.send.mockResolvedValue(false);
  const close = vi.fn();
  render(<NativeBrowser id="tab" onClose={close} />);
  fireEvent.click(screen.getByRole("button", { name: "Close tab" }));
  await waitFor(() => expect(native.send).toHaveBeenCalledWith("close"));
  expect(close).not.toHaveBeenCalled();
});

it("expands the native renderer without reopening its tab", async () => {
  const toggle = vi.fn();
  const view = render(<NativeBrowser id="tab" onClose={vi.fn()} onToggleFullscreen={toggle} />);
  fireEvent.click(screen.getByRole("button", { name: "Maximize" }));
  expect(toggle).toHaveBeenCalledTimes(1);
  view.rerender(
    <NativeBrowser id="tab" onClose={vi.fn()} fullscreen onToggleFullscreen={toggle} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Back beside the chat" }));
  expect(toggle).toHaveBeenCalledTimes(2);
  expect(native.send).not.toHaveBeenCalled();
});
