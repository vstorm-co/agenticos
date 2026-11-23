import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { StartTools } from "./start-tools";

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("@/components/mcp/mcp-server-list", () => ({
  McpServerList: ({ presentation }: { presentation: string }) => <p>{presentation}</p>,
}));

it("starts with suggested services instead of the administrative catalog", () => {
  render(<StartTools />);
  expect(screen.getByText("onboarding")).toBeVisible();
});
