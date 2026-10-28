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

it("uses the full-bleed content layout without compensating margins", () => {
  const { container } = render(<ChatPage />);
  const page = container.firstElementChild;
  expect(page).toHaveClass("flex", "min-h-0", "flex-1");
  expect(page).not.toHaveClass("-mt-(--page-inset-top)", "-mx-3", "sm:-mx-6");
});
