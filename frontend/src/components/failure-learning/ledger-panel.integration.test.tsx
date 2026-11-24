import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LedgerEntryDetail } from "./ledger-entry-detail";
import { LedgerPanel } from "./ledger-panel";
import type { LedgerEntryRead } from "@/lib/failure-learning-api";

const entry = (overrides: Partial<LedgerEntryRead> = {}): LedgerEntryRead => ({
  id: "entry-1",
  organization_id: "org-1",
  agent_id: "agent-1",
  scope: "agent",
  model: null,
  pattern_key: "failed:ModelHTTPError:400",
  title: "Bad requests",
  summary: "The agent keeps sending bad requests.",
  evidence: { count: 4, error_class: "ModelHTTPError:400" },
  status: "draft",
  created_by_user_id: null,
  eval_case_count: 2,
  proposal_count: 1,
  open_since: null,
  created_at: "2026-11-09T00:00:00Z",
  updated_at: "2026-11-09T00:00:00Z",
  ...overrides,
});

describe("LedgerPanel", () => {
  it("lists entries with their case and proposal counts", () => {
    render(
      <LedgerPanel
        entries={[entry()]}
        isLoading={false}
        error={null}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Bad requests")).toBeInTheDocument();
    expect(screen.getByText(/2 eval cases/)).toBeInTheDocument();
    expect(screen.getByText(/1 proposal/)).toBeInTheDocument();
  });

  it("filters by status, and selects a row on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <LedgerPanel
        entries={[entry(), entry({ id: "entry-2", status: "open", title: "Stalled runs" })]}
        isLoading={false}
        error={null}
        selectedId={null}
        onSelect={onSelect}
      />,
    );

    await user.click(screen.getByText("Stalled runs"));
    expect(onSelect).toHaveBeenCalledWith("entry-2");
  });

  it("says when the ledger is empty", () => {
    render(
      <LedgerPanel
        entries={[]}
        isLoading={false}
        error={null}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText(/No ledger entries yet/)).toBeInTheDocument();
  });
});

describe("LedgerEntryDetail", () => {
  it("accepts a draft, and hides the accept control once open", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <LedgerEntryDetail entry={entry()} canEdit={true} onUpdate={onUpdate} onDelete={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Accept" }));
    expect(onUpdate).toHaveBeenCalledWith("entry-1", { status: "open" });
  });

  it("dismisses with a reason, appended to the summary so the record survives", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <LedgerEntryDetail entry={entry()} canEdit={true} onUpdate={onUpdate} onDelete={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await user.type(
      screen.getByLabelText("Why this is not a real pattern"),
      "three different bugs",
    );
    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(onUpdate).toHaveBeenCalledWith(
      "entry-1",
      expect.objectContaining({
        status: "dismissed",
        summary: expect.stringContaining("three different bugs"),
      }),
    );
    expect(onUpdate.mock.calls[0]?.[1]?.summary).toContain("The agent keeps sending bad requests.");
  });

  it("deletes only on the second click", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(
      <LedgerEntryDetail entry={entry()} canEdit={true} onUpdate={vi.fn()} onDelete={onDelete} />,
    );

    await user.click(screen.getByRole("button", { name: "Delete entry" }));
    expect(onDelete).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete this entry?" }));
    expect(onDelete).toHaveBeenCalledWith("entry-1");
  });

  it("hides every curation control from a caller who may not edit", () => {
    render(
      <LedgerEntryDetail entry={entry()} canEdit={false} onUpdate={vi.fn()} onDelete={vi.fn()} />,
    );

    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete entry" })).not.toBeInTheDocument();
  });
});
