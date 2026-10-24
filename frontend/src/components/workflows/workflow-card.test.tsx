import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
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
    live_trigger: "core.input",
    tags: [],
    trigger_active: null,
    draft_revision: 3,
    entry_node: "trigger.webhook",
    step_count: 3,
    last_run: null,
    created_at: null,
    updated_at: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}

type CardProps = ComponentProps<typeof WorkflowCard>;

function card(overrides: Partial<CardProps> = {}) {
  const props: CardProps = {
    workflow: workflow(),
    startsFrom: "Webhook",
    canCreate: true,
    canEdit: false,
    onDuplicate: vi.fn(),
    onArchive: vi.fn(),
    onRestore: vi.fn(),
    onDelete: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<WorkflowCard {...props} />);
  return props;
}

describe("WorkflowCard", () => {
  it("shows a live workflow, what starts it, its size and who may reach it", () => {
    card();
    expect(screen.getByText("Lead follow-up")).toBeTruthy();
    expect(screen.getByText("Webhook · 3 steps")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Organization" })).toBeTruthy();
    expect(screen.getByText("Scores new leads")).toBeTruthy();
    expect(screen.getByText(/^Not run yet · edited/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Runs of Lead follow-up" })).toHaveAttribute(
      "href",
      "/workflows/wf/runs",
    );
  });

  it("says how its last run went instead of when it was edited", () => {
    card({
      workflow: workflow({
        last_run: {
          id: "r1",
          status: "failed",
          mode: "real",
          created_at: new Date().toISOString(),
        },
      }),
    });
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("just now")).toBeTruthy();
    expect(screen.queryByText(/edited/)).toBeNull();
  });

  it("counts the steps of a draft whose first step is not yet known", () => {
    card({
      startsFrom: null,
      workflow: workflow({
        entry_node: null,
        step_count: 0,
        current_version_id: null,
        last_run: { id: "r1", status: "queued", mode: "test", created_at: null },
      }),
    });
    expect(screen.getByText("No steps yet")).toBeTruthy();
    expect(screen.getByText("Draft")).toBeTruthy();
    expect(screen.getByText("Queued")).toBeTruthy();
  });

  it("duplicates on request", async () => {
    const props = card();
    await userEvent.click(screen.getByRole("button", { name: /Duplicate/ }));
    expect(props.onDuplicate).toHaveBeenCalled();
  });

  it("shows an unpublished private draft without a way to copy it", () => {
    card({
      workflow: workflow({
        status: "archived",
        visibility: "somewhere",
        current_version_id: null,
        description: null,
        updated_at: null,
      }),
      canCreate: false,
      busy: true,
    });
    expect(screen.getByRole("img", { name: "Private" })).toBeTruthy();
    expect(screen.getByText("Archived")).toBeTruthy();
    // No description, and none said to be missing.
    expect(screen.queryByText("No description yet.")).toBeNull();
    expect(screen.getByText("Not run yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Duplicate/ })).toBeNull();
  });

  it("shows its tags and whether its trigger is on", () => {
    card({ workflow: workflow({ tags: ["sales"], trigger_active: true }) });
    expect(screen.getByText("sales")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
  });

  it("says a paused trigger is paused, and says nothing of one on an archived workflow", () => {
    card({ workflow: workflow({ trigger_active: false }) });
    expect(screen.getByText("Paused")).toBeTruthy();
  });

  it("offers no management menu without the role to edit", () => {
    card();
    expect(screen.queryByRole("button", { name: "More for Lead follow-up" })).toBeNull();
  });

  it("archives a live workflow from its menu", async () => {
    const user = userEvent.setup();
    const props = card({ canEdit: true, workflow: workflow({ trigger_active: false }) });

    await user.click(screen.getByRole("button", { name: "More for Lead follow-up" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));

    expect(props.onArchive).toHaveBeenCalled();
  });

  it("restores an archived workflow, or deletes it after asking", async () => {
    const user = userEvent.setup();
    const props = card({
      canEdit: true,
      workflow: workflow({ status: "archived", trigger_active: false }),
    });
    expect(screen.queryByText("Paused")).toBeNull();

    await user.click(screen.getByRole("button", { name: "More for Lead follow-up" }));
    await user.click(screen.getByRole("menuitem", { name: "Restore" }));
    expect(props.onRestore).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "More for Lead follow-up" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(screen.getByText("Delete Lead follow-up?")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(props.onDelete).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Delete Lead follow-up?")).toBeNull());
  });

  it("closes the question when a delete is refused", async () => {
    const user = userEvent.setup();
    card({
      canEdit: true,
      workflow: workflow({ status: "archived" }),
      onDelete: vi.fn().mockRejectedValue(new Error("in use")),
    });

    await user.click(screen.getByRole("button", { name: "More for Lead follow-up" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("Delete Lead follow-up?")).toBeNull());
  });
});
