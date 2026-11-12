import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { skillSession } from "@/test-utils/skill-improvement";
import { ForkedSummary } from "./forked-summary";

const forked = (moved: string[], drafts: string[]) => ({
  session: skillSession(),
  fork: { id: "f9", name: "Returns" },
  moved: moved.map((name) => ({ id: name, name })),
  draft_only: drafts.map((name) => ({ id: name, name })),
});

describe("ForkedSummary", () => {
  it("says who moved onto the fork at once and who only in a draft", () => {
    render(<ForkedSummary forked={forked(["Support"], ["Refunds", "Desk"])} />);

    expect(screen.getByRole("status", { name: "What forking did" })).toBeVisible();
    expect(screen.getByText("The change is now the fork “Returns”.")).toBeVisible();
    expect(screen.getByText("Moved onto it and published: Support.")).toBeVisible();
    expect(
      screen.getByText(
        "Moved onto it in their drafts, which wait to be published: Refunds and Desk.",
      ),
    ).toBeVisible();
  });

  it("says when nobody moved onto it", () => {
    render(<ForkedSummary forked={forked([], [])} />);
    expect(screen.getByText(/No agent was moved onto it/)).toBeVisible();
  });
});
