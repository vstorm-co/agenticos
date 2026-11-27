import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore, useOrgStore } from "@/stores";
import { START_SCOPES, type Onboarding, type StartScope } from "@/lib/onboarding-api";
import { StartScopedHub } from "./start-scoped-hub";
const env = vi.hoisted(() => ({
  data: null as Onboarding | null,
  save: vi.fn(),
  saveScope: vi.fn(),
  report: vi.fn(),
  switchOrg: vi.fn(),
  pending: false,
  failed: false,
  org: "org",
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: env.data,
    save: { mutate: env.save, isPending: false, isError: false },
    saveScope: { mutate: env.saveScope, isPending: env.pending, isError: env.failed },
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: { id: env.org, name: "Acme" }, switchOrg: env.switchOrg }),
  useOrganizationList: () => ({ data: [{ id: "org", name: "Acme" }] }),
}));
vi.mock("@/hooks/use-report-start-step", () => ({
  useReportStartStep: (...args: unknown[]) => env.report(...args),
}));
vi.mock("./start-shared-stage", () => ({
  StartSharedStage: ({
    step,
    onNext,
    onSelect,
  }: {
    step: string;
    onNext: () => void;
    onSelect: (id: string) => void;
  }) => (
    <div>
      <p>Body {step}</p>
      <input aria-label={`Unsent ${step} name`} defaultValue="" />
      <button onClick={onNext}>Next {step}</button>
      <button onClick={() => onSelect("org")}>Select organization</button>
    </div>
  ),
}));
vi.mock("./start-member", () => ({
  StartMember: ({ resumeStep }: { resumeStep: string | null }) => (
    <h1>Personal review {resumeStep}</h1>
  ),
}));
vi.mock("./start-preferences", () => ({
  StartPreferences: ({
    onContinue,
    continuing,
  }: {
    onContinue: () => void;
    continuing: boolean;
  }) => (
    <>
      <h1>Personal preferences</h1>
      <button disabled={continuing} onClick={onContinue}>
        Finish preferences
      </button>
    </>
  ),
}));
vi.mock("./start-language", () => ({ StartLanguage: () => null }));
function sample(): Onboarding {
  return {
    organization_id: "org",
    organization_name: "Acme",
    goal: null,
    dismissed: true,
    completed: true,
    snoozed_until: null,
    can_prepare: false,
    can_configure_model: false,
    support_email: null,
    agents: [],
    setup_agent: null,
    latest_conversation_id: null,
    latest_completed_at: null,
    has_result: true,
    has_activity: true,
    active_scope: "deployment",
    scopes: START_SCOPES.map((scope) => ({
      scope,
      applicable: true,
      completed: scope === "personal",
      completed_at: scope === "personal" ? "2026-01-01T00:00:00Z" : null,
      current_step: scope === "personal" ? "member.context" : null,
      updated_at: null,
    })),
  };
}
function state() {
  if (!env.data) throw new Error("Missing fixture");
  return env.data;
}
function complete(scope: StartScope) {
  const data = state();
  env.data = {
    ...data,
    scopes: data.scopes?.map((item) =>
      item.scope === scope
        ? { ...item, completed: true, completed_at: "2026-11-27T00:00:00Z" }
        : item,
    ),
    active_scope: scope === "deployment" ? "organization" : null,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  env.data = sample();
  env.pending = false;
  env.failed = false;
  env.org = "org";
  window.history.replaceState(null, "", "/onboarding");
  useAuthStore.setState({
    user: {
      id: "user",
      email: "user@example.com",
      is_active: true,
      is_app_admin: true,
      created_at: "2026-01-01T00:00:00Z",
    },
  });
  useOrgStore.setState({ activeOrgId: "org" });
});
it("does not let a future personal URL bypass new shared setup or reset completed personal progress", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-scope=personal&start-step=member.context&workspace=org",
  );
  render(<StartScopedHub data={state()} />);
  expect(screen.getByText("Body deployment")).toBeVisible();
  expect(screen.getByRole("button", { name: /Your personal setup/ })).toBeDisabled();
  expect(screen.queryByRole("heading", { name: "Personal preferences" })).not.toBeInTheDocument();
  expect(env.save).not.toHaveBeenCalled();
  expect(env.saveScope).not.toHaveBeenCalled();
  expect(env.report).toHaveBeenCalledWith("admin.deployment", "org", true, "deployment");
  expect(state().completed).toBe(true);
});
it("keeps the open shared draft after another administrator completes it, until explicit Continue", async () => {
  const view = render(<StartScopedHub data={state()} />);
  const deploymentDraft = screen.getByRole("textbox", { name: "Unsent deployment name" });
  await userEvent.type(deploymentDraft, "Unsent deployment edit");
  complete("deployment");
  view.rerender(<StartScopedHub data={state()} />);
  expect(screen.getByRole("textbox", { name: "Unsent deployment name" })).toBe(deploymentDraft);
  expect(deploymentDraft).toHaveValue("Unsent deployment edit");
  expect(screen.getByRole("status")).toHaveTextContent("Your open form stays available");
  await userEvent.click(screen.getByRole("button", { name: "Continue to the next stage" }));
  expect(screen.getByText("Body workspace")).toBeVisible();
  const organizationDraft = screen.getByRole("textbox", { name: "Unsent workspace name" });
  await userEvent.type(organizationDraft, "Unsent team name");
  complete("organization");
  view.rerender(<StartScopedHub data={state()} />);
  expect(organizationDraft).toHaveValue("Unsent team name");
  expect(screen.getByRole("textbox", { name: "Unsent workspace name" })).toBe(organizationDraft);
  expect(
    screen.queryByRole("heading", { name: /Personal review|Personal preferences/ }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Continue to the next stage" }));
  expect(screen.getByRole("heading", { name: "Setup is complete" })).toBeVisible();
  expect(env.save).not.toHaveBeenCalled();
  expect(env.saveScope).not.toHaveBeenCalled();
});

it("allows explicit earlier-stage review and clears it when its current authority disappears", async () => {
  complete("deployment");
  const view = render(<StartScopedHub data={state()} />);
  await userEvent.click(screen.getByRole("button", { name: /Set up the deployment/ }));
  expect(screen.getByText("Body deployment")).toBeVisible();
  env.data = {
    ...state(),
    scopes: state().scopes?.map((scope) =>
      scope.scope === "deployment"
        ? { ...scope, applicable: false, completed_at: null, current_step: null, updated_at: null }
        : scope,
    ),
  };
  view.rerender(<StartScopedHub data={state()} />);
  expect(screen.getByText("Body workspace")).toBeVisible();
  expect(screen.queryByRole("button", { name: /Set up the deployment/ })).not.toBeInTheDocument();
  env.data = {
    ...state(),
    scopes: state().scopes?.map((scope) => ({ ...scope, applicable: true })),
  };
  view.rerender(<StartScopedHub data={state()} />);
  expect(screen.getByText("Body workspace")).toBeVisible();
});
it("marks only the explicit shared scope on completion and fences a late callback after logout", async () => {
  render(<StartScopedHub data={state()} />);
  await userEvent.click(screen.getByRole("button", { name: "Next deployment" }));
  expect(env.saveScope).toHaveBeenCalledWith(
    { scope: "deployment", data: { completed: true } },
    expect.objectContaining({ onSuccess: expect.any(Function) }),
  );
  const call = env.saveScope.mock.calls[0];
  if (!call) throw new Error("Expected completion mutation");
  const callbacks: { onSuccess: (saved: { data: Onboarding }) => void } = call[1];
  const before = window.location.search;
  act(() => useAuthStore.setState({ user: null }));
  act(() => callbacks.onSuccess({ data: { ...state(), active_scope: "organization" } }));
  expect(window.location.search).toBe(before);
  expect(screen.queryByText("Body deployment")).not.toBeInTheDocument();
});
it("shows saving failures and disables phase changes without pretending completion", () => {
  env.pending = true;
  env.failed = true;
  render(<StartScopedHub data={state()} />);
  expect(screen.getByRole("alert")).toHaveTextContent("could not be saved");
  for (const button of within(
    screen.getByRole("navigation", { name: "Setup stages" }),
  ).getAllByRole("button"))
    expect(button).toBeDisabled();
  expect(state().scopes?.[0]?.completed).toBe(false);
});
it("does not render another organization's cached stage", () => {
  env.org = "other";
  render(<StartScopedHub data={state()} />);
  expect(screen.queryByText("Body deployment")).not.toBeInTheDocument();
  expect(env.report).not.toHaveBeenCalled();
});
it("starts personal preferences only after applicable shared phases, then preserves a saved personal resume", async () => {
  complete("deployment");
  complete("organization");
  env.data = {
    ...state(),
    completed: false,
    dismissed: false,
    active_scope: "personal",
    current_step: null,
    scopes: state().scopes?.map((scope) =>
      scope.scope === "personal"
        ? { ...scope, completed: false, current_step: null, completed_at: null }
        : scope,
    ),
  };
  const view = render(<StartScopedHub data={state()} />);
  expect(screen.getByRole("heading", { name: "Personal preferences" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Finish preferences" }));
  expect(env.save).toHaveBeenCalledWith({ current_step: "member.welcome" }, expect.any(Object));
  env.data = {
    ...state(),
    scopes: state().scopes?.map((scope) =>
      scope.scope === "personal" ? { ...scope, current_step: "admin.context" } : scope,
    ),
  };
  view.rerender(<StartScopedHub data={state()} />);
  expect(screen.getByRole("heading", { name: "Personal review member.context" })).toBeVisible();
  expect(state().completed).toBe(false);
});
