import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StartEntry } from "./start-entry";
const env = vi.hoisted(() => ({
  automatic: true,
  activity: false,
  ready: false,
  dismissed: false,
  pending: false,
  noOrg: false,
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(env.automatic ? "welcome=1" : ""),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: env.noOrg
      ? undefined
      : {
          dismissed: env.dismissed,
          has_result: false,
          has_activity: env.activity,
          agents: env.ready ? [{ id: "agent" }] : [],
        },
    isLoading: env.pending,
    waitingForScope: env.noOrg,
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ isPending: false, data: env.noOrg ? [] : [{}] }),
}));
vi.mock("./start-hub", () => ({ StartHub: () => <h1>Workspace setup</h1> }));
beforeEach(() => {
  Object.assign(env, {
    automatic: true,
    activity: false,
    ready: false,
    dismissed: false,
    pending: false,
    noOrg: false,
  });
  env.replace.mockReset();
});
it.each(["activity", "ready", "dismissed"] as const)(
  "takes an automatic welcome to chat for %s",
  async (reason) => {
    env[reason] = true;
    render(<StartEntry />);
    await waitFor(() => expect(env.replace).toHaveBeenCalledWith("/chat"));
    expect(screen.queryByRole("heading", { name: "Workspace setup" })).not.toBeInTheDocument();
  },
);
it("keeps manually opened setup available to existing users", () => {
  env.automatic = false;
  env.activity = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
  expect(env.replace).not.toHaveBeenCalled();
});
it("waits for the check before deciding", () => {
  env.pending = true;
  render(<StartEntry />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(env.replace).not.toHaveBeenCalled();
});
it("allows an administrator without any organization to create one", () => {
  env.noOrg = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
});
