import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ChatPage from "./page";

vi.mock("@/components/chat", () => ({
  ConversationSidebar: () => <aside>Chats</aside>,
  ChatContainer: () => <div>Conversation</div>,
}));
vi.mock("@/components/chat/phone-chat-bar", () => ({ PhoneChatBar: () => null }));
vi.mock("@/hooks", () => ({ useMcpOAuthOutcome: () => undefined }));
vi.mock("@/hooks/use-chat-with", () => ({ useChatWith: () => undefined }));

it("cancels the current page inset rather than pulling the desktop header above its scrollport", () => {
  const { container } = render(<ChatPage />);
  const page = container.firstElementChild;
  expect(page).toHaveClass("-mt-(--page-inset-top)");
  expect(page).not.toHaveClass("-mt-4", "sm:-mt-8");
});
