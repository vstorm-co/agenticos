import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StartTools } from "./start-connections";
const env = vi.hoisted(() => ({ canManage: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => env.canManage }),
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
