import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useChatControlsStore, chatControlScope } from "@/stores/chat-controls-store";
import { StartModels, StartTools } from "./start-connections";
const env = vi.hoisted(() => ({ canManage: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => env.canManage }),
}));
vi.mock("@/components/chat/chat-model-picker", () => ({
  ChatModelPicker: ({
    value,
    onChange,
    agentModel,
  }: {
    value: string | null;
    onChange: (value: string | null) => void;
    agentModel: unknown;
  }) => (
    <button onClick={() => onChange("personal-model")}>
      {value ?? (agentModel === null ? "Choose model" : "Wrong shared default")}
    </button>
  ),
}));
vi.mock("@/components/mcp/mcp-server-list", () => ({
  McpServerList: ({
    canManageOrganization,
    persistSelection,
  }: {
    canManageOrganization: boolean;
    persistSelection: boolean;
  }) => (
    <p>
      {canManageOrganization ? "Shared and personal connections" : "Personal connections"}
      {persistSelection ? "Wrong URL mutation" : " Embedded catalog"}
    </p>
  ),
}));
beforeEach(() => {
  env.canManage = false;
  useChatControlsStore.setState({ byScope: {} });
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: "org" });
});
it("remembers a model for personal chat scope without modifying a shared agent", async () => {
  render(<StartModels />);
  await userEvent.click(screen.getByRole("button", { name: "Choose model" }));
  expect(
    useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
  ).toBe("personal-model");
  expect(screen.getByRole("button", { name: "personal-model" })).toBeVisible();
  expect(screen.getByText(/shared agent defaults/)).toBeVisible();
});
it.each([false, true])("gates shared MCP management (%s) and preserves onboarding URL", (can) => {
  env.canManage = can;
  render(<StartTools />);
  expect(
    screen.getByText(can ? /Shared and personal connections/ : /Personal connections/),
  ).toBeVisible();
  expect(screen.getByText(/Embedded catalog/)).toBeVisible();
  expect(screen.queryByText(/Wrong URL mutation/)).not.toBeInTheDocument();
});
