import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { EmailAccountSetup } from "./email-account-setup";
const state = vi.hoisted(() => ({ canConnect: true }));
vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => ({ connections: [], ...state }),
}));
vi.mock("@/components/workflows/pickers/workflow-connections-dialog", () => ({
  WorkflowConnectionsDialog: ({ catalogKey }: { catalogKey?: string }) => <p>Setup {catalogKey}</p>,
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
afterEach(() => useWorkflowEditorStore.getState().teardown());
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
