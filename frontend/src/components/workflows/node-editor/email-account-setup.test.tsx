import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeDefinition } from "@/components/workflows/validation/fixtures";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { EmailAccountSetup } from "./email-account-setup";
const state = vi.hoisted(() => ({
  canConnect: true,
  connections: [] as Record<string, unknown>[],
}));
vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => ({ ...state, servers: [] }),
}));
vi.mock("@/components/workflows/pickers/workflow-connections-dialog", () => ({
  WorkflowConnectionsDialog: ({
    catalogKey,
    onOpenChange,
  }: {
    catalogKey?: string;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <p>Setup {catalogKey}</p>
      <button onClick={() => onOpenChange(false)}>Close setup</button>
    </div>
  ),
}));
vi.mock("@/components/workflows/pickers/secret-picker", () => ({
  SecretPicker: ({
    onChange,
    disabled,
  }: {
    onChange: (id: string | null) => void;
    disabled?: boolean;
  }) => (
    <button disabled={disabled} onClick={() => onChange("smtp-id")}>
      Choose SMTP
    </button>
  ),
}));
afterEach(() => {
  state.connections = [];
  state.canConnect = true;
  useWorkflowEditorStore.getState().teardown();
});
describe("email account setup", () => {
  it("opens the mailbox connection flow without leaving the step", async () => {
    state.canConnect = true;
    render(<EmailAccountSetup nodeId="email" catalog={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Gmail" }));
    expect(screen.getByText("Setup google-workspace")).toBeInTheDocument();
  });
  it("does not offer account creation to a member without connection management", () => {
    state.canConnect = false;
    render(<EmailAccountSetup nodeId="email" catalog={[]} />);
    expect(screen.queryByRole("button", { name: "Connect Gmail" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect Outlook" })).toBeNull();
  });
});

it("pins only the SMTP secret id and preserves the rest of the email configuration", async () => {
  useWorkflowEditorStore.getState().seedGraph({
    entry_node_id: "email",
    nodes: [
      {
        id: "email",
        definition_id: "email.send",
        definition_version: 1,
        config: { reply_to: "support@example.com" },
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  });
  render(<EmailAccountSetup nodeId="email" catalog={[]} />);
  await userEvent.click(screen.getByRole("button", { name: "Choose SMTP" }));
  expect(useWorkflowEditorStore.getState().graph?.nodes[0]?.config).toEqual({
    reply_to: "support@example.com",
    smtp_secret_id: "smtp-id",
  });
});

it("keeps sender settings read-only when inspecting a run", () => {
  render(<EmailAccountSetup nodeId="email" catalog={[]} disabled />);
  expect(screen.getByRole("button", { name: "Choose SMTP" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Connect Gmail" })).toBeNull();
});

describe("sending through a connected mailbox", () => {
  const MCP_CALL = makeDefinition({ id: "mcp.call", category: "mcp", name: "Call an MCP tool" });
  const mailbox = {
    id: "c1",
    name: "support-inbox",
    label: null,
    catalog_key: "google-workspace",
    is_enabled: true,
    allowed_tools: null,
    last_tools: [
      { name: "send_gmail_message", description: "Send a message" },
      { name: "search_gmail_messages", description: "Search" },
    ],
  };

  function seedEmailStep() {
    useWorkflowEditorStore.getState().seedGraph({
      entry_node_id: "email",
      nodes: [
        {
          id: "email",
          definition_id: "email.send",
          definition_version: 1,
          config: { subject: "Hi" },
          layout: { x: 0, y: 0 },
        },
      ],
      edges: [],
      bindings: [],
      scopes: [],
    });
  }

  it("offers the mailbox's send tools only, and switches the step to one after a confirmation", async () => {
    state.connections = [mailbox];
    seedEmailStep();
    render(<EmailAccountSetup nodeId="email" catalog={[MCP_CALL]} />);
    expect(screen.queryByRole("button", { name: /Search/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /support-inbox/ }));
    await userEvent.click(screen.getByRole("button", { name: "Use mailbox" }));

    expect(useWorkflowEditorStore.getState().graph?.nodes[0]).toMatchObject({
      definition_id: "mcp.call",
      config: { connection_id: "c1", tool: "send_gmail_message" },
    });
  });

  it("leaves the step as it was when the switch is cancelled", async () => {
    state.connections = [mailbox];
    seedEmailStep();
    render(<EmailAccountSetup nodeId="email" catalog={[MCP_CALL]} />);

    await userEvent.click(screen.getByRole("button", { name: /support-inbox/ }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(useWorkflowEditorStore.getState().graph?.nodes[0]?.definition_id).toBe("email.send");
  });

  it("opens the Outlook connection flow from its button", async () => {
    render(<EmailAccountSetup nodeId="email" catalog={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "Connect Outlook" }));

    expect(screen.getByText("Setup ms-365")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close setup" }));
    expect(screen.queryByText("Setup ms-365")).toBeNull();
  });
});
