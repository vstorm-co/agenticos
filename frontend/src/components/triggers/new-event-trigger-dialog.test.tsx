import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewEventTriggerDialog } from "./new-event-trigger-dialog";

let can: (permission: string) => boolean = () => true;

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can, isLoading: false }),
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

  it("passes the caller's create and connect permissions down to the grid", () => {
    can = (permission) => permission === "agents:run";
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    const grid = screen.getByTestId("portal-catalog");
    expect(grid.getAttribute("data-can-run")).toBe("true");
    expect(grid.getAttribute("data-can-connect")).toBe("false");
  });
});
