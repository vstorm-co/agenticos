import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/types/agents";
import { NewEventTriggerDialog } from "./new-event-trigger-dialog";

let can: (permission: string) => boolean = () => true;
let canCreate = true;
let agents: Pick<Agent, "status" | "can_run" | "can_edit">[] = [];

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can, isLoading: false }),
  useCanCreateTrigger: () => canCreate,
  useAgents: () => ({ agents }),
}));
vi.mock("./trigger-form-dialog", () => ({
  TriggerFormDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <button type="button" onClick={() => onOpenChange(false)}>
      Close source routine
    </button>
  ),
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
  agents = [];
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
    // still be told it may create. Connecting is gated on `mcp:manage` - the
    // permission the org MCP-connection routes those buttons invoke require -
    // and `connections:manage` alone must NOT light the connect actions, or a
    // custom role holding only it would be offered buttons that always 403.
    can = (permission) => permission === "mcp:manage";
    canCreate = true;
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    const grid = screen.getByTestId("portal-catalog");
    expect(grid.getAttribute("data-can-run")).toBe("true");
    expect(grid.getAttribute("data-can-connect")).toBe("true");
  });

  it("does not offer connect on connections:manage alone", () => {
    // The two permissions are independent and the routes behind Connect and
    // Re-authorize require mcp:manage; a caller holding only connections:manage
    // must not be shown controls the backend will refuse.
    can = (permission) => permission === "connections:manage";
    canCreate = true;
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);

    expect(screen.getByTestId("portal-catalog").getAttribute("data-can-connect")).toBe("false");
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

  it("keeps existing trigger creation available without an editable agent", () => {
    agents = [{ status: "published", can_run: true, can_edit: false }];
    render(<NewEventTriggerDialog open onOpenChange={vi.fn()} />);
    expect(screen.getByTestId("portal-catalog")).toHaveAttribute("data-can-run", "true");
    expect(
      screen.queryByRole("button", { name: "Create routine from an event source" }),
    ).toBeNull();
  });

  it("opens source routine setup for an eligible agent and returns to the catalog on close", async () => {
    agents = [{ status: "published", can_run: true, can_edit: true }];
    const onOpenChange = vi.fn();
    render(<NewEventTriggerDialog open onOpenChange={onOpenChange} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Create routine from an event source" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Close source routine" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByTestId("portal-catalog")).toBeVisible();
  });
});
