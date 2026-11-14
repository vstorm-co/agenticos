import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartOffer } from "./start-offer";
const env = vi.hoisted(() => ({
  path: "/chat",
  params: new URLSearchParams(),
  dismissed: false,
  hasResult: false,
  appAdmin: false,
  orgAdmin: false,
  closed: false,
  pending: false,
  error: false,
  save: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => env.path,
  useSearchParams: () => env.params,
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (pick: (state: { user: { is_app_admin: boolean } }) => unknown) =>
    pick({ user: { is_app_admin: env.appAdmin } }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: { is_personal: false } }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.orgAdmin }) }));
vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ maintenanceMode: false }),
}));
vi.mock("@/hooks/use-branding-notice", () => ({
  useBrandingNotice: () => ({ data: { maintenance_mode: env.closed } }),
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: {
      organization_name: "Demo",
      dismissed: env.dismissed,
      has_result: env.hasResult,
      has_activity: false,
      agents: [],
    },
    save: { mutate: env.save, isPending: env.pending, isError: env.error },
  }),
}));
beforeEach(() => {
  env.path = "/chat";
  env.params = new URLSearchParams();
  env.dismissed = false;
  env.hasResult = false;
  env.appAdmin = false;
  env.orgAdmin = false;
  env.pending = false;
  env.closed = false;
  env.error = false;
  env.save.mockClear();
});
it("offers a shared start and saves only the decision to dismiss it", async () => {
  render(<StartOffer />);
  expect(screen.getByRole("link", { name: "Try an example" })).toHaveAttribute(
    "href",
    "/onboarding",
  );
  await userEvent.click(screen.getByRole("button", { name: "Hide for 24 hours" }));
  expect(env.save).toHaveBeenCalledWith({ dismissed: true });
});
it.each(["existing chat", "example", "dismissed", "completed", "dashboard"])(
  "does not interrupt %s",
  (reason) => {
    if (reason === "existing chat") env.params.set("id", "conversation");
    if (reason === "example") env.params.set("example", "meeting");
    if (reason === "dismissed") env.dismissed = true;
    if (reason === "completed") env.hasResult = true;
    if (reason === "dashboard") env.path = "/dashboard";
    render(<StartOffer />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  },
);

it.each(["application", "organization"])(
  "offers relevant setup guidance to an %s administrator",
  (kind) => {
    env.appAdmin = kind === "application";
    env.orgAdmin = kind === "organization";
    render(<StartOffer />);
    expect(
      screen.getByRole("complementary", { name: "Set up your team’s workspace" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Continue setup" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
    expect(screen.queryByRole("link", { name: "Try an example" })).not.toBeInTheDocument();
  },
);
it("keeps the notice available after a refused dismissal and blocks repeated pending clicks", () => {
  env.error = true;
  env.pending = true;
  render(<StartOffer />);
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.getByRole("button", { name: "Hide for 24 hours" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Try an example" })).toBeVisible();
});

it("does not offer setup over a maintenance screen for a regular member", () => {
  env.closed = true;
  render(<StartOffer />);
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
});
it("keeps setup reachable for an application administrator during maintenance", () => {
  env.closed = true;
  env.appAdmin = true;
  render(<StartOffer />);
  expect(screen.getByRole("link", { name: "Continue setup" })).toBeVisible();
});
