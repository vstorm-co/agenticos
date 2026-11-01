import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyClaims } from "./my-claims";
import { useMyClaims } from "@/hooks/use-my-claims";
import type { MemoryClaim } from "@/lib/memory-api";

vi.mock("@/hooks/use-my-claims", () => ({ useMyClaims: vi.fn() }));
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, string | number>): string =>
      values ? `${key}:${Object.values(values).join("|")}` : key,
  useFormatter: () => ({ dateTime: () => "1 Nov 2026" }),
}));

function claim(overrides: Partial<MemoryClaim> = {}): MemoryClaim {
  return {
    id: "c-1",
    agent_id: null,
    agent_name: null,
    scope: "profile",
    subject: "style",
    statement: "Prefers short answers",
    kind: "preference",
    origin: "agent",
    status: "current",
    observed_at: "2026-11-01T10:00:00Z",
    effective_from: null,
    effective_to: null,
    supersedes_id: null,
    derived_from_count: 0,
    ...overrides,
  };
}

const correct = vi.fn();
const retract = vi.fn();
const setHistory = vi.fn();

function mount({
  items = [claim()],
  history = false,
  isLoading = false,
  error = undefined,
}: {
  items?: MemoryClaim[];
  history?: boolean;
  isLoading?: boolean;
  error?: unknown;
} = {}) {
  vi.mocked(useMyClaims).mockReturnValue({
    page: isLoading || error ? undefined : { items, total: items.length },
    isLoading,
    error,
    history,
    setHistory,
    correct,
    retract,
  });
  return render(<MyClaims />);
}

beforeEach(() => {
  vi.clearAllMocks();
  correct.mockResolvedValue(undefined);
});

describe("MyClaims", () => {
  it("shows nothing while loading, on an error, and when nothing is recorded", () => {
    expect(mount({ isLoading: true }).container).toBeEmptyDOMElement();
    expect(mount({ error: new Error("x") }).container).toBeEmptyDOMElement();
    expect(mount({ items: [] }).container).toBeEmptyDOMElement();
  });

  it("says where each claim lives and where it came from", () => {
    mount({
      items: [
        claim(),
        claim({
          id: "c-2",
          scope: "agent",
          agent_name: "Finance",
          origin: "consolidation",
          derived_from_count: 3,
          effective_from: "2026-11-02T00:00:00Z",
          statement: "Piotr handles invoices",
          status: "disputed",
        }),
      ],
    });

    expect(screen.getByText("scopeProfile")).toBeInTheDocument();
    expect(screen.getByText("scopeAgent:Finance")).toBeInTheDocument();
    expect(screen.getByText("origin.consolidation")).toBeInTheDocument();
    expect(screen.getByText("drawnFrom:3")).toBeInTheDocument();
    expect(screen.getByText("since:1 Nov 2026")).toBeInTheDocument();
    expect(screen.getByText("status.disputed")).toBeInTheDocument();
  });

  it("names an agent that has no name", () => {
    mount({ items: [claim({ scope: "agent" })] });

    expect(screen.getByText("scopeAgent:anAgent")).toBeInTheDocument();
  });

  it("retracts a claim", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "retract" }));

    expect(retract).toHaveBeenCalledWith("c-1");
  });

  it("corrects a claim in the person's own words from a date", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "correct" }));
    const box = screen.getByLabelText("statement");
    const save = screen.getByRole("button", { name: "save" });
    expect(save).toBeDisabled();
    await userEvent.clear(box);
    await userEvent.type(box, "Prefers long answers");
    await userEvent.type(screen.getByLabelText("effectiveFrom"), "2026-11-03");
    await userEvent.click(save);

    expect(correct).toHaveBeenCalledWith("c-1", "Prefers long answers", "2026-11-03T00:00:00Z");
    expect(screen.queryByLabelText("statement")).not.toBeInTheDocument();
  });

  it("corrects without a date and can be cancelled", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "correct" }));
    await userEvent.type(screen.getByLabelText("statement"), "!");
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(correct).toHaveBeenCalledWith("c-1", "Prefers short answers!", null);

    await userEvent.click(screen.getByRole("button", { name: "correct" }));
    await userEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(screen.queryByLabelText("statement")).not.toBeInTheDocument();
  });

  it("offers history, and a replaced claim can no longer be changed", async () => {
    mount({ items: [claim({ status: "superseded" })], history: true });

    expect(screen.getByText("status.superseded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "correct" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(setHistory).toHaveBeenCalledWith(false);
  });
});
