import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetupProposals } from "./setup-proposals";
import type { SetupProposal } from "@/lib/turn-extras";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";

/**
 * What a welcome interview ends with (#2301): each proposal a card acted on in
 * one click - a routine dialog filled in, a question to the Architect, the MCP
 * servers page at its add button.
 */

const push = vi.hoisted(() => vi.fn());
const pointAt = vi.hoisted(() => vi.fn());
const dialogs = vi.hoisted(() => [] as { agentId: string | null; template?: TriggerTemplate }[]);

const servers = vi.hoisted(() => ({
  entry: null as { key: string; name: string; icon: string | null; url: string } | null,
  isLoading: false,
  connections: [] as { catalog_key: string; is_enabled: boolean; authorized: boolean }[],
  connectedWith: [] as { entry: { key: string }; returnTo?: string }[],
}));

vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/use-mcp-servers", () => ({
  useMcpServerEntry: () => ({ entry: servers.entry, isLoading: servers.isLoading }),
}));
vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ connections: servers.connections }),
}));
vi.mock("@/components/agents/connect-server-dialog", () => ({
  ConnectOwnButton: (props: { entry: { key: string }; label: string; returnTo?: string }) => (
    <button type="button" onClick={() => servers.connectedWith.push(props)}>
      {props.label}
    </button>
  ),
}));
vi.mock("@/lib/assistant-highlight", () => ({ pointAt }));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({
    agentId,
    initialTemplate,
    onOpenChange,
  }: {
    agentId: string | null;
    initialTemplate?: TriggerTemplate;
    onOpenChange: (open: boolean) => void;
  }) => {
    dialogs.push({ agentId, template: initialTemplate });
    return (
      <div role="dialog">
        <button type="button" onClick={() => onOpenChange(false)}>
          close
        </button>
      </div>
    );
  },
}));

function proposal(overrides: Partial<SetupProposal>): SetupProposal {
  return {
    key: "p-0",
    kind: "routine",
    title: "Monday digest",
    why: "You read tickets every Monday",
    request: "Summarise last week's tickets",
    cron: null,
    server: null,
    ...overrides,
  };
}

function take(title: string) {
  const card = screen.getByRole("group", { name: title });
  return userEvent.click(within(card).getByRole("button"));
}

beforeEach(() => {
  push.mockReset();
  pointAt.mockReset();
  dialogs.length = 0;
  useArchitectAskStore.setState({ request: null });
  servers.entry = null;
  servers.isLoading = false;
  servers.connections = [];
  servers.connectedWith = [];
});

describe("SetupProposals", () => {
  it("draws a card per proposal, with what it would do", () => {
    render(
      <SetupProposals
        agentId="a-1"
        proposals={[
          proposal({ key: "p-0" }),
          proposal({ key: "p-1", kind: "agent", title: "Ticket helper" }),
          proposal({ key: "p-2", kind: "connection", title: "Connect Gmail" }),
        ]}
      />,
    );

    expect(screen.getAllByRole("group")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Set it up" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build it with the Architect" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect it" })).toBeInTheDocument();
  });

  it("opens the routine dialog filled in, on the agent that proposed it", async () => {
    render(<SetupProposals agentId="a-1" proposals={[proposal({ cron: "0 7 * * 1-5" })]} />);

    await take("Monday digest");

    expect(dialogs.at(-1)).toMatchObject({
      agentId: "a-1",
      template: {
        label: "Monday digest",
        prompt: "Summarise last week's tickets",
        trigger_type: "schedule",
        suggested_cadence: { schedule_kind: "cron", cron_expression: "0 7 * * 1-5" },
      },
    });
  });

  it("runs a routine proposed without a cadence weekly, and closes the dialog", async () => {
    render(<SetupProposals agentId={null} proposals={[proposal({})]} />);

    await take("Monday digest");
    expect(dialogs.at(-1)?.template?.suggested_cadence).toEqual({
      schedule_kind: "cron",
      cron_expression: "0 8 * * 1",
    });

    await userEvent.click(screen.getByRole("button", { name: "close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks the Architect to build a proposed agent", async () => {
    render(
      <SetupProposals
        agentId="a-1"
        proposals={[proposal({ kind: "agent", title: "Ticket helper", request: "Triage tickets" })]}
      />,
    );

    await take("Ticket helper");

    expect(useArchitectAskStore.getState().request?.text).toContain("Triage tickets");
    expect(dialogs).toHaveLength(0);
  });

  it("opens the MCP servers page at its add button for a connection", async () => {
    render(
      <SetupProposals
        agentId="a-1"
        proposals={[proposal({ kind: "connection", title: "Connect Gmail", request: "Gmail" })]}
      />,
    );

    await take("Connect Gmail");

    expect(push).toHaveBeenCalledWith("/mcp-servers");
    expect(pointAt).toHaveBeenCalledWith("mcp-add");
  });

  describe("a connection naming its server", () => {
    const GMAIL = {
      key: "com.mintmcp/gmail",
      name: "com.mintmcp/gmail",
      icon: null,
      url: "https://gmail.mintmcp.com/mcp",
    };
    const gmail = () =>
      proposal({
        kind: "connection",
        title: "Connect Gmail",
        request: "Gmail",
        server: GMAIL.key,
      });

    it("connects that service from the card, and comes back to this conversation", async () => {
      servers.entry = GMAIL;
      window.history.replaceState({}, "", "/chat?id=c-1");
      render(<SetupProposals agentId="a-1" proposals={[gmail()]} />);

      await take("Connect Gmail");

      expect(servers.connectedWith).toEqual([
        expect.objectContaining({ entry: GMAIL, returnTo: "/chat?id=c-1" }),
      ]);
      expect(push).not.toHaveBeenCalled();
    });

    it("leaves the conversation once the person's own account is on it", () => {
      servers.entry = GMAIL;
      servers.connections = [{ catalog_key: GMAIL.key, is_enabled: true, authorized: true }];
      render(<SetupProposals agentId="a-1" proposals={[gmail(), proposal({ key: "p-1" })]} />);

      expect(screen.queryByRole("group", { name: "Connect Gmail" })).toBeNull();
      expect(screen.getByRole("group", { name: "Monday digest" })).toBeInTheDocument();
    });

    it("waits, unclickable, while the server is looked up", () => {
      servers.isLoading = true;
      render(<SetupProposals agentId="a-1" proposals={[gmail()]} />);

      expect(screen.getByRole("button", { name: "Connect it" })).toBeDisabled();
    });

    it("falls back to the MCP servers page for a key nothing knows", async () => {
      render(<SetupProposals agentId="a-1" proposals={[gmail()]} />);

      await take("Connect Gmail");

      expect(push).toHaveBeenCalledWith("/mcp-servers");
    });
  });
});
