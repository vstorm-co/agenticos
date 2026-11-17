import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessageSearchHit } from "@/lib/conversation-message-search-api";
import type { Conversation } from "@/types/conversation";
import { ConversationSearchDialog } from "./conversation-search-dialog";

const state = vi.hoisted(() => ({
  messageResults: [] as ConversationMessageSearchHit[],
  messageHasData: true,
  messageIsError: false,
  messageIsFetching: false,
  messageRefetch: vi.fn(),
  titleResults: [] as Conversation[],
  titleHasData: true,
  titleIsError: false,
  titleIsFetching: false,
  titleRefetch: vi.fn(),
  titleTerm: "",
}));

vi.mock("@/hooks/use-conversation-message-search", () => ({
  useConversationMessageSearch: () => ({
    data: state.messageHasData ? state.messageResults : undefined,
    isError: state.messageIsError,
    isFetching: state.messageIsFetching,
    refetch: state.messageRefetch,
  }),
}));
vi.mock("@/hooks/use-conversations", () => ({
  useConversationSearch: (term: string) => {
    state.titleTerm = term;
    return {
      data: state.titleHasData
        ? { items: state.titleResults, total: state.titleResults.length }
        : undefined,
      isError: state.titleIsError,
      isFetching: state.titleIsFetching,
      refetch: state.titleRefetch,
    };
  },
}));
vi.mock("@/components/ui/list-controls", () => ({ useDebounced: (value: string) => value }));
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () =>
    Object.assign((key: string) => key, {
      rich: (key: string) => key,
      markup: (key: string) => key,
      has: () => true,
    }),
}));

const hit: ConversationMessageSearchHit = {
  conversation_id: "conversation-1",
  message_id: "message-2",
  thread_root_message_id: "message-1",
  title: "Q3 roadmap",
  updated_at: "2026-11-16T10:00:00Z",
  matched_at: "2026-11-16T09:00:00Z",
  hits: 2,
  snippet: "we approved the **pricing** change",
  speaker_role: "user",
  speaker_name: "Sam",
};

const titleOnlyConversation: Conversation = {
  id: "conversation-title-only",
  title: "Vendor contract review",
  created_at: "2026-11-15T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
  is_archived: true,
};

beforeEach(() => {
  state.messageResults = [hit];
  state.messageHasData = true;
  state.messageIsError = false;
  state.messageIsFetching = false;
  state.messageRefetch.mockReset();
  state.titleResults = [titleOnlyConversation];
  state.titleHasData = true;
  state.titleIsError = false;
  state.titleIsFetching = false;
  state.titleRefetch.mockReset();
  state.titleTerm = "";
});

describe("ConversationSearchDialog", () => {
  it("shows message excerpts and selects the exact room-thread destination", () => {
    const onSelect = vi.fn();
    const onSelectResult = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConversationSearchDialog
        open
        onOpenChange={onOpenChange}
        onSelect={onSelect}
        onSelectResult={onSelectResult}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "pricing" },
    });

    expect(screen.getByText("Q3 roadmap")).toBeInTheDocument();
    expect(screen.getByText("pricing").tagName).toBe("MARK");
    fireEvent.click(screen.getByRole("button", { name: /Q3 roadmap/ }));

    expect(onSelectResult).toHaveBeenCalledExactlyOnceWith({
      conversationId: "conversation-1",
      messageId: "message-2",
      threadRootMessageId: "message-1",
    });
    expect(onSelect).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps focus on an exact-message destination when closing search", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open search
          </button>
          <button type="button" data-testid="matched-message">
            Matched message
          </button>
          <ConversationSearchDialog
            open={open}
            onOpenChange={setOpen}
            onSelect={vi.fn()}
            onSelectResult={() => screen.getByTestId("matched-message").focus()}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open search" }));
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "pricing" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Q3 roadmap/ }));

    await screen.findByRole("button", { name: "Open search" });
    expect(screen.getByTestId("matched-message")).toHaveFocus();
  });

  it("keeps the conversation-only selection contract for older callers", () => {
    const onSelect = vi.fn();
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={onSelect} />);
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "pricing" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Q3 roadmap/ }));

    expect(onSelect).toHaveBeenCalledExactlyOnceWith("conversation-1");
  });

  it("finds a conversation by title even when no message body matches", () => {
    state.messageResults = [];
    const onSelect = vi.fn();
    const onSelectResult = vi.fn();
    render(
      <ConversationSearchDialog
        open
        onOpenChange={vi.fn()}
        onSelect={onSelect}
        onSelectResult={onSelectResult}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "searchModeLabel" }), {
      target: { value: "titles" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "vendor contract" },
    });

    expect(state.titleTerm).toBe("vendor contract");
    expect(screen.getByRole("button", { name: "Vendor contract review" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vendor contract review" }));

    expect(onSelect).toHaveBeenCalledExactlyOnceWith("conversation-title-only");
    expect(onSelectResult).not.toHaveBeenCalled();
  });

  it("resets the query and search mode after selecting a title result", () => {
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open search
          </button>
          <ConversationSearchDialog open={open} onOpenChange={setOpen} onSelect={vi.fn()} />
        </>
      );
    }

    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox", { name: "searchModeLabel" }), {
      target: { value: "titles" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "vendor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Vendor contract review" }));
    fireEvent.click(screen.getByRole("button", { name: "Open search" }));

    expect(screen.getByRole("combobox", { name: "searchModeLabel" })).toHaveValue("messages");
    expect(screen.getByRole("textbox", { name: "searchLabel" })).toHaveValue("");
  });

  it("shows a retry action when message search fails instead of showing an empty result", () => {
    state.messageResults = [];
    state.messageHasData = false;
    state.messageIsError = true;
    const onSelect = vi.fn();
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={onSelect} />);
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "pricing" },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("searchFailed");
    expect(screen.queryByText("noMessageSearchResults")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "retrySearch" }));

    expect(state.messageRefetch).toHaveBeenCalledOnce();
  });

  it("shows the same retry state for title-search errors", () => {
    state.titleResults = [];
    state.titleHasData = false;
    state.titleIsError = true;
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "searchModeLabel" }), {
      target: { value: "titles" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "vendor" },
    });

    fireEvent.click(screen.getByRole("button", { name: "retrySearch" }));

    expect(screen.getByRole("alert")).toHaveTextContent("searchFailed");
    expect(state.titleRefetch).toHaveBeenCalledOnce();
  });

  it("shows loading and empty states for message searches without matches", () => {
    state.messageResults = [];
    state.messageIsFetching = true;
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    const input = screen.getByRole("textbox", { name: "searchLabel" });
    fireEvent.change(input, { target: { value: "missing" } });
    expect(screen.getByText("searching")).toBeInTheDocument();

    state.messageIsFetching = false;
    fireEvent.change(input, { target: { value: "still missing" } });
    expect(screen.getByText("noMessageSearchResults")).toBeInTheDocument();
  });

  it("shows loading and empty states for title searches without matches", () => {
    state.titleResults = [];
    state.titleIsFetching = true;
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "searchModeLabel" }), {
      target: { value: "titles" },
    });
    const input = screen.getByRole("textbox", { name: "searchLabel" });
    fireEvent.change(input, { target: { value: "missing" } });
    expect(screen.getByText("searching")).toBeInTheDocument();

    state.titleIsFetching = false;
    fireEvent.change(input, { target: { value: "still missing" } });
    expect(screen.getByText("noSearchResults")).toBeInTheDocument();
  });

  it("omits optional thread and speaker details and uses untitled fallbacks", () => {
    state.messageResults = [
      {
        ...hit,
        thread_root_message_id: null,
        title: null,
        speaker_name: null,
        snippet: "**",
      },
    ];
    const onSelectResult = vi.fn();
    const rendered = render(
      <ConversationSearchDialog
        open
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        onSelectResult={onSelectResult}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "pricing" },
    });

    const result = screen.getByRole("button", { name: /untitled/ });
    expect(result).not.toHaveTextContent("Sam:");
    expect(result.querySelector("mark")).toBeNull();
    fireEvent.click(result);
    expect(onSelectResult).toHaveBeenCalledExactlyOnceWith({
      conversationId: "conversation-1",
      messageId: "message-2",
    });

    rendered.unmount();
    state.titleResults = [{ ...titleOnlyConversation, title: "" }];
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "searchModeLabel" }), {
      target: { value: "titles" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "searchLabel" }), {
      target: { value: "vendor" },
    });
    expect(screen.getByRole("button", { name: "untitled" })).toBeInTheDocument();
  });

  it("falls back to message mode for an unsupported select value", () => {
    render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
    const mode = screen.getByRole("combobox", { name: "searchModeLabel" });
    fireEvent.change(mode, { target: { value: "unsupported" } });
    expect(mode).toHaveValue("messages");
  });
});
