import userEvent from "@testing-library/user-event";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationForkRead } from "@/lib/conversation-forks-api";
import { ConversationSideThreads } from "./conversation-side-threads";

const state = vi.hoisted(() => ({
  page: { items: [] as ConversationForkRead[], total: 0 },
  hasData: true,
  isError: false,
  isPending: false,
  hasNextPage: false,
  isFetchingNextPage: false,
  refetch: vi.fn(),
  fetchNextPage: vi.fn(),
}));

vi.mock("@/hooks/use-conversation-forks", () => ({
  useConversationForks: () => ({
    data: state.hasData ? { pages: [state.page], pageParams: [0] } : undefined,
    isError: state.isError,
    isPending: state.isPending,
    isSuccess: !state.isPending && !state.isError,
    hasNextPage: state.hasNextPage,
    isFetchingNextPage: state.isFetchingNextPage,
    refetch: state.refetch,
    fetchNextPage: state.fetchNextPage,
  }),
}));
vi.mock("@/lib/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/utils")>()),
  timeAgo: () => "just now",
}));
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => Object.assign((key: string) => key, { has: () => true }),
}));

const fork: ConversationForkRead = {
  id: "fork-a",
  title: "Explore a different option",
  created_at: "2026-11-17T12:00:00Z",
  updated_at: null,
  is_archived: true,
  forked_from: { conversation_id: "source-a", message_id: "answer-a", title: "Main" },
};

beforeEach(() => {
  state.page = {
    items: [
      fork,
      {
        ...fork,
        id: "fork-active",
        title: null,
        updated_at: "2026-11-17T12:30:00Z",
        is_archived: false,
      },
      {
        ...fork,
        id: "fork-other-anchor",
        forked_from: { ...fork.forked_from, message_id: "answer-b" },
      },
      {
        ...fork,
        id: "fork-other-source",
        forked_from: { ...fork.forked_from, conversation_id: "source-b" },
      },
    ],
    total: 3,
  };
  state.hasData = true;
  state.isError = false;
  state.isPending = false;
  state.hasNextPage = false;
  state.isFetchingNextPage = false;
  state.refetch.mockReset();
  state.fetchNextPage.mockReset();
});

describe("ConversationSideThreads", () => {
  it("shows only the selected answer's child conversations and opens the chosen one", () => {
    const onCreate = vi.fn(async (_messageId: string) => {});
    const onOpen = vi.fn();
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={onCreate}
        onOpen={onOpen}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /title/ }));

    expect(screen.getByRole("button", { name: /Explore a different option/ })).toHaveTextContent(
      "archived",
    );
    expect(screen.getByRole("button", { name: /untitledFork/ })).not.toHaveTextContent("archived");
    expect(screen.queryByText("fork-other-anchor")).not.toBeInTheDocument();
    expect(screen.queryByText("fork-other-source")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Explore a different option/ }));

    expect(onOpen).toHaveBeenCalledExactlyOnceWith(fork);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("sends the exact anchor to the owner’s create callback", async () => {
    const onCreate = vi.fn(async (_messageId: string) => {});
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={onCreate}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /title/ }));
    await userEvent.click(screen.getByRole("button", { name: "start" }));

    expect(onCreate).toHaveBeenCalledExactlyOnceWith("answer-a");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("loads another page for this answer and prevents duplicate fetches while loading", async () => {
    state.hasNextPage = true;
    const { rerender } = render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={vi.fn(async (_messageId: string) => {})}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    await userEvent.click(screen.getByRole("button", { name: "loadMore" }));
    expect(state.fetchNextPage).toHaveBeenCalledExactlyOnceWith();

    state.isFetchingNextPage = true;
    rerender(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={vi.fn(async (_messageId: string) => {})}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "loading" })).toBeDisabled();
  });

  it("shows query errors with retry", async () => {
    state.isError = true;
    state.isPending = false;
    state.hasData = false;
    const { rerender } = render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={vi.fn(async (_messageId: string) => {})}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("error");
    await userEvent.click(screen.getByRole("button", { name: "retry" }));
    expect(state.refetch).toHaveBeenCalledExactlyOnceWith();

    state.isError = false;
    state.isPending = true;
    state.hasData = false;
    rerender(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={vi.fn(async (_messageId: string) => {})}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("shows an empty list after loading", async () => {
    state.page = { items: [], total: 0 };
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={vi.fn(async (_messageId: string) => {})}
        onOpen={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    expect(screen.getByText("empty")).toBeInTheDocument();
  });

  it("keeps create disabled when this or another answer is already being created", async () => {
    const onCreate = vi.fn(async (_messageId: string) => {});
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        creatingMessageId="answer-b"
        onCreate={onCreate}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    const button = screen.getByRole("button", { name: "loading" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("ignores a duplicate create event while a side thread is already being made", async () => {
    let finish!: () => void;
    const onCreate = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={onCreate}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    const button = screen.getByRole("button", { name: "start" });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onCreate).toHaveBeenCalledExactlyOnceWith("answer-a");

    await act(async () => finish());
  });

  it("shows a create failure and lets the reader retry", async () => {
    const onCreate = vi.fn(async (_messageId: string) => {
      throw new Error("refused");
    });
    render(
      <ConversationSideThreads
        sourceConversationId="source-a"
        messageId="answer-a"
        onCreate={onCreate}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /title/ }));
    await userEvent.click(screen.getByRole("button", { name: "start" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("createFailed");
    expect(onCreate).toHaveBeenCalledExactlyOnceWith("answer-a");
  });
});
