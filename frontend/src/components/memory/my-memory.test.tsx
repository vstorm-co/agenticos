import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyMemory } from "./my-memory";
import { useMyMemory } from "@/hooks";

vi.mock("@/hooks", () => ({ useMyMemory: vi.fn() }));
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
    deactivated_at: null,
    ...overrides,
  };
}

const setActive = vi.fn();
const remove = vi.fn();

function mount({
  items = [note()],
  external_stores = [],
  isLoading = false,
}: {
  items?: ReturnType<typeof note>[];
  external_stores?: string[];
  isLoading?: boolean;
} = {}) {
  vi.mocked(useMyMemory).mockReturnValue({
    page: isLoading ? undefined : { items, total: items.length, external_stores },
    isLoading,
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
    mount({ items: [note({ agent_name: null, updated_at: "2026-09-01T00:00:00Z" })] });

    expect(screen.getByText("writtenBy:anAgent|1 Aug 2026")).toBeInTheDocument();
  });

  it("renders a description where the agent gave one", () => {
    mount({ items: [note({ description: "How they like things" })] });

    expect(screen.getByText("How they like things")).toBeInTheDocument();
  });
});
