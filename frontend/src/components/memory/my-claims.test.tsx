import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MyClaims } from "./my-claims";
import { useMyClaims } from "@/hooks/use-my-claims";
import type { MemoryClaim } from "@/lib/memory-api";

vi.mock("@/hooks/use-my-claims", () => ({ useMyClaims: vi.fn() }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, string | number>) =>
    values ? `${key}:${Object.values(values).join("|")}` : key,
  useFormatter: () => ({ dateTime: () => "4 Nov 2026" }),
}));
const correct = vi.fn();
const retract = vi.fn();
const setHistory = vi.fn();
const showPage = vi.fn();
function claim(overrides: Partial<MemoryClaim> = {}): MemoryClaim {
  return {
    id: "c-1",
    agent_id: null,
    agent_name: null,
    scope: "profile",
    subject: "style",
    statement: "Prefers short answers",
    kind: "preference",
    origin: "person",
    status: "current",
    observed_at: "2026-11-04T10:00:00Z",
    effective_from: null,
    effective_to: null,
    supersedes_id: null,
    derived_from_count: 0,
    ...overrides,
  };
}
function mount(
  options: {
    items?: MemoryClaim[];
    error?: unknown;
    isLoading?: boolean;
    total?: number;
    skip?: number;
  } = {},
) {
  const items = options.items ?? [claim()];
  vi.mocked(useMyClaims).mockReturnValue({
    page:
      options.error || options.isLoading
        ? undefined
        : { items, total: options.total ?? items.length },
    error: options.error,
    isLoading: options.isLoading ?? false,
    history: false,
    setHistory,
    skip: options.skip ?? 0,
    showPage,
    correct,
    retract,
  });
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MyClaims />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  correct.mockResolvedValue(true);
  retract.mockResolvedValue(true);
});
describe("memory browser", () => {
  it("keeps a decision's evidence out of the list until its row is opened", async () => {
    mount({
      items: [
        claim({
          kind: "decision",
          statement: "Ask for an update",
          episode: {
            situation: "Late supplier",
            choice: "Ask again",
            alternatives: ["Wait", "Escalate"],
            expected_outcome: "New date",
            actual_outcome: null,
            correction: null,
          },
        }),
      ],
    });
    expect(screen.queryByText("Late supplier")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Ask for an update/ }));
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByText("Late supplier")).toBeVisible();
    expect(within(panel).getByText("Wait; Escalate")).toBeVisible();
    expect(within(panel).getByText("origin.person")).toBeVisible();
  });
  it("passes search and type filters to the paginated read", async () => {
    mount();
    await userEvent.type(screen.getByRole("textbox", { name: "searchMemories" }), "invoice");
    await userEvent.click(screen.getByRole("button", { name: "kind.decision" }));
    expect(useMyClaims).toHaveBeenLastCalledWith({ q: "invoice", kind: "decision" });
  });
  it("includes history only after it is requested", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: "filters" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "showHistory" }));
    expect(setHistory).toHaveBeenCalledWith(true);
  });
  it("opens an editor and closes only after the correction succeeds", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
    await userEvent.click(screen.getByRole("button", { name: "correct" }));
    await userEvent.type(screen.getByLabelText("statement"), "!");
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(correct).toHaveBeenCalledWith("c-1", "Prefers short answers!", null, undefined);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("retains entered text after a refused correction", async () => {
    correct.mockResolvedValue(false);
    mount();
    await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
    await userEvent.click(screen.getByRole("button", { name: "correct" }));
    await userEvent.type(screen.getByLabelText("statement"), "!");
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(screen.getByLabelText("statement")).toHaveValue("Prefers short answers!");
  });
  it("asks before stopping use and retains historical entries without live actions", async () => {
    mount({ items: [claim({ status: "retracted" })] });
    await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
    expect(screen.queryByRole("button", { name: "retract" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "correct" })).not.toBeInTheDocument();
  });
  it("does not silently retract a row when opening it", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
    await userEvent.click(screen.getByRole("button", { name: "retract" }));
    expect(retract).not.toHaveBeenCalled();
    const confirm = screen.getAllByRole("dialog").at(-1)!;
    await userEvent.click(within(confirm).getByRole("button", { name: "retract" }));
    expect(retract).toHaveBeenCalledWith("c-1");
  });
  it("distinguishes an empty store, a failed read and initial loading", () => {
    const empty = mount({ items: [] });
    expect(screen.getByText("emptyMemories")).toBeVisible();
    empty.unmount();
    const failed = mount({ error: new Error("offline") });
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.queryByText("emptyMemories")).not.toBeInTheDocument();
    failed.unmount();
    mount({ isLoading: true });
    expect(screen.queryByText("emptyMemories")).not.toBeInTheDocument();
  });
  it("keeps older memories reachable and does not return a false zero count", async () => {
    mount({ total: 205, skip: 100 });
    expect(screen.getByText("showing:101|101|205")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "older" }));
    expect(showPage).toHaveBeenCalledWith(200);
    await userEvent.click(screen.getByRole("button", { name: "newer" }));
    expect(showPage).toHaveBeenCalledWith(0);
  });
});

it("corrects a decision with an effective date and observed outcome", async () => {
  mount({
    items: [
      claim({
        kind: "decision",
        episode: {
          situation: "Late delivery",
          choice: "Ask",
          alternatives: [],
          expected_outcome: "New date",
          actual_outcome: null,
          correction: null,
        },
      }),
    ],
  });
  await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
  await userEvent.click(screen.getByRole("button", { name: "correct" }));
  await userEvent.type(screen.getByLabelText("episode.actual"), "Confirmed Friday");
  fireEvent.change(screen.getByLabelText("effectiveFrom"), { target: { value: "2026-11-07" } });
  await userEvent.click(screen.getByRole("button", { name: "save" }));
  expect(correct).toHaveBeenCalledWith(
    "c-1",
    "Prefers short answers",
    "2026-11-07T00:00:00Z",
    expect.objectContaining({
      actual_outcome: "Confirmed Friday",
      correction: "Prefers short answers",
    }),
  );
});
it("can cancel an edit and dismiss detail without changing memory", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
  await userEvent.click(screen.getByRole("button", { name: "correct" }));
  await userEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(screen.queryByLabelText("statement")).not.toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(correct).not.toHaveBeenCalled();
});
it("retains a refused retraction for another review", async () => {
  retract.mockResolvedValue(false);
  mount();
  await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
  await userEvent.click(screen.getByRole("button", { name: "retract" }));
  await userEvent.click(
    within(screen.getAllByRole("dialog").at(-1)!).getByRole("button", { name: "retract" }),
  );
  expect(screen.getAllByRole("dialog", { hidden: true })).toHaveLength(2);
});
it("supports compact type and scope selection and clears a search with no matches", async () => {
  mount({ items: [] });
  await userEvent.click(screen.getByRole("combobox", { name: "typeLabel" }));
  await userEvent.click(screen.getByRole("option", { name: "kind.fact" }));
  await userEvent.click(screen.getByRole("button", { name: "filters" }));
  await userEvent.click(screen.getByRole("combobox", { name: "scopeLabel" }));
  await userEvent.click(screen.getByRole("option", { name: "scope.agent" }));
  expect(useMyClaims).toHaveBeenLastCalledWith({ q: "", kind: "fact", scope: "agent" });
  await userEvent.click(screen.getByRole("button", { name: "clearFilters" }));
  expect(useMyClaims).toHaveBeenLastCalledWith({ q: "" });
});

it.each([null, "Researcher"])(
  "shows an agent-scoped consolidated memory without confusing its audience (%s)",
  async (agentName) => {
    mount({
      items: [
        claim({
          scope: "agent",
          agent_id: "a",
          agent_name: agentName,
          origin: "consolidation",
          derived_from_count: 2,
          effective_from: "2026-11-01T00:00:00Z",
        }),
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent(`scopeAgent:${agentName ?? "anAgent"}`);
    expect(screen.getByRole("dialog")).toHaveTextContent("drawnFrom:2");
  },
);
it("keeps a refused memory retraction open for another decision", async () => {
  retract.mockResolvedValue(false);
  mount();
  await userEvent.click(screen.getByRole("button", { name: /Prefers short answers/ }));
  await userEvent.click(screen.getByRole("button", { name: "retract" }));
  const confirm = screen.getAllByRole("dialog").at(-1)!;
  await userEvent.click(within(confirm).getByRole("button", { name: "retract" }));
  expect(confirm).toBeInTheDocument();
});
