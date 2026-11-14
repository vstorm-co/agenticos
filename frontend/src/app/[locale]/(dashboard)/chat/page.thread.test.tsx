import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import ChatPage from "./page";

let queryString = "";
const push = vi.fn();
const runExample = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(queryString),
}));
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push }),
}));
vi.mock("@/components/chat", () => ({
  ConversationSidebar: () => <aside>Chats</aside>,
  ChatContainer: ({
    requestedConversationId,
    requestedThreadRootId,
    onOpenThread,
    onCloseThread,
    emptyState,
  }: {
    requestedConversationId: string | null;
    requestedThreadRootId: string | null;
    onOpenThread: (root: string) => void;
    onCloseThread: () => void;
    emptyState?: (onPick: (prompt: string) => void) => ReactNode;
  }) => (
    <main>
      <output aria-label="Requested room">{requestedConversationId ?? "none"}</output>
      <output aria-label="Requested thread">{requestedThreadRootId ?? "none"}</output>
      {emptyState?.(runExample)}
      <button type="button" onClick={() => onOpenThread("root-b")}>
        Open thread B
      </button>
      {requestedThreadRootId !== null && (
        <aside key={requestedThreadRootId} aria-label="Thread" data-tour="chat-room-thread-panel">
          <button type="button" onClick={() => onOpenThread("root-c")}>
            Open pending thread
          </button>
          <button type="button" onClick={onCloseThread}>
            Close selected thread
          </button>
        </aside>
      )}
    </main>
  ),
}));
vi.mock("@/components/chat/phone-chat-bar", () => ({ PhoneChatBar: () => null }));
vi.mock("@/hooks", () => ({ useMcpOAuthOutcome: () => undefined }));
vi.mock("@/hooks/use-chat-with", () => ({ useChatWith: () => undefined }));
vi.mock("@/components/onboarding/start-example", () => ({
  StartExample: ({ goal, onRun }: { goal: string; onRun: (prompt: string) => void }) => (
    <button type="button" onClick={() => onRun(`Example for ${goal}`)}>
      Run {goal} example
    </button>
  ),
}));

function destination() {
  const [url, options] = push.mock.calls.at(-1)!;
  expect(options).toEqual({ scroll: false });
  return new URL(url as string, "https://example.invalid");
}

beforeEach(() => {
  push.mockClear();
  runExample.mockClear();
  queryString = "id=room-a&thread=root-a&keep=present";
  useConversationStore.setState({ currentConversationId: "room-a" });
});

describe("thread URLs on the chat page", () => {
  it("keeps the selected onboarding example and its send callback alongside thread navigation", async () => {
    queryString = "id=room-a&example=meeting&thread=root-a";
    render(<ChatPage />);
    await userEvent.click(screen.getByRole("button", { name: "Run meeting example" }));
    expect(runExample).toHaveBeenCalledWith("Example for meeting");
    await userEvent.click(screen.getByRole("button", { name: "Open thread B" }));
    expect(destination().searchParams.get("example")).toBe("meeting");
    expect(destination().searchParams.get("thread")).toBe("root-b");
  });

  it("restores a direct link and follows browser navigation back to the main room", () => {
    const { rerender } = render(<ChatPage />);
    expect(screen.getByLabelText("Requested room")).toHaveTextContent("room-a");
    expect(screen.getByLabelText("Requested thread")).toHaveTextContent("root-a");

    queryString = "id=room-a&keep=present";
    rerender(<ChatPage />);
    expect(screen.getByLabelText("Requested room")).toHaveTextContent("room-a");
    expect(screen.getByLabelText("Requested thread")).toHaveTextContent("none");
    expect(push).not.toHaveBeenCalled();
  });

  it("uses the currently selected room when opening a root and preserves other parameters", async () => {
    useConversationStore.setState({ currentConversationId: "room-b" });
    render(<ChatPage />);
    await userEvent.click(screen.getByRole("button", { name: "Open thread B" }));

    const target = destination();
    expect(target.pathname).toBe("/chat");
    expect(target.searchParams.get("id")).toBe("room-b");
    expect(target.searchParams.get("thread")).toBe("root-b");
    expect(target.searchParams.get("keep")).toBe("present");
  });

  it("closes only the thread and restores focus to the control that opened it", async () => {
    const { rerender } = render(<ChatPage />);
    const open = screen.getByRole("button", { name: "Open thread B" });
    await userEvent.click(open);
    await userEvent.click(screen.getByRole("button", { name: "Close selected thread" }));

    const target = destination();
    expect(target.searchParams.get("id")).toBe("room-a");
    expect(target.searchParams.has("thread")).toBe(false);
    expect(target.searchParams.get("keep")).toBe("present");
    expect(screen.getByRole("button", { name: "Close selected thread" })).toHaveFocus();
    queryString = target.search.slice(1);
    rerender(<ChatPage />);
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("restores focus after browser Back closes a thread without pushing another entry", async () => {
    queryString = "id=room-a&keep=present";
    const { rerender } = render(<ChatPage />);
    const open = screen.getByRole("button", { name: "Open thread B" });
    await userEvent.click(open);
    queryString = destination().search.slice(1);
    rerender(<ChatPage />);
    screen.getByRole("button", { name: "Close selected thread" }).focus();

    queryString = "id=room-a&keep=present";
    rerender(<ChatPage />);
    await waitFor(() => expect(open).toHaveFocus());
    expect(push).toHaveBeenCalledTimes(1);
  });

  it("closes a directly loaded thread without an opening control", async () => {
    const { rerender } = render(<ChatPage />);
    await userEvent.click(screen.getByRole("button", { name: "Close selected thread" }));
    expect(destination().searchParams.has("thread")).toBe(false);
    expect(destination().searchParams.get("id")).toBe("room-a");
    queryString = destination().search.slice(1);
    rerender(<ChatPage />);
    expect(screen.getByLabelText("Requested thread")).toHaveTextContent("none");
  });

  it("keeps the main-room opener when a pending-action notice switches the panel's root", async () => {
    queryString = "id=room-a&keep=present";
    const { rerender } = render(<ChatPage />);
    const opener = screen.getByRole("button", { name: "Open thread B" });
    await userEvent.click(opener);
    queryString = destination().search.slice(1);
    rerender(<ChatPage />);

    const panel = screen.getByRole("complementary", { name: "Thread" });
    await userEvent.click(within(panel).getByRole("button", { name: "Open pending thread" }));
    expect(destination().searchParams.get("thread")).toBe("root-c");
    queryString = destination().search.slice(1);
    rerender(<ChatPage />);
    expect(panel).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Close selected thread" }));
    queryString = destination().search.slice(1);
    rerender(<ChatPage />);
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("retains the requested room while its selection is still loading", async () => {
    useConversationStore.setState({ currentConversationId: null });
    render(<ChatPage />);
    await userEvent.click(screen.getByRole("button", { name: "Open thread B" }));
    expect(destination().searchParams.get("id")).toBe("room-a");
    expect(destination().searchParams.get("thread")).toBe("root-b");
  });
});
