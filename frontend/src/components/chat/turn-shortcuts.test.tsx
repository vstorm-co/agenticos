import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TurnShortcuts } from "./turn-shortcuts";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";
import { Perm, type Permission } from "@/types/permissions";

/**
 * Keeping a request that worked (#2301): a routine made from it, or the
 * Architect asked to make an agent of it - each offered only to somebody who
 * may do it.
 */

const state = vi.hoisted(() => ({
  held: [] as string[],
  assistant: null as { status: string; can_use: boolean } | null,
  dialogs: [] as { agentId: string | null; template?: TriggerTemplate }[],
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.held.includes(permission) }),
}));
vi.mock("@/hooks/use-assistant", () => ({ useAssistant: () => ({ assistant: state.assistant }) }));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({
    agentId,
    initialTemplate,
  }: {
    agentId: string | null;
    initialTemplate?: TriggerTemplate;
  }) => {
    state.dialogs.push({ agentId, template: initialTemplate });
    return <div role="dialog" />;
  },
}));

const REQUEST = "Summarise yesterday's support tickets";

beforeEach(() => {
  state.held = [Perm.agentsRun, Perm.agentsEdit];
  state.assistant = { status: "ready", can_use: true };
  state.dialogs = [];
  useArchitectAskStore.setState({ request: null });
});

describe("TurnShortcuts", () => {
  it("opens a routine made of the request, weekly and on the agent that answered", async () => {
    render(<TurnShortcuts request={REQUEST} agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Run this on a schedule" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const { agentId, template } = state.dialogs.at(-1)!;
    expect(agentId).toBe("a-1");
    expect(template).toMatchObject({
      prompt: REQUEST,
      trigger_type: "schedule",
      suggested_cadence: { schedule_kind: "cron", cron_expression: "0 8 * * 1" },
    });
  });

  it("asks the Architect to make an agent of the request", async () => {
    render(<TurnShortcuts request={REQUEST} agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Make an agent of this" }));

    expect(useArchitectAskStore.getState().request?.text).toContain(REQUEST);
  });

  it("offers neither to somebody who may not run or edit agents", () => {
    state.held = [];
    render(<TurnShortcuts request={REQUEST} agentId={null} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers no agent while the Architect is not there to ask", () => {
    state.assistant = { status: "ready", can_use: false };
    const { rerender } = render(<TurnShortcuts request={REQUEST} agentId="a-1" />);
    expect(screen.queryByRole("button", { name: "Make an agent of this" })).not.toBeInTheDocument();

    state.assistant = null;
    rerender(<TurnShortcuts request={REQUEST} agentId="a-1" />);
    expect(screen.queryByRole("button", { name: "Make an agent of this" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run this on a schedule" })).toBeVisible();
  });
});
