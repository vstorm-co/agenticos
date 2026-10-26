import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantState } from "@/types/assistant";

import { AssistantSettings } from "./assistant-settings";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  isLoading: false,
  error: null as Error | null,
  retry: vi.fn(),
  orgId: "o1" as string | null,
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({
    assistant: state.assistant,
    isLoading: state.isLoading,
    error: state.error,
    retry: state.retry,
  }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (pick: (store: { activeOrgId: string | null }) => unknown) =>
    pick({ activeOrgId: state.orgId }),
}));
// The person's suggestions are tested on their own; here only that they are offered.
vi.mock("./your-suggestions", () => ({
  YourSuggestions: () => <section aria-label="Suggestions for you" />,
}));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "ready",
    agent_id: "a1",
    slug: "ai-architect",
    name: "Architect",
    named_by_default: true,
    greeting: null,
    avatar_url: null,
    wears_mark: true,
    avatar_color: null,
    can_use: true,
    can_configure: true,
    ...overrides,
  };
}

beforeEach(() => {
  state.assistant = assistant();
  state.isLoading = false;
  state.error = null;
  state.retry.mockReset();
  state.orgId = "o1";
});

afterEach(() => localStorage.clear());

describe("Settings → Assistant", () => {
  it("keeps the actual sections mounted while their controls wait for the assistant", () => {
    state.isLoading = true;
    const { container, rerender } = render(<AssistantSettings />);
    const cards = Array.from(container.querySelectorAll(".shadow-card"));
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    state.isLoading = false;
    rerender(<AssistantSettings />);
    expect(Array.from(container.querySelectorAll(".shadow-card"))).toEqual(cards);
    expect(container.querySelector("[inert]")).toBeNull();
  });

  it("says why the assistant could not be read, and offers to try again", () => {
    state.assistant = null;
    state.error = new Error("The assistant could not be installed");
    render(<AssistantSettings />);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(state.retry).toHaveBeenCalledOnce();
    expect(screen.queryByText("Your tips")).toBeNull();
  });

  it("draws nothing when there is no assistant to read", () => {
    state.assistant = null;
    const { container } = render(<AssistantSettings />);

    expect(container).toBeEmptyDOMElement();
  });

  it("tells somebody without agents:run why there is no assistant, and nothing more", () => {
    state.assistant = assistant({ can_use: false, can_configure: false });
    render(<AssistantSettings />);

    expect(screen.getByText(/Your role doesn't include running agents/)).toBeInTheDocument();
    expect(screen.queryByText("Your tips")).toBeNull();
    expect(screen.queryByText("For the organization")).toBeNull();
  });

  it("lets a member switch their tips off and bring silenced pages back", () => {
    state.assistant = assistant({ can_configure: false });
    localStorage.setItem(
      "assistant-bubbles",
      JSON.stringify({ silenced: ["/agents"], off: false }),
    );
    render(<AssistantSettings />);

    expect(screen.queryByText("For the organization")).toBeNull();
    // Watches are managed under Routines; this page only points there.
    expect(screen.getByRole("link", { name: "Manage your watches in Routines" })).toHaveAttribute(
      "href",
      "/routines",
    );
    fireEvent.click(screen.getByRole("switch", { name: "Show tips in speech bubbles" }));
    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toMatchObject({ off: true });

    fireEvent.click(
      screen.getByRole("button", { name: "Show tips again on the 1 page I silenced" }),
    );
    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toMatchObject({
      silenced: [],
      off: true,
    });
    expect(screen.queryByRole("button", { name: /Show tips again/ })).toBeNull();
  });

  it("points an administrator at the Builder and the organization's page, and edits nothing here", () => {
    render(<AssistantSettings />);

    expect(screen.getByRole("link", { name: "Open in Agent Builder" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
    expect(screen.getByRole("link", { name: "Organization settings" })).toHaveAttribute(
      "href",
      "/orgs/o1/members",
    );
    // Kacper on #2062: the Architect is an agent like any other, so nothing of
    // the agent's is set from a person's own settings.
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("switch", { name: /switched on/ })).toBeNull();
  });
});
