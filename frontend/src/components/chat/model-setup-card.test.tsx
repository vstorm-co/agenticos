import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelSetupCard } from "./model-setup-card";
import { Perm } from "@/types/permissions";
const env = vi.hoisted(() => ({
  interactive: true,
  manage: true,
  email: "owner@example.com" as string | null,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    can: (permission: string) =>
      env.manage && (permission === Perm.connectionsManage || permission === Perm.agentsEdit),
  }),
}));
vi.mock("@/hooks/use-start", () => ({ useStart: () => ({ data: { support_email: env.email } }) }));
vi.mock("@/components/onboarding/start-companions", () => ({ StartCompanions: () => null }));
beforeEach(() => {
  env.interactive = true;
  env.manage = true;
  env.email = "owner@example.com";
});
it("takes a builder directly to the chosen starter's model settings", () => {
  render(<ModelSetupCard agentId="starter" interactive={env.interactive} />);
  expect(screen.getByRole("link", { name: "Connect my AI model" })).toHaveAttribute(
    "href",
    "/agents/starter?highlight=agent-model-picker",
  );
  expect(screen.getByText(/No AI model was called/)).toBeVisible();
});
it("offers members their administrator rather than a forbidden configuration control", () => {
  env.manage = false;
  render(<ModelSetupCard agentId="starter" interactive={env.interactive} />);
  expect(screen.queryByRole("link", { name: "Connect my AI model" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Contact your administrator" })).toHaveAttribute(
    "href",
    "mailto:owner@example.com",
  );
});
it("renders a shared transcript without private setup actions or owner details", () => {
  env.interactive = false;
  render(<ModelSetupCard agentId="starter" interactive={env.interactive} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("keeps the member explanation when no support address is available", () => {
  env.manage = false;
  env.email = null;
  render(<ModelSetupCard agentId="starter" interactive={env.interactive} />);
  expect(screen.getByText(/Your workspace administrator can connect AI/)).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
