import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ChatPage from "./page";

const state = vi.hoisted(() => ({
  params: new URLSearchParams(),
  items: [] as import("@/lib/suggestions-api").Suggestion[],
  loading: false,
  error: null as Error | null,
  enabled: vi.fn(),
}));
const organizations = vi.hoisted(() => ({
  isSuccess: true,
  data: [] as import("@/types").Organization[],
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => state.params }));
vi.mock("@/hooks/use-organizations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-organizations")>()),
  useOrganizationList: () => organizations,
}));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: (enabled: boolean) => {
    state.enabled(enabled);
    return { suggestions: state.items, isLoading: state.loading, error: state.error };
  },
}));
vi.mock("@/components/chat", () => ({
  ConversationSidebar: () => <aside>Chats</aside>,
  ChatContainer: ({ composerDraft }: { composerDraft?: { text: string; consume: () => void } }) => (
    <div>
      <output>{composerDraft?.text ?? "No draft"}</output>
      {composerDraft && <button onClick={composerDraft.consume}>Consume draft</button>}
    </div>
  ),
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

it("hands a ?prompt= address to the composer as a draft, once, after the new chat starts", () => {
  window.history.replaceState({}, "", "/chat?new=1&prompt=Draft%20a%20workflow");
  state.params = new URLSearchParams("new=1&prompt=Draft a workflow");
  const view = render(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent("No draft");

  state.params = new URLSearchParams("prompt=Draft a workflow");
  view.rerender(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent("Draft a workflow");
  expect(window.location.search).toContain("prompt=");
  fireEvent.click(screen.getByRole("button", { name: "Consume draft" }));
  expect(window.location.search).not.toContain("prompt=");

  state.params = new URLSearchParams();
  view.rerender(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent("No draft");
});

it("reserves the phone toolbar space for both initial content and sent-turn scrolling", () => {
  const { container } = render(<ChatPage />);
  expect(container.firstElementChild?.lastElementChild).toHaveClass(
    "max-lg:[&_[data-chat-scroller]]:scroll-pt-20",
    "max-lg:[&_[data-transcript]]:pt-20",
  );
});

beforeEach(() => {
  state.params = new URLSearchParams();
  state.items = [];
  state.loading = false;
  state.error = null;
  state.enabled.mockClear();
});

it("waits for the actual Inbox item and offers an editable draft only after data arrives", () => {
  const id = "247b3b83-4dbb-4db5-9d1f-978348dd3e99";
  state.params = new URLSearchParams({ discuss: id });
  window.history.replaceState({}, "", `/chat?discuss=${id}`);
  state.loading = true;
  const view = render(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent("No draft");
  expect(state.enabled).toHaveBeenLastCalledWith(true);
  expect(window.location.search).toContain("discuss=");
  state.loading = false;
  view.rerender(<ChatPage />);
  expect(screen.queryByRole("button", { name: "Consume draft" })).toBeNull();
  state.items = [
    {
      id,
      kind: "agent",
      status: "open",
      title: "Support assistant",
      detail: null,
      payload: { chat_prompt: "Create an agent to answer help center questions." },
      created_at: "2026-11-21T10:00:00Z",
    },
  ];
  view.rerender(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Create an agent to answer help center questions.",
  );
  expect(window.location.search).toContain("discuss=");
  fireEvent.click(screen.getByRole("button", { name: "Consume draft" }));
  expect(window.location.search).toBe("");
});

it("does not request suggestions or emit a draft for an invalid id", () => {
  state.params = new URLSearchParams({ discuss: "invalid" });
  render(<ChatPage />);
  expect(state.enabled).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("status")).toHaveTextContent("No draft");
});

it("does not compose cached item data when the personal Inbox read fails", () => {
  const id = "247b3b83-4dbb-4db5-9d1f-978348dd3e99";
  state.params = new URLSearchParams({ discuss: id });
  state.items = [
    {
      id,
      kind: "finding",
      status: "open",
      title: "Stale finding",
      detail: null,
      payload: { chat_prompt: "Act on a stale finding" },
      created_at: "2026-11-21T10:00:00Z",
    },
  ];
  state.error = new Error("Inbox read refused");
  render(<ChatPage />);
  expect(screen.getByRole("status")).toHaveTextContent("No draft");
  expect(screen.queryByRole("button", { name: "Consume draft" })).toBeNull();
});
