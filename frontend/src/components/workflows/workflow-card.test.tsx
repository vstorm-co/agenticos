import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowRead } from "@/lib/workflows/types";

import { WorkflowCard } from "./workflow-card";

function workflow(overrides: Partial<WorkflowRead> = {}): WorkflowRead {
  return {
    id: "wf",
    slug: "lead-follow-up",
    name: "Lead follow-up",
    description: "Scores new leads",
    status: "published",
    visibility: "org",
    owner_user_id: null,
    current_version_id: "v1",
    draft_revision: 3,
    created_at: null,
    updated_at: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}

describe("WorkflowCard", () => {
  it("shows a published workflow, who may reach it and that it has a live version", () => {
    render(<WorkflowCard workflow={workflow()} canCreate onDuplicate={vi.fn()} />);
    expect(screen.getByText("Lead follow-up")).toBeTruthy();
    expect(screen.getByText("Organization")).toBeTruthy();
    expect(screen.getByText("Live version")).toBeTruthy();
    expect(screen.getByText(/edited/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Runs of Lead follow-up" })).toHaveAttribute(
      "href",
      "/workflows/wf/runs",
    );
  });

  it("duplicates on request", async () => {
    const onDuplicate = vi.fn();
    render(<WorkflowCard workflow={workflow()} canCreate onDuplicate={onDuplicate} />);
    await userEvent.click(screen.getByRole("button", { name: /Duplicate/ }));
    expect(onDuplicate).toHaveBeenCalled();
  });

  it("shows an unpublished private draft without a way to copy it", () => {
    render(
      <WorkflowCard
        workflow={workflow({
          status: "archived",
          visibility: "somewhere",
          current_version_id: null,
          description: null,
          updated_at: null,
        })}
        canCreate={false}
        busy
        onDuplicate={vi.fn()}
      />,
    );
    expect(screen.getByText("Private")).toBeTruthy();
    expect(screen.getByText("Not published")).toBeTruthy();
    expect(screen.getByText("No description yet.")).toBeTruthy();
    expect(screen.getByText("Draft revision 3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Duplicate/ })).toBeNull();
  });
});
