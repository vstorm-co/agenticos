import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuggestionsWidget } from "./suggestions";

/**
 * What the nightly look proposed, on the dashboard (#2301): the chat's own
 * cards when there are some, and why there are none when there are not.
 */

const state = vi.hoisted(() => ({
  suggestions: [] as { id: string }[],
  orgOn: false,
}));

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({ activeOrg: { proactive_enabled: state.orgOn } }),
}));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({ suggestions: state.suggestions }),
}));
vi.mock("@/components/chat/suggestion-cards", () => ({
  SuggestionCards: ({ agentId }: { agentId: string | null }) => (
    <div data-testid="cards" data-agent={agentId ?? ""} />
  ),
}));
vi.mock("../widget-frame", () => ({
  WidgetFrame: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section aria-label={title}>{children}</section>
  ),
}));

const props = {
  title: "Suggestions for you",
  hint: "",
  period: "30d",
} as unknown as Parameters<typeof SuggestionsWidget>[0];

beforeEach(() => {
  state.suggestions = [];
  state.orgOn = false;
});

describe("SuggestionsWidget", () => {
  it("shows the chat's own cards, for any agent the person picks", () => {
    state.suggestions = [{ id: "s1" }];
    render(<SuggestionsWidget {...props} />);

    expect(screen.getByTestId("cards")).toHaveAttribute("data-agent", "");
  });

  it("says the organization has it off, when it does", () => {
    render(<SuggestionsWidget {...props} />);
    expect(screen.getByText("Your organization has nightly suggestions off.")).toBeInTheDocument();
  });

  it("says when to expect some, where the organization has it on", () => {
    state.orgOn = true;
    render(<SuggestionsWidget {...props} />);
    expect(
      screen.getByText("Suggestions appear here after the nightly look at your week."),
    ).toBeInTheDocument();
  });
});
