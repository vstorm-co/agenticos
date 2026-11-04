import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { useChatSidebarStore, useSidebarStore } from "@/stores";
import { PhoneChatBar } from "./phone-chat-bar";

const env = vi.hoisted(() => ({ unread: 0, startNewChat: vi.fn() }));
vi.mock("@/hooks", () => ({ useConversations: () => ({ startNewChat: env.startNewChat }) }));
vi.mock("@/hooks/use-notifications", () => ({
  useUnreadNotificationCount: () => ({ count: env.unread }),
}));

function mount() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <PhoneChatBar />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  env.unread = 0;
  env.startNewChat.mockClear();
  useChatSidebarStore.getState().close();
  useSidebarStore.setState({ isOpen: false });
});

describe("PhoneChatBar", () => {
  it("opens the menu, the conversations, and a new chat", () => {
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Toggle menu" }));
    expect(useSidebarStore.getState().isOpen).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Open conversations" }));
    expect(useChatSidebarStore.getState().isOpen).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(env.startNewChat).toHaveBeenCalledOnce();
  });

  it("marks the menu while something in the inbox is unread", () => {
    const { container, unmount } = mount();
    expect(container.querySelector(".bg-destructive")).toBeNull();
    unmount();

    env.unread = 2;
    expect(mount().container.querySelector(".bg-destructive")).not.toBeNull();
  });
});
