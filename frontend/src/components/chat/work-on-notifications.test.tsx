import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationStore } from "@/stores";
import type { ShellInfo } from "@/lib/desktop/shell";
import { ConversationNotifications } from "./work-on";

const surface = vi.hoisted((): { value: ShellInfo | null } => ({ value: null }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => surface.value }));
vi.mock("@/components/desktop/notification-settings", () => ({
  ConversationNotificationToggle: ({ conversationId }: { conversationId: string | null }) => (
    <p>Desktop notifications: {conversationId}</p>
  ),
}));
vi.mock("@/components/mobile/notification-preferences", () => ({
  MobileConversationNotifications: ({ conversationId }: { conversationId: string | null }) => (
    <p>Mobile notifications: {conversationId}</p>
  ),
}));

beforeEach(() => {
  surface.value = null;
  useConversationStore.setState({ currentConversationId: "chat-1" });
});

it.each(["macos", "windows", "linux", "ios", "android"] as const)(
  "keeps conversation notifications available on %s",
  (platform) => {
    surface.value = { platform, window: "main", version: "0.2.0", vibrancy: false };
    render(<ConversationNotifications />);
    const mobile = platform === "ios" || platform === "android";
    expect(
      screen.getByText(`${mobile ? "Mobile" : "Desktop"} notifications: chat-1`),
    ).toBeVisible();
  },
);

it("keeps native notification settings out of a browser", () => {
  const { container } = render(<ConversationNotifications />);
  expect(container).toBeEmptyDOMElement();
});
