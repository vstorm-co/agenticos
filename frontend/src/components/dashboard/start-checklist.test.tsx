import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StartChecklist } from "./start-checklist";
const state = vi.hoisted(() => ({
  data: {
    organization_id: "org",
    dismissed: false,
    has_result: false,
    has_activity: false,
    agents: [],
  },
  error: null as unknown,
  isLoading: false,
  waitingForScope: false,
  refetch: vi.fn(),
  save: { mutate: vi.fn(), isPending: false, isError: false },
}));
vi.mock("@/hooks/use-start", () => ({ useStart: () => state }));
beforeEach(() => {
  state.data = {
    organization_id: "org",
    dismissed: false,
    has_result: false,
    has_activity: false,
    agents: [],
  };
  state.error = null;
  state.isLoading = false;
  state.waitingForScope = false;
  state.save.mutate.mockClear();
});
it("links to the shared start and saves a dismissal without claiming success", async () => {
  render(<StartChecklist orgId="org" />);
  expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/onboarding");
  await userEvent.click(screen.getByRole("button", { name: "Hide for 24 hours" }));
  expect(state.save.mutate).toHaveBeenCalledWith({ dismissed: true });
});
it.each(["other-organization", "dismissed", "result", "error"])(
  "does not offer an irrelevant start: %s",
  (reason) => {
    if (reason === "other-organization") state.data.organization_id = "other";
    if (reason === "dismissed") state.data.dismissed = true;
    if (reason === "result") state.data.has_result = true;
    if (reason === "error") state.error = new Error("offline");
    render(<StartChecklist orgId="org" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  },
);

it("reserves a shaped panel while start state is loading", () => {
  state.isLoading = true;
  render(<StartChecklist orgId="org" />);
  expect(screen.getByRole("region", { name: "Start with something useful" })).toHaveClass(
    "min-h-[22rem]",
    "lg:h-[31rem]",
  );
  expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("offers retry rather than silently dropping a failed start check", async () => {
  state.error = new Error("offline");
  render(<StartChecklist orgId="org" />);
  expect(screen.getByRole("alert")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});
