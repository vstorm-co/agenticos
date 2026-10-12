import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CardDescription } from "./card";

afterEach(() => vi.restoreAllMocks());

/** jsdom lays nothing out, so a description is as tall as these say. */
function measured(scrollHeight: number, clientHeight: number) {
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(scrollHeight);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(clientHeight);
}

describe("CardDescription", () => {
  it("draws a short description as it always did, with no toggle", () => {
    measured(40, 40);
    render(<CardDescription>What this agent can do.</CardDescription>);

    expect(screen.getByText("What this agent can do.")).toHaveClass("line-clamp-1");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("folds a long one to a line and opens the rest on More", async () => {
    measured(120, 40);
    render(<CardDescription>A paragraph that runs well past one line.</CardDescription>);
    const text = screen.getByText("A paragraph that runs well past one line.");

    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(text).not.toHaveClass("line-clamp-1");

    await userEvent.click(screen.getByRole("button", { name: "Less" }));
    expect(text).toHaveClass("line-clamp-1");
  });
});
