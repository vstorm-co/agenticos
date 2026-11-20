import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ConversationSearchDialog } from "./conversation-search-dialog";

const state = vi.hoisted(() => ({
  isError: false,
  refetch: vi.fn(),
  items: [
    {
      id: "c-1",
      title: "Warsaw trip",
      updated_at: "2026-11-19T10:00:00Z",
      snippet: "Visit **Warsaw** <script>literal</script>",
      hits: 2,
    },
  ],
}));
vi.mock("@/hooks", () => ({
  useConversationSearch: () => ({
    data: { items: state.items },
    isFetching: false,
    isError: state.isError,
    refetch: state.refetch,
  }),
}));
vi.mock("@/components/ui/list-controls", () => ({ useDebounced: (value: string) => value }));
beforeEach(() => {
  state.isError = false;
  vi.clearAllMocks();
});

it("shows highlighted excerpts as safe text and opens a result with the keyboard", async () => {
  const onSelect = vi.fn();
  render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={onSelect} />);
  await userEvent.type(screen.getByRole("combobox"), "Warsaw");
  expect(screen.getByRole("option").querySelectorAll("mark")).toHaveLength(2);
  expect(screen.getByRole("option").querySelector("script")).toBeNull();
  expect(screen.getByText(/<script>literal/)).toBeInTheDocument();
  expect(screen.getByText("2 matching messages")).toBeInTheDocument();
  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("c-1");
});

it("keeps a failed search explicit and offers a retry", async () => {
  state.isError = true;
  render(<ConversationSearchDialog open onOpenChange={vi.fn()} onSelect={vi.fn()} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not search conversations");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});
