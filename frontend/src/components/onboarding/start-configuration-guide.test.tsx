import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Perm, type Permission } from "@/types/permissions";
import { StartConfigurationGuide } from "./start-configuration-guide";

const env = vi.hoisted(() => ({ permissions: new Set<string>(), orgId: "org-1" as string | null }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => env.permissions.has(permission) }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: <T,>(select: (state: { activeOrgId: string | null }) => T) =>
    select({ activeOrgId: env.orgId }),
}));
beforeEach(() => {
  env.permissions = new Set();
  env.orgId = "org-1";
});
it("keeps optional configuration closed and offers personal settings without resource permissions", async () => {
  render(<StartConfigurationGuide />);
  expect(screen.getByText("Explore optional settings").closest("details")).not.toHaveAttribute(
    "open",
  );
  await userEvent.click(screen.getByText("Explore optional settings"));
  expect(screen.getByRole("link", { name: "Make the console yours" })).toHaveAttribute(
    "href",
    "/settings/profile",
  );
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByText(/You can finish setup now/)).toBeVisible();
});
it("offers permitted projects, transfers, Python actions and organization defaults", async () => {
  env.permissions = new Set([
    Perm.projectsView,
    Perm.agentsView,
    Perm.workflowsView,
    Perm.orgSettings,
  ]);
  render(<StartConfigurationGuide />);
  await userEvent.click(screen.getByText("Explore optional settings"));
  expect(screen.getByRole("link", { name: "Keep work together in projects" })).toHaveAttribute(
    "href",
    "/projects",
  );
  expect(screen.getByRole("link", { name: "Export and import agents" })).toHaveAttribute(
    "href",
    "/agents",
  );
  expect(screen.getByRole("link", { name: "Build workflows with Python actions" })).toHaveAttribute(
    "href",
    "/workflows",
  );
  expect(screen.getByRole("link", { name: "Set organization defaults" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=assistant",
  );
  expect(screen.getAllByRole("link")).toHaveLength(5);
});
it("does not offer organization configuration without an active membership scope", async () => {
  env.orgId = null;
  env.permissions = new Set([Perm.orgSettings]);
  render(<StartConfigurationGuide />);
  await userEvent.click(screen.getByText("Explore optional settings"));
  expect(screen.queryByRole("link", { name: "Set organization defaults" })).toBeNull();
  expect(screen.getAllByRole("link")).toHaveLength(1);
});
