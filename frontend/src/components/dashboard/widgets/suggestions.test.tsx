import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Period } from "@/lib/dashboard/period";
import type { AuthoringWaiting } from "@/types/authoring";
import { SuggestionsWidget } from "./suggestions";

const state = vi.hoisted(() => ({
  waiting: null as AuthoringWaiting | null,
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-authoring", () => ({ useWaitingSuggestions: () => state }));

const PERIOD: Period = { preset: "30d", from: "2026-09-21", to: "2026-10-20" };

function widget() {
  render(<SuggestionsWidget title="Suggestions waiting" hint="" period={PERIOD} />);
}

beforeEach(() => {
  state.waiting = null;
  state.isLoading = false;
  state.error = null;
  state.refetch = vi.fn();
});

describe("SuggestionsWidget", () => {
  it("lists each agent with what waits, and the skill changes", () => {
    state.waiting = {
      agents: [{ agent_id: "a1", name: "Clerk", instructions: 2, tools: 1 }],
      skills: 3,
    };
    widget();
    expect(screen.getByRole("link", { name: "Clerk" })).toHaveAttribute(
      "href",
      "/agents/a1?tab=build",
    );
    expect(screen.getByText("2 instruction changes · 1 tool change")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "3 skill changes to review" })).toHaveAttribute(
      "href",
      "/skills",
    );
  });

  it("counts setting changes, and the context file changes", () => {
    state.waiting = {
      agents: [{ agent_id: "a1", name: "Clerk", instructions: 1, tools: 0, fields: 2 }],
      skills: 0,
      contexts: 1,
    };
    widget();
    expect(screen.getByText("1 instruction change · 2 setting changes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 context file change to review" })).toHaveAttribute(
      "href",
      "/context",
    );
    expect(screen.queryByRole("link", { name: /skill change/ })).toBeNull();
  });

  it("is not empty while only a context file change waits", () => {
    state.waiting = { agents: [], skills: 0, contexts: 2 };
    widget();
    expect(screen.queryByText("Nothing waiting")).toBeNull();
    expect(screen.getByRole("link", { name: "2 context file changes to review" })).toBeVisible();
  });

  it("says nothing waits, and lists an agent with tool changes only", () => {
    state.waiting = { agents: [], skills: 0 };
    const { unmount } = render(<SuggestionsWidget title="t" hint="" period={PERIOD} />);
    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
    unmount();
    state.waiting = {
      agents: [{ agent_id: "a1", name: "Clerk", instructions: 0, tools: 1 }],
      skills: 0,
    };
    widget();
    expect(screen.getByText(/1 tool change/)).toBeInTheDocument();
  });

  it("loads, and offers a retry when the read failed", async () => {
    state.isLoading = true;
    const { unmount } = render(<SuggestionsWidget title="t" hint="" period={PERIOD} />);
    unmount();
    state.isLoading = false;
    state.error = new Error("boom");
    widget();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalled();
  });
});
