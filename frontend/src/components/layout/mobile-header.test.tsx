import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { AssistantState } from "@/types/assistant";

import messages from "../../../messages/en.json";
import { MobileHeader } from "./mobile-header";

const pathname = vi.hoisted(() => ({ current: "/chat" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));
vi.mock("@/components/layout/brand-link", () => ({ BrandLink: () => null }));
vi.mock("@/components/layout/notification-bell", () => ({ NotificationBell: () => null }));

const architect = vi.hoisted(() => ({
  assistant: null as Pick<AssistantState, "can_use" | "agent_id" | "status"> | null,
}));
vi.mock("@/hooks/use-assistant", () => ({ useAssistant: () => architect }));

function mount() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MobileHeader />
    </NextIntlClientProvider>,
  );
}

/**
 * The phone's top bar, everywhere but the chat: there the buttons float over
 * the transcript instead (`PhoneChatBar`), the conversation list among them.
 */
describe("MobileHeader", () => {
  it("steps aside on the chat, which floats its own buttons over the transcript", () => {
    pathname.current = "/pl/chat";
    const { container } = mount();

    expect(container).toBeEmptyDOMElement();
  });

  it("offers no conversation list away from the chat", () => {
    pathname.current = "/agents";
    mount();

    expect(screen.queryByRole("button", { name: "Open conversations" })).toBeNull();
    expect(screen.getByRole("button", { name: "Toggle menu" })).toBeInTheDocument();
  });
});

it.each([
  [true, "a", "ready", true],
  [true, "a", "needs_model", true],
  [true, "a", "disabled", false],
  [false, "a", "ready", false],
  [true, null, "ready", false],
] as const)(
  "reserves header room only for an available Architect (%s, %s, %s)",
  (can_use, agent_id, status, visible) => {
    pathname.current = "/admin/users";
    architect.assistant = { can_use, agent_id, status };
    const { container } = mount();
    expect(container.querySelector("[data-architect-slot]") !== null).toBe(visible);
    architect.assistant = null;
  },
);
