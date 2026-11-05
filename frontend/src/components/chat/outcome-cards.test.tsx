import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OutcomeActions, OutcomeCards } from "./outcome-cards";

const state = vi.hoisted(() => ({
  outcomes: [] as unknown[],
  error: null as Error | null,
  retry: vi.fn(),
  settle: vi.fn().mockResolvedValue(undefined),
  via: "" as string,
}));

vi.mock("@/hooks/use-outcomes", () => ({
  useConversationOutcomes: () => ({
    outcomes: state.outcomes,
    error: state.error,
    retry: state.retry,
  }),
  useSettleOutcome: (via: string) => {
    state.via = via;
    return { settle: state.settle, isPending: false };
  },
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const outcome = (overrides: Record<string, unknown> = {}) => ({
  id: "o-1",
  kind: "finding",
  summary: "Finance is waiting on your approval",
  context_url: "/runs?tab=approvals",
  status: "open",
  source_conversation_id: "c-1",
  created_at: "2026-11-01T10:00:00Z",
  settled_at: null,
  settled_via: null,
  ...overrides,
});

beforeEach(() => {
  state.outcomes = [];
  state.error = null;
  state.retry.mockClear();
  state.settle.mockClear();
});

describe("OutcomeCards", () => {
  it("shows nothing when nothing needs the person", () => {
    const { container } = render(<OutcomeCards conversationId="c-1" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows each outcome with where to open it and the three answers, settled from the chat", async () => {
    state.outcomes = [
      outcome(),
      outcome({ id: "o-2", summary: "A watch found a thing", context_url: null }),
    ];
    render(<OutcomeCards conversationId="c-1" />);

    expect(screen.getByRole("list", { name: "label" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "open" })).toHaveLength(1);

    fireEvent.click(screen.getAllByRole("button", { name: "resolve" })[0] as HTMLElement);

    await waitFor(() =>
      expect(state.settle).toHaveBeenCalledWith({ id: "o-1", action: "resolve" }),
    );
    expect(state.via).toBe("chat");
  });
  it("offers only the actual approval destination for an approval notification", () => {
    state.outcomes = [outcome({ kind: "approval_requested" })];
    render(<OutcomeCards conversationId="c-1" />);
    expect(screen.getByRole("link", { name: "reviewApproval" })).toHaveAttribute(
      "href",
      "/runs?tab=approvals",
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(state.settle).not.toHaveBeenCalled();
  });

  it("hides approval notices from every run while the decision panel is visible", () => {
    state.outcomes = [
      outcome({ kind: "approval_requested", source_run_id: "r-1" }),
      outcome({
        id: "o-other",
        kind: "approval_requested",
        source_run_id: "r-2",
        summary: "Another approval",
      }),
      outcome({ id: "o-finding", summary: "A finding" }),
    ];
    render(<OutcomeCards conversationId="c-1" hasApprovalPanel />);
    expect(screen.queryByText("Finance is waiting on your approval")).toBeNull();
    expect(screen.queryByText("Another approval")).toBeNull();
    expect(screen.getByText("A finding")).toBeVisible();
  });

  it("hides stale approval notices while a continuation is working", () => {
    state.outcomes = [
      outcome({ kind: "approval_requested" }),
      outcome({ id: "finding", summary: "A finding" }),
    ];
    render(<OutcomeCards conversationId="c-1" isWorking />);
    expect(screen.queryByText("Finance is waiting on your approval")).toBeNull();
    expect(screen.getByText("A finding")).toBeVisible();
  });

  it("keeps a legacy approval reachable when its source or link is absent", () => {
    state.outcomes = [outcome({ kind: "approval_requested", context_url: null })];
    render(<OutcomeCards conversationId="c-1" />);
    expect(screen.getByRole("link", { name: "reviewApproval" })).toHaveAttribute(
      "href",
      "/runs?tab=approvals",
    );
  });

  it("also hides a legacy approval without a source run while decisions are visible", () => {
    state.outcomes = [outcome({ kind: "approval_requested", context_url: null })];
    const { container } = render(<OutcomeCards conversationId="c-1" hasApprovalPanel />);
    expect(container).toBeEmptyDOMElement();
    expect(state.settle).not.toHaveBeenCalled();
  });

  it("renders no empty list when the decision panel handles the only outcome", () => {
    state.outcomes = [outcome({ kind: "approval_requested", source_run_id: "r-1" })];
    const { container } = render(<OutcomeCards conversationId="c-1" hasApprovalPanel />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("OutcomeActions", () => {
  it("offers acknowledge, resolve and mute, and a failed answer is not an unhandled rejection", async () => {
    state.settle.mockRejectedValueOnce(new Error("closed"));
    render(<OutcomeActions id="o-9" via="inbox" />);

    fireEvent.click(screen.getByRole("button", { name: "mute" }));

    await waitFor(() => expect(state.settle).toHaveBeenCalledWith({ id: "o-9", action: "mute" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("closed"));
    expect(state.via).toBe("inbox");
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });
});

it("shows a failed read with a retry instead of an empty chat", () => {
  state.error = new Error("offline");
  render(<OutcomeCards conversationId="failed-chat" />);
  expect(screen.getByRole("alert")).toHaveTextContent("loadFailed");
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(state.retry).toHaveBeenCalledOnce();
});
