import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ChatSidePanel, ChatPanelHeader } from "./chat-side-panel";

afterEach(() => vi.restoreAllMocks());
function panel(onClose = vi.fn(), contained = false) {
  return render(
    <ChatSidePanel label="Files" panelId="test-panel" contained={contained} onClose={onClose}>
      {({ fullscreen, toggleFullscreen }) => (
        <>
          <ChatPanelHeader
            title="Files"
            icon={<span aria-hidden />}
            closeLabel="Close files"
            onClose={onClose}
            fullscreen={fullscreen}
            toggleFullscreen={toggleFullscreen}
            actions={<button>Download</button>}
            subtitle="Personal workspace"
          />
          <button>Open file</button>
        </>
      )}
    </ChatSidePanel>,
  );
}
it("shares keyboard resizing, expansion and one close action", async () => {
  const close = vi.fn();
  const view = panel(close);
  expect(screen.getByRole("complementary", { name: "Files" })).toHaveAttribute("id", "test-panel");
  fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowLeft" });
  expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "57");
  await userEvent.click(screen.getByRole("button", { name: "Maximize" }));
  expect(screen.queryByRole("separator")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Back beside the chat" }));
  expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "57");
  expect(screen.getByText("Personal workspace")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Close files" }));
  expect(close).toHaveBeenCalledOnce();
  view.unmount();
});
it("does not close a parent panel for Escape handled by its nested preview", () => {
  const close = vi.fn();
  const view = panel(close);
  const nested = document.createElement("div");
  nested.setAttribute("role", "dialog");
  const input = document.createElement("input");
  nested.append(input);
  document.body.append(nested);
  fireEvent.keyDown(input, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  const prevented = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
  });
  prevented.preventDefault();
  fireEvent(window, prevented);
  expect(close).not.toHaveBeenCalled();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).toHaveBeenCalledOnce();
  nested.remove();
  view.unmount();
});
it("restores the initiating control without moving the page when focus was in the panel", () => {
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  const focus = vi.spyOn(trigger, "focus");
  const view = panel();
  screen.getByRole("button", { name: "Open file" }).focus();
  view.unmount();
  expect(focus).toHaveBeenCalledWith({ preventScroll: true });
  trigger.remove();
});
it("does not take focus back after the reader moved elsewhere", () => {
  const trigger = document.createElement("button"),
    elsewhere = document.createElement("button");
  document.body.append(trigger, elsewhere);
  trigger.focus();
  const focus = vi.spyOn(trigger, "focus");
  const view = panel();
  elsewhere.focus();
  view.unmount();
  expect(focus).not.toHaveBeenCalled();
  trigger.remove();
  elsewhere.remove();
});
it("keeps an embedded panel within its conversation and permits a bare header", () => {
  const view = render(
    <ChatSidePanel label="Sources" contained onClose={vi.fn()}>
      {({ fullscreen, toggleFullscreen }) => (
        <ChatPanelHeader
          title="Sources"
          icon={null}
          closeLabel="Close sources"
          onClose={vi.fn()}
          fullscreen={fullscreen}
          toggleFullscreen={toggleFullscreen}
        />
      )}
    </ChatSidePanel>,
  );
  expect(view.container.querySelector("aside")).toHaveClass("absolute");
  expect(screen.queryByRole("separator")).toBeNull();
});
