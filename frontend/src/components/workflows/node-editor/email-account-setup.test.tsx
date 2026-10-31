import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmailAccountSetup } from "./email-account-setup";
const state = vi.hoisted(() => ({ canConnect: true }));
vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => ({ connections: [], ...state }),
}));
vi.mock("@/components/workflows/pickers/workflow-connections-dialog", () => ({
  WorkflowConnectionsDialog: ({ catalogKey }: { catalogKey?: string }) => <p>Setup {catalogKey}</p>,
}));
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
