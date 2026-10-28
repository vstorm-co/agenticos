import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuggestionsWidget } from "./suggestions";

/**
 * The briefing on the dashboard (#2301): what cannot wait first, a few cards and
 * the rest a link away in the inbox, and why there are none when there are not.
 */

const state = vi.hoisted(() => ({
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  suggestions: [] as { id: string; urgent?: boolean }[],
  org: {} as { proactive_enabled?: boolean; proactive_watches_enabled?: boolean },
  shown: [] as { id: string }[],
}));

vi.mock("@/hooks", () => ({ useOrganizations: () => ({ activeOrg: state.org }) }));
vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({
    suggestions: state.suggestions,
    isLoading: state.isLoading,
    error: state.error,
    refetch: state.refetch,
  }),
}));
vi.mock("@/components/inbox/suggestion-rows", () => ({
  SuggestionRows: ({ items, dense }: { items: { id: string }[]; dense?: boolean }) => {
    state.shown = items;
    return <div data-testid="rows" data-dense={String(dense)} />;
  },
}));
vi.mock("../widget-frame", () => ({
  WidgetFrame: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section aria-label={title}>{children}</section>
  ),
}));

const props = {
  title: "Briefing",
  hint: "",
  period: "30d",
} as unknown as Parameters<typeof SuggestionsWidget>[0];

beforeEach(() => {
  state.suggestions = [];
  state.isLoading = false;
  state.error = null;
  state.refetch.mockReset();
  state.org = {};
  state.shown = [];
});

describe("SuggestionsWidget", () => {
  it("waits for the briefing instead of reporting no proposals", () => {
    state.isLoading = true;
    render(<SuggestionsWidget {...props} />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("Nothing proposed yet")).not.toBeInTheDocument();
  });

  it("keeps a failed briefing distinct from an empty one and can retry", () => {
    state.error = new Error("offline");
    render(<SuggestionsWidget {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalledOnce();
    expect(screen.queryByText("Nothing proposed yet")).not.toBeInTheDocument();
  });

  it("shows the inbox's own rows, tightened", () => {
    state.suggestions = [{ id: "s1" }];
    render(<SuggestionsWidget {...props} />);

    expect(screen.getByTestId("rows")).toHaveAttribute("data-dense", "true");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("leads with what cannot wait and leaves the rest to the inbox", () => {
    state.suggestions = [
      { id: "a" },
      { id: "b" },
      { id: "c" },
      { id: "d" },
      { id: "e", urgent: true },
      { id: "f" },
    ];
    render(<SuggestionsWidget {...props} />);

    expect(state.shown.map((item) => item.id)).toEqual(["e", "a", "b", "c"]);
    expect(screen.getByRole("link", { name: "2 more in your inbox" })).toHaveAttribute(
      "href",
      "/inbox",
    );
  });

  it("says the organization has it off, when it does", () => {
    render(<SuggestionsWidget {...props} />);
    expect(screen.getByText("Your organization has proactivity off.")).toBeInTheDocument();
  });

  it.each([{ proactive_enabled: true }, { proactive_watches_enabled: true }])(
    "says what will arrive, where either kind is on (%o)",
    (org) => {
      state.org = org;
      render(<SuggestionsWidget {...props} />);
      expect(
        screen.getByText("Findings from your watches and the nightly suggestions appear here."),
      ).toBeInTheDocument();
    },
  );
});
