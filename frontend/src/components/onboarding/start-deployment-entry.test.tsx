import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartDeploymentEntry } from "./start-deployment-entry";
const env = vi.hoisted(() => ({
  allowed: true,
  pending: false,
  completed: false,
  failure: false,
  save: vi.fn(),
  refetch: vi.fn(),
  switchOrg: vi.fn(),
}));
vi.mock("@/hooks/use-deployment-start", () => ({
  useDeploymentStart: () => ({
    allowed: env.allowed,
    isLoading: env.pending,
    error: env.failure ? new Error("forbidden") : null,
    refetch: env.refetch,
    save: { mutate: env.save, isPending: false, isError: false },
    data: {
      organization_id: null,
      organization_name: null,
      scopes: [
        {
          scope: "deployment",
          applicable: true,
          completed: env.completed,
          completed_at: null,
          current_step: null,
          updated_at: null,
        },
        {
          scope: "organization",
          applicable: false,
          completed: false,
          completed_at: null,
          current_step: null,
          updated_at: null,
        },
        {
          scope: "personal",
          applicable: false,
          completed: false,
          completed_at: null,
          current_step: null,
          updated_at: null,
        },
      ],
    },
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ switchOrg: env.switchOrg }),
  useOrganizationList: () => ({ data: [], isPending: false, error: null, refetch: env.refetch }),
}));
vi.mock("./start-workspace", () => ({
  StartWorkspace: ({ onSelect }: { onSelect: (id: string) => void }) => (
    <button onClick={() => onSelect("created-org")}>Create organization</button>
  ),
}));
vi.mock("./start-shared-journey", async () => {
  const { StartScopeProgress } = await import("./start-scope-progress");
  return {
    StartSharedJourney: ({ org, onComplete }: { org?: object; onComplete: () => void }) => (
      <>
        <StartScopeProgress />
        <h1>{org ? "Unexpected tenant" : "First deployment setup"}</h1>
        <input aria-label="Unsent deployment setting" defaultValue="" />
        <button onClick={onComplete}>Complete deployment</button>
      </>
    ),
  };
});
beforeEach(() => {
  vi.clearAllMocks();
  env.allowed = true;
  env.pending = false;
  env.completed = false;
  env.failure = false;
});
it("starts deployment without inventing an organization or automatically completing it", async () => {
  render(<StartDeploymentEntry />);
  expect(screen.getByRole("heading", { name: "First deployment setup" })).toBeVisible();
  expect(env.save).not.toHaveBeenCalled();
  expect(env.switchOrg).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Complete deployment" }));
  expect(env.save).toHaveBeenCalledWith({ completed: true }, expect.any(Object));
});
it("only offers organization creation after the deployment is explicitly complete", async () => {
  env.completed = true;
  render(<StartDeploymentEntry />);
  expect(screen.getByRole("heading", { name: "Create or choose an organization" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Set up the deployment — Completed" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /Your personal setup/ })).not.toBeInTheDocument();
  expect(env.save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Create organization" }));
  expect(env.switchOrg).toHaveBeenCalledWith("created-org");
});
it("keeps explicit review available without resetting shared completion", async () => {
  env.completed = true;
  render(<StartDeploymentEntry />);
  await userEvent.click(screen.getByRole("button", { name: "Set up the deployment — Completed" }));
  expect(screen.getByRole("heading", { name: "First deployment setup" })).toBeVisible();
  expect(env.save).not.toHaveBeenCalled();
});
it.each(["loading", "revoked"])("does not display retained setup data while %s", (reason) => {
  env.pending = reason === "loading";
  env.allowed = reason !== "revoked";
  render(<StartDeploymentEntry />);
  expect(screen.queryByRole("button", { name: "Complete deployment" })).not.toBeInTheDocument();
  expect(env.save).not.toHaveBeenCalled();
});
it("shows a refused read and an explicit retry instead of organization creation", async () => {
  env.failure = true;
  render(<StartDeploymentEntry />);
  expect(screen.getByText("Could not load setup")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Create organization" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.refetch).toHaveBeenCalled();
});

it("retains the no-organization deployment draft when another administrator finishes", async () => {
  const view = render(<StartDeploymentEntry />);
  const input = screen.getByRole("textbox", { name: "Unsent deployment setting" });
  await userEvent.type(input, "Draft not sent");
  env.completed = true;
  view.rerender(<StartDeploymentEntry />);
  expect(screen.getByRole("textbox", { name: "Unsent deployment setting" })).toBe(input);
  expect(input).toHaveValue("Draft not sent");
  await userEvent.click(screen.getByRole("button", { name: "Continue to the next stage" }));
  expect(screen.getByRole("heading", { name: "Create or choose an organization" })).toBeVisible();
  expect(env.save).not.toHaveBeenCalled();
});
