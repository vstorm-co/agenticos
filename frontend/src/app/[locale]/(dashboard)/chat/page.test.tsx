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
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: vi.fn() }),
}));

it("uses the full-bleed content layout without compensating margins", () => {
  const { container } = render(<ChatPage />);
  const page = container.firstElementChild;
  expect(page).toHaveClass("flex", "min-h-0", "flex-1");
  expect(page).not.toHaveClass("-mt-(--page-inset-top)", "-mx-3", "sm:-mx-6");
});

it("reserves the phone toolbar space for both initial content and sent-turn scrolling", () => {
  const { container } = render(<ChatPage />);
  expect(container.firstElementChild?.lastElementChild).toHaveClass(
    "max-lg:[&_[data-chat-scroller]]:scroll-pt-20",
    "max-lg:[&_[data-transcript]]:pt-20",
  );
});
