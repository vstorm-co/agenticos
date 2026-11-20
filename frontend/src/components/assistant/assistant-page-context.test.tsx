import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AssistantPageContextBar } from "./assistant-page-context";

const page = {
  path: "/apps/scheduler",
  title: "Scheduler",
  captured_at: "2026-01-01T00:00:00.000Z",
  resource: { kind: "app", id: "scheduler", title: "Scheduling" },
  view: "Week",
  filters: { date: "2026-01-01" },
  selected_ids: ["job-1"],
  summary: "One selected job is unassigned.",
};

describe("the floating assistant's page context", () => {
  it("lets the reader inspect the actual registered context and stop sharing it", () => {
    const change = vi.fn();
    const { rerender } = render(
      <AssistantPageContextBar page={page} enabled onEnabledChange={change} />,
    );
    const toggle = screen.getByRole("switch", { name: "Use the current page" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "View context" }));
    expect(screen.getByText("/apps/scheduler")).toBeVisible();
    expect(screen.getByText("job-1")).toBeVisible();
    expect(screen.getByText("One selected job is unassigned.")).toBeVisible();
    fireEvent.click(toggle);
    expect(change).toHaveBeenCalledWith(false);

    rerender(<AssistantPageContextBar page={page} enabled={false} onEnabledChange={change} />);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Page context is off")).toBeVisible();
    fireEvent.click(toggle);
    expect(change).toHaveBeenLastCalledWith(true);
  });

  it("updates the displayed page when navigation changes the context", () => {
    const { rerender } = render(
      <AssistantPageContextBar page={page} enabled onEnabledChange={vi.fn()} />,
    );
    expect(screen.getByText("Using: Scheduling")).toBeVisible();
    rerender(
      <AssistantPageContextBar
        page={{ path: "/runs", title: "Runs", captured_at: page.captured_at }}
        enabled
        onEnabledChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Using: Runs")).toBeVisible();
    expect(screen.queryByText("Using: Scheduling")).not.toBeInTheDocument();
  });
});
