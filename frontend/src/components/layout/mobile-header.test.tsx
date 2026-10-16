import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { useChatSidebarStore } from "@/stores";
import { MobileHeader } from "./mobile-header";

const pathname = vi.hoisted(() => ({ current: "/chat" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));
vi.mock("@/components/layout/brand-link", () => ({ BrandLink: () => null }));
vi.mock("@/components/layout/notification-bell", () => ({ NotificationBell: () => null }));

function mount() {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MobileHeader />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useChatSidebarStore.getState().close();
});

/**
 * On a phone the chat's conversation list is a slide-over, and this header is
 * the only way into it - so the button is there on the chat and nowhere else.
 */
describe("MobileHeader", () => {
  it("opens the conversation list from the chat", () => {
    pathname.current = "/pl/chat";
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Open conversations" }));

    expect(useChatSidebarStore.getState().isOpen).toBe(true);
  });

  it("offers no conversation list away from the chat", () => {
    pathname.current = "/agents";
    mount();

    expect(screen.queryByRole("button", { name: "Open conversations" })).toBeNull();
    expect(screen.getByRole("button", { name: "Toggle menu" })).toBeInTheDocument();
  });
});
