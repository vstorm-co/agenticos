import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { trackingProject } from "@/test-utils/project-tracking";
import { ProjectTrackingOffer } from "./project-tracking-offer";
const state = vi.hoisted(() => ({
  eligible: true,
  allowed: true,
  known: true,
  open: vi.fn(),
  dismiss: vi.fn(),
}));
vi.mock("@/lib/locale-navigation", () => ({ usePathname: () => "/projects/launch" }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed, scopeOf: () => "all" }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: state.eligible
      ? [{ can_run: true, status: "published", current_version_id: "v", workflow_id: null }]
      : [],
  }),
  useAgentCeiling: () => ({ known: state.known, ceiling: null }),
}));
vi.mock("@/stores/onboarding-store", () => ({
  useOnboardingStore: (
    select: (s: { openFlow: typeof state.open; dismissOffer: typeof state.dismiss }) => unknown,
  ) => select({ openFlow: state.open, dismissOffer: state.dismiss }),
}));
beforeEach(() => {
  state.eligible = true;
  state.allowed = true;
  state.known = true;
  state.open.mockReset();
  state.dismiss.mockReset();
});
function mount(installed = false) {
  const client = new QueryClient();
  client.setQueryData(qk.projects.detail("launch"), trackingProject);
  client.setQueryData(qk.projects.tracking("launch"), installed ? { id: "installed" } : null);
  return render(
    <QueryClientProvider client={client}>
      <ProjectTrackingOffer />
    </QueryClientProvider>,
  );
}
it("opens the explicit project setup flow after accepting the offer", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Yes, guide me" }));
  expect(state.open).toHaveBeenCalledWith("create-project-tracker");
});
it.each(["installed", "permissions", "base", "limit"])(
  "does not offer an unavailable setup: %s",
  (reason) => {
    state.allowed = reason !== "permissions";
    state.eligible = reason !== "base";
    state.known = reason !== "limit";
    mount(reason === "installed");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);
