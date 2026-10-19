import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProblemBadge } from "./problem-badge";

const FIVE = ["Model: Required.", "Prompt: Required.", "Not connected yet", "Fourth", "Fifth"];

describe("ProblemBadge", () => {
  it("spells out the first three problems on hover and counts the rest", async () => {
    render(<ProblemBadge problems={FIVE} onOpen={vi.fn()} />);
    await userEvent.hover(screen.getByRole("button", { name: "5 problems" }));

    expect((await screen.findAllByText("Model: Required.")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not connected yet").length).toBeGreaterThan(0);
    expect(screen.queryByText("Fourth")).toBeNull();
    expect(screen.getAllByText("2 more problems. Click to see them all.").length).toBeGreaterThan(
      0,
    );
  });

  it("says a click opens the step when nothing is left out, and opens it", async () => {
    const onOpen = vi.fn();
    render(<ProblemBadge problems={["Not connected yet"]} onOpen={onOpen} />);
    const badge = screen.getByRole("button", { name: "1 problem" });
    await userEvent.hover(badge);
    expect((await screen.findAllByText("Click to open the step.")).length).toBeGreaterThan(0);

    await userEvent.click(badge);
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
