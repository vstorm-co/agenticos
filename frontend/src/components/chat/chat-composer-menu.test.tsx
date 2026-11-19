import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Paperclip, Mic } from "lucide-react";
import { ChatComposerMenu } from "./chat-composer-menu";
import { MainChatContext } from "./main-chat-context";

it("keeps the file action compact and closes after selection", async () => {
  const attach = vi.fn();
  const voice = vi.fn();
  render(
    <ChatComposerMenu
      actions={[
        { key: "attach", icon: Paperclip, label: "Files", run: attach },
        { key: "voice", icon: Mic, label: "Voice input", run: voice },
      ]}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Add to message" }));
  const menu = screen.getByRole("dialog", { name: "Add to message" });
  expect(within(menu).queryByRole("button", { name: "Voice input" })).toBeNull();
  await userEvent.click(within(menu).getByRole("button", { name: "Files" }));
  expect(attach).toHaveBeenCalledOnce();
  expect(voice).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("opens secondary controls without closing the parent, then restores keyboard focus", async () => {
  render(
    <MainChatContext.Provider value={true}>
      <ChatComposerMenu actions={[]}>
        <button type="button">Call agent</button>
      </ChatComposerMenu>
    </MainChatContext.Provider>,
  );
  const plus = screen.getByRole("button", { name: "Add to message" });
  await userEvent.click(plus);
  const more = screen.getByRole("button", { name: "More" });
  await userEvent.click(more);
  expect(screen.getByRole("dialog", { name: "More" })).toHaveFocus();
  expect(screen.getByRole("button", { name: "Call agent" })).toBeVisible();
  expect(screen.getByRole("dialog", { name: "Add to message" })).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "More" })).toBeNull();
  expect(more).toHaveFocus();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(plus).toHaveFocus();
});

it("opens the secondary panel above its trigger on narrow screens", async () => {
  const query = window.matchMedia("(max-width: 767px)");
  const viewport = vi.spyOn(window, "matchMedia").mockReturnValue({ ...query, matches: true });
  try {
    render(
      <ChatComposerMenu actions={[]}>
        <button type="button">Settings</button>
      </ChatComposerMenu>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add to message" }));
    const more = screen.getByRole("button", { name: "More" });
    vi.spyOn(more, "getBoundingClientRect").mockReturnValue(new DOMRect(20, 400, 200, 40));
    await userEvent.click(more);
    expect(screen.getByRole("dialog", { name: "More" })).toHaveAttribute("data-side", "top");
  } finally {
    viewport.mockRestore();
  }
});
