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

it("shows every secondary action in the first panel and restores focus on Escape", async () => {
  const call = vi.fn();
  render(
    <MainChatContext.Provider value={true}>
      <ChatComposerMenu actions={[]}>
        <button type="button" onClick={call}>
          Call agent
        </button>
      </ChatComposerMenu>
    </MainChatContext.Provider>,
  );
  const plus = screen.getByRole("button", { name: "Add to message" });
  await userEvent.click(plus);
  expect(screen.getByRole("dialog", { name: "Add to message" })).toHaveFocus();
  expect(screen.queryByRole("button", { name: "More" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Call agent" }));
  expect(call).toHaveBeenCalledOnce();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(plus).toHaveFocus();
});
