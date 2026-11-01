import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OutcomeActions, OutcomeCards } from "./outcome-cards";

const state = vi.hoisted(() => ({
  outcomes: [] as unknown[],
  settle: vi.fn().mockResolvedValue(undefined),
  via: "" as string,
}));

vi.mock("@/hooks/use-outcomes", () => ({
  useConversationOutcomes: () => state.outcomes,
  useSettleOutcome: (via: string) => {
    state.via = via;
    return { settle: state.settle, isPending: false };
  },
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const outcome = (overrides: Record<string, unknown> = {}) => ({
  id: "o-1",
  kind: "approval_requested",
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
});

describe("OutcomeActions", () => {
  it("offers acknowledge, resolve and mute, and a failed answer is not an unhandled rejection", async () => {
    state.settle.mockRejectedValueOnce(new Error("closed"));
    render(<OutcomeActions id="o-9" via="inbox" />);

    fireEvent.click(screen.getByRole("button", { name: "mute" }));

    await waitFor(() => expect(state.settle).toHaveBeenCalledWith({ id: "o-9", action: "mute" }));
    expect(state.via).toBe("inbox");
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });
});
