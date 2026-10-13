import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyMemory } from "./my-memory";
import { PAGE_SIZE, useMyMemory } from "@/hooks/use-my-memory";

vi.mock("@/hooks/use-my-memory", async () => ({
  ...(await vi.importActual<object>("@/hooks/use-my-memory")),
  useMyMemory: vi.fn(),
}));
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, string>): string =>
      values ? `${key}:${Object.values(values).join("|")}` : key,
  useFormatter: () => ({ dateTime: () => "1 Aug 2026" }),
}));

function note(overrides = {}) {
  return {
    id: "n-1",
    agent_id: "a-1",
    agent_name: "Support",
    name: "prefs",
    description: null,
    content: "Prefers short answers",
    format: "md",
    kind: "note",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: null,
    written_at: null,
    deactivated_at: null,
    ...overrides,
  };
}

const setActive = vi.fn();
const remove = vi.fn();

const showPage = vi.fn();

function mount({
  items = [note()],
  external_stores = [],
  isLoading = false,
  error = undefined,
  total = undefined,
  skip = 0,
}: {
  items?: ReturnType<typeof note>[];
  external_stores?: string[];
  isLoading?: boolean;
  error?: unknown;
  total?: number;
  skip?: number;
} = {}) {
  vi.mocked(useMyMemory).mockReturnValue({
    page: isLoading || error ? undefined : { items, total: total ?? items.length, external_stores },
    isLoading,
    error,
    skip,
    showPage,
    setActive,
    remove,
  });
  render(<MyMemory />);
}

beforeEach(() => vi.clearAllMocks());

describe("your own memory", () => {
  it("shows what was written and who wrote it", () => {
    // "This is wrong" is a different sentence from "this was true last March",
    // and neither can be said without the provenance.
    mount();

    expect(screen.getByText("Prefers short answers")).toBeInTheDocument();
    expect(screen.getByText("writtenBy:Support|1 Aug 2026")).toBeInTheDocument();
  });

  it("suppresses a note that is in use", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "suppress" }));

    expect(setActive).toHaveBeenCalledWith("n-1", false);
  });

  it("restores one that is suppressed, and says so", async () => {
    mount({ items: [note({ deactivated_at: "2026-09-01T00:00:00Z" })] });

    expect(screen.getByText("suppressed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "restore" }));

    expect(setActive).toHaveBeenCalledWith("n-1", true);
  });

  it("deletes one outright", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "delete" }));

    expect(remove).toHaveBeenCalledWith("n-1");
  });

  it("names an external store rather than pretending the page is complete", () => {
    // A page of native notes presented as a whole inventory is worse than one
    // saying what it misses.
    mount({ items: [], external_stores: ["Support"] });

    expect(screen.getByText("externalStores:Support")).toBeInTheDocument();
  });

  it("says nothing is written down when nothing is", () => {
    mount({ items: [] });

    expect(screen.getByText("nothingYet")).toBeInTheDocument();
  });

  it("shows a skeleton while the store is loading", () => {
    mount({ isLoading: true });

    expect(screen.queryByText("nothingYet")).not.toBeInTheDocument();
  });

  it("names the agent generically where the note outlived it", () => {
    mount({ items: [note({ agent_name: null })] });

    expect(screen.getByText("writtenBy:anAgent|1 Aug 2026")).toBeInTheDocument();
  });

  it("dates a note by the agent's own write, not by your suppressing it", () => {
    // `updated_at` moves when you silence a note, and reading provenance off it
    // made the page say the agent had written it at that moment.
    mount({ items: [note({ written_at: "2026-09-01T00:00:00Z" })] });

    expect(screen.getByText(/writtenBy:Support/)).toBeInTheDocument();
  });

  it("shows a failure rather than a skeleton that never resolves", () => {
    // After the retries are spent React Query is neither loading nor holding
    // data, and a permanent skeleton says nothing about why.
    mount({ error: new Error("502") });

    expect(screen.queryByText("nothingYet")).not.toBeInTheDocument();
    expect(document.querySelector(".border-destructive\\/30")).toBeInTheDocument();
  });

  it("offers a way to the older notes when there are more than a page", () => {
    // A store with more than a page of notes had its older ones silently absent
    // and unreachable - unable to be read, suppressed or deleted.
    mount({ total: PAGE_SIZE * 3 });

    expect(screen.getByText(/showing:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "newer" })).toBeDisabled();
  });

  it("asks for the next page by its offset", async () => {
    mount({ total: PAGE_SIZE * 3 });

    await userEvent.click(screen.getByRole("button", { name: "older" }));

    expect(showPage).toHaveBeenCalledWith(PAGE_SIZE);
  });

  it("walks back from a later page", async () => {
    mount({ total: PAGE_SIZE * 3, skip: PAGE_SIZE });

    await userEvent.click(screen.getByRole("button", { name: "newer" }));

    expect(showPage).toHaveBeenCalledWith(0);
  });

  it("offers no paging where one page holds everything", () => {
    mount();

    expect(screen.queryByRole("button", { name: "older" })).not.toBeInTheDocument();
  });

  it("renders a description where the agent gave one", () => {
    mount({ items: [note({ description: "How they like things" })] });

    expect(screen.getByText("How they like things")).toBeInTheDocument();
  });
});
