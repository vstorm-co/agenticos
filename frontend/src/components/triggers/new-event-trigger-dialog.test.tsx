import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewEventTriggerDialog } from "./new-event-trigger-dialog";

let can: (permission: string) => boolean = () => true;
let canCreate = true;

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can, isLoading: false }),
  useCanCreateTrigger: () => canCreate,
}));

// The grid's own behaviour is covered by the portal tests; here it is stubbed so
// the dialog's job - resolving the two permissions and handing them down - is what
// this suite checks.
vi.mock("@/components/triggers/portal-catalog", () => ({
  PortalCatalog: ({
    canRun,
    canManageConnections,
  }: {
    canRun: boolean;
    canManageConnections: boolean;
  }) => (
    <div
      data-testid="portal-catalog"
      data-can-run={canRun}
      data-can-connect={canManageConnections}
    />
  ),
}));

beforeEach(() => {
  can = () => true;
  canCreate = true;
});

describe("NewEventTriggerDialog", () => {
  it("shows the portal grid under a titled dialog when open", () => {
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "New event trigger" })).toBeInTheDocument();
    expect(screen.getByTestId("portal-catalog")).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    render(<NewEventTriggerDialog open={false} onOpenChange={vi.fn()} />);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("takes create-ability from the per-agent floor, not the org-level agents:run", () => {
    // A Viewer whose role reaches no agent but who holds a run grant on one:
    // `agents:run` is false, `useCanCreateTrigger` is true, so the grid must
    // still be told it may create. Connecting stays a separate org permission.
    can = (permission) => permission === "connections:manage";
    canCreate = true;
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    const grid = screen.getByTestId("portal-catalog");
    expect(grid.getAttribute("data-can-run")).toBe("true");
    expect(grid.getAttribute("data-can-connect")).toBe("true");
  });

  it("withholds create-ability when no agent is runnable, whatever the org role says", () => {
    // `agents:run` true here, but the per-agent floor is what decides: with no
    // runnable agent the create actions stay hidden rather than 403 on use.
    can = () => true;
    canCreate = false;
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    const grid = screen.getByTestId("portal-catalog");
    expect(grid.getAttribute("data-can-run")).toBe("false");
    expect(grid.getAttribute("data-can-connect")).toBe("true");
  });
});
