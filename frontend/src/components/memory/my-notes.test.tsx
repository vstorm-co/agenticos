import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { MyNotes } from "./my-notes";
import { useMyMemory } from "@/hooks/use-my-memory";
import type { MemoryNote } from "@/lib/memory-api";
vi.mock("@/hooks/use-my-memory", () => ({ PAGE_SIZE: 50, useMyMemory: vi.fn() }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) =>
    content === "Index link" ? (
      <a href="./checklist.md">Open checklist</a>
    ) : content === "Missing link" ? (
      <a href="./missing.md">Find missing note</a>
    ) : content === "Empty relative link" ? (
      <a href="./">Current note</a>
    ) : content === "Malformed link" ? (
      <a href="./bad%ZZ.md">Malformed target</a>
    ) : (
      <p>{content}</p>
    ),
}));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${Object.values(values).join("|")}` : key,
  useLocale: () => "en",
  useFormatter: () => ({ dateTime: () => "4 Nov 2026" }),
}));
const remove = vi.fn();
const setActive = vi.fn();
const showPage = vi.fn();
const note: MemoryNote = {
  id: "n-1",
  agent_id: "a-1",
  agent_name: "Playground",
  name: "checklist.md",
  description: "A test checklist",
  content: "Checklist content",
  format: "md",
  kind: "note",
  created_at: "2026-11-04T00:00:00Z",
  updated_at: null,
  written_at: null,
  deactivated_at: null,
};
function mount(
  overrides: Partial<MemoryNote> = {},
  items: MemoryNote[] = [{ ...note, ...overrides }],
) {
  vi.mocked(useMyMemory).mockReturnValue({
    page: { items, total: items.length },
    isLoading: false,
    error: null,
    skip: 0,
    showPage,
    setActive,
    remove,
  });
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MyNotes />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  remove.mockResolvedValue(true);
  setActive.mockResolvedValue(true);
});
it("opens one note at a time instead of expanding every file inline", async () => {
  mount();
  expect(screen.queryByText("Checklist content")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  expect(await screen.findByText("Checklist content")).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: "noteDetails" }));
  expect(screen.getByText("writtenBy:Playground|4 Nov 2026")).toBeVisible();
});
it("suppresses and restores a note without deleting it", async () => {
  mount({ deactivated_at: "2026-11-04T12:00:00Z" });
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  await userEvent.click(screen.getByRole("tab", { name: "noteDetails" }));
  await userEvent.click(screen.getByRole("button", { name: "restore" }));
  expect(setActive).toHaveBeenCalledWith("n-1", true);
  expect(remove).not.toHaveBeenCalled();
});
it("requires confirmation before permanent deletion", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  await userEvent.click(screen.getByRole("tab", { name: "noteDetails" }));
  await userEvent.click(screen.getByRole("button", { name: "delete" }));
  expect(remove).not.toHaveBeenCalled();
  const confirm = screen.getAllByRole("dialog").at(-1)!;
  await userEvent.click(within(confirm).getByRole("button", { name: "delete" }));
  expect(remove).toHaveBeenCalledWith("n-1");
});
it("keeps the note visible after deletion is refused", async () => {
  remove.mockResolvedValue(false);
  mount();
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  await userEvent.click(screen.getByRole("tab", { name: "noteDetails" }));
  await userEvent.click(screen.getByRole("button", { name: "delete" }));
  const confirm = screen.getAllByRole("dialog").at(-1)!;
  await userEvent.click(within(confirm).getByRole("button", { name: "delete" }));
  expect(screen.getByRole("dialog", { name: "deleteNote" })).toBeVisible();
  expect(screen.getAllByRole("dialog", { hidden: true })).toHaveLength(2);
});

it("follows an index link within the same agent's memory instead of navigating away", async () => {
  mount({}, [
    { ...note, id: "index", name: "MEMORY.md", content: "Index link" },
    { ...note, id: "other", agent_id: "other-agent", content: "Another agent's checklist" },
    note,
  ]);
  await userEvent.click(screen.getByRole("button", { name: /^MEMORY.md/ }));
  await userEvent.click(await screen.findByRole("link", { name: "Open checklist" }));
  expect(await screen.findByText("Checklist content")).toBeVisible();
  expect(screen.queryByText("Another agent's checklist")).not.toBeInTheDocument();
});

it("searches the whole note store when an index target is outside the loaded page", async () => {
  mount({ name: "MEMORY.md", content: "Missing link" });
  await userEvent.click(screen.getByRole("button", { name: /^MEMORY.md/ }));
  await userEvent.click(await screen.findByRole("link", { name: "Find missing note" }));
  expect(useMyMemory).toHaveBeenLastCalledWith("missing.md");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("ignores malformed index links without replacing the visible note", async () => {
  mount({ content: "Malformed link" });
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  await userEvent.click(await screen.findByRole("link", { name: "Malformed target" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(useMyMemory).not.toHaveBeenLastCalledWith("bad%ZZ.md");
});
it("clears a whole-store search with no matching notes", async () => {
  mount({}, []);
  await userEvent.type(screen.getByRole("textbox", { name: "searchNotes" }), "unmatched");
  await userEvent.click(screen.getByRole("button", { name: "clearFilters" }));
  expect(screen.getByRole("textbox", { name: "searchNotes" })).toHaveValue("");
});

it("does not replace a selected note for an empty relative reference", async () => {
  mount({ content: "Empty relative link" });
  await userEvent.click(screen.getByRole("button", { name: /checklist.md/ }));
  await userEvent.click(await screen.findByRole("link", { name: "Current note" }));
  expect(screen.getByRole("link", { name: "Current note" })).toBeInTheDocument();
  expect(showPage).not.toHaveBeenCalled();
});
