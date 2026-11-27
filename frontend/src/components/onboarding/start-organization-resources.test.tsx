import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Perm, type Permission } from "@/types/permissions";
import { StartOrganizationResources } from "./start-organization-resources";
const env = vi.hoisted(() => ({
  loaded: true,
  error: false,
  permissions: new Set<Permission>(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    isLoaded: env.loaded,
    error: env.error ? new Error("refused") : null,
    can: (permission: Permission) => env.permissions.has(permission),
    refetch: env.refetch,
  }),
}));
beforeEach(() => {
  env.loaded = true;
  env.error = false;
  env.permissions.clear();
  env.refetch.mockClear();
});
it.each(["models", "tools"] as const)(
  "keeps %s optional without offering an unauthorized shared resource",
  (kind) => {
    render(<StartOrganizationResources kind={kind} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("permissions do not include");
  },
);
it.each(["models", "tools"] as const)(
  "opens existing %s resources in a separate tab without setting a personal model",
  (kind) => {
    env.permissions.add(kind === "models" ? Perm.secretsView : Perm.connectionsView);
    render(<StartOrganizationResources kind={kind} />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      kind === "models" ? "/vault" : "/mcp-servers",
    );
    expect(screen.getByRole("link")).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/Return to this setup/)).toBeVisible();
  },
);
it("does not describe loading permissions as a denial", () => {
  env.loaded = false;
  render(<StartOrganizationResources kind="models" />);
  expect(screen.queryByText(/permissions do not include/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("shows an explicit retry on a refused read", async () => {
  env.error = true;
  render(<StartOrganizationResources kind="tools" />);
  expect(screen.getByText("Could not load setup")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.refetch).toHaveBeenCalledOnce();
});
