import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Organization } from "@/types";
import { Perm, type Permission } from "@/types/permissions";
import { StartAdministration } from "./start-administration";

const env = vi.hoisted(() => ({
  orgs: new Array<Organization>(),
  activeId: "personal",
  permissions: new Set<Permission>(),
  create: vi.fn(),
  change: vi.fn(),
  refetch: vi.fn(),
  local: false,
  error: null as unknown,
  deployment: vi.fn(),
  finish: vi.fn(),
  push: vi.fn(),
  profileCallbacks: new Map<string, () => void>(),
  permissionError: null as unknown,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: {
      organization_id: env.activeId,
      organization_name: "Northwind",
      goal: null,
      dismissed: false,
      completed: false,
      snoozed_until: null,
      has_result: false,
      has_activity: false,
      agents: [],
      setup_agent: null,
      can_prepare: false,
      can_configure_model: false,
      support_email: null,
      latest_conversation_id: null,
      latest_completed_at: null,
    },
    save: { mutate: env.finish, isPending: false, error: null },
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({
    orgs: env.orgs,
    activeOrgId: env.activeId,
    activeOrg: env.orgs.find((org) => org.id === env.activeId) ?? null,
    switchOrg: env.change,
    createOrg: env.create,
  }),
  useOrganizationList: () => ({
    data: env.orgs,
    isPending: false,
    error: env.error,
    refetch: env.refetch,
  }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: Permission) => env.permissions.has(permission),
    isLoaded: true,
    isLoading: false,
    error: env.permissionError,
    refetch: env.refetch,
  }),
}));
vi.mock("@/lib/local-server", () => ({ isLoopbackAddress: () => env.local }));
vi.mock("@/components/desktop/blobby-pickers", () => ({ Face: () => null }));
vi.mock("@/components/settings/profile-identity-settings", () => ({
  ProfileIdentitySettings: ({
    onContinue,
    section,
    secondaryAction,
  }: {
    onContinue: () => void;
    section: string;
    secondaryAction?: React.ReactNode;
  }) => {
    env.profileCallbacks.set(section, onContinue);
    return (
      <div>
        <button onClick={onContinue}>Save and continue</button>
        {secondaryAction}
      </div>
    );
  },
}));
vi.mock("@/components/teams/organization-profile-settings", () => ({
  OrganizationProfileSettings: ({ onContinue }: { onContinue: () => void }) => (
    <button onClick={onContinue}>Save and continue</button>
  ),
}));
vi.mock("@/components/ui/entity-avatar", () => ({
  EntityAvatar: ({
    seed,
    imageSrc,
    hasImage,
  }: {
    seed: string;
    imageSrc?: string;
    hasImage?: boolean;
  }) => (
    <span
      aria-hidden="true"
      data-testid={`org-avatar-${seed}`}
      data-image={hasImage ? imageSrc : ""}
    />
  ),
}));
vi.mock("./start-language", () => ({ StartLanguage: () => null }));
vi.mock("./start-deployment", () => ({
  StartDeployment: ({ onContinue }: { onContinue?: () => void }) => {
    env.deployment();
    if (onContinue) env.profileCallbacks.set("deployment", onContinue);
    return (
      <>
        <input aria-label="Deployment name" defaultValue="AgenticOS" />
        <button onClick={onContinue}>Save and continue</button>
      </>
    );
  },
}));
vi.mock("./start-budget", () => ({
  StartBudget: ({ onContinue }: { onContinue: () => void }) => (
    <div>
      <h3>Workspace spending cap</h3>
      <button onClick={onContinue}>Keep current settings</button>
    </div>
  ),
}));
vi.mock("@/components/teams", () => ({
  InviteMemberDialog: ({ orgId, open }: { orgId: string; open: boolean }) =>
    open ? (
      <div role="dialog" aria-label="Email invitation">
        {orgId}
      </div>
    ) : null,
  InviteLinkDialog: ({ orgId, open }: { orgId: string; open: boolean }) =>
    open ? (
      <div role="dialog" aria-label="Invitation link">
        {orgId}
      </div>
    ) : null,
  OrgSpendingLimit: () => <h3>Workspace spending cap</h3>,
  OrgApprovalWaiver: () => <h3>Approval rules</h3>,
  OrgPublicLiveData: () => <h3>Public data policy</h3>,
  OrgVoiceSettings: () => <h3>Voice settings</h3>,
  OrgProactivity: () => <h3>Proactivity settings</h3>,
  OrgAssistant: () => <h3>Organization assistant</h3>,
  OrgSystemAgents: () => <h3>System agent budgets</h3>,
}));
function org(id: string, personal = false): Organization {
  return {
    id,
    name: personal ? "Personal" : "Northwind",
    slug: id,
    is_personal: personal,
    avatar_url: null,
    avatar_color: null,
    owner_id: "owner",
    stripe_customer_id: null,
    subscription_tier: "free",
    seats_limit: null,
    monthly_budget_usd: null,
    chat_may_waive_approvals: false,
    public_live_data: false,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    created_at: "2026-11-08T00:00:00Z",
    updated_at: null,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/onboarding");
  env.orgs = [org("personal", true)];
  env.activeId = "personal";
  env.permissions = new Set([
    Perm.membersManage,
    Perm.rolesManage,
    Perm.orgSettings,
    Perm.budgetsManage,
    Perm.approvalsDecide,
  ]);
  env.local = false;
  env.error = null;
  env.permissionError = null;
  env.profileCallbacks.clear();
  env.change.mockImplementation((id: string) => {
    env.activeId = id;
  });
  env.create.mockImplementation(async (input: { name: string }) => {
    const created = { ...org("company"), name: input.name };
    env.orgs = [...env.orgs, created];
    return created;
  });
});
async function selectCompany() {
  await userEvent.click(screen.getByRole("button", { name: "Northwind" }));
}
async function completePersonalization() {
  for (let i = 0; i < 3; i++)
    await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
}
async function openOrganizationSettings(appAdmin: boolean) {
  await selectCompany();
  await completePersonalization();
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  if (appAdmin) await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
}
it("starts with one decision and no settings sidebar", () => {
  render(<StartAdministration appAdmin />);
  expect(screen.getByRole("heading", { name: "Where will your team work?" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Organization name" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "People" })).not.toBeInTheDocument();
  expect(env.change).not.toHaveBeenCalled();
  expect(env.deployment).not.toHaveBeenCalled();
});
it("creates a company and guides identity, profile and context before team invitations", async () => {
  render(<StartAdministration appAdmin />);
  await userEvent.type(
    screen.getByRole("textbox", { name: "Organization name" }),
    "Northwind Labs",
  );
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  expect(env.create).toHaveBeenCalledWith({ name: "Northwind Labs" });
  expect(env.change).toHaveBeenCalledWith("company");
  expect(screen.getByRole("heading", { name: "Give your workspace an identity" })).toBeVisible();
  await completePersonalization();
  expect(screen.getByRole("heading", { name: "Invite your team" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Invite by email" }));
  expect(screen.getByRole("dialog", { name: "Email invitation" })).toHaveTextContent("company");
  expect(env.deployment).not.toHaveBeenCalled();
});
it("can start without any existing workspace", async () => {
  env.orgs = [];
  env.activeId = "";
  render(<StartAdministration appAdmin />);
  await userEvent.type(screen.getByRole("textbox", { name: "Organization name" }), "Northwind");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  expect(screen.getByRole("heading", { name: "Give your workspace an identity" })).toBeVisible();
});
it("keeps a failed creation on the same decision without advancing", async () => {
  env.create.mockRejectedValue(new Error("Cannot create workspace"));
  render(<StartAdministration appAdmin />);
  await userEvent.type(screen.getByRole("textbox", { name: "Organization name" }), "Northwind");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Create" })).toBeEnabled());
  expect(screen.getByRole("textbox", { name: "Organization name" })).toHaveValue("Northwind");
  expect(env.change).not.toHaveBeenCalled();
});
it("offers existing organizations before another creation form", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  expect(screen.queryByRole("textbox", { name: "Organization name" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Create a new workspace instead" }));
  expect(screen.getByRole("textbox", { name: "Organization name" })).toBeVisible();
  expect(env.create).not.toHaveBeenCalled();
});
it("preserves an edited deployment form when going back and forward", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await completePersonalization();
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  const input = await screen.findByRole("textbox", { name: "Deployment name" });
  await userEvent.clear(input);
  await userEvent.type(input, "Our installation");
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  expect(screen.getByRole("textbox", { name: "Deployment name" })).toHaveValue("Our installation");
});
it("skips deployment administration for an organization administrator", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin={false} />);
  await openOrganizationSettings(false);
  expect(screen.getByRole("heading", { name: "Workspace spending cap" })).toBeVisible();
  expect(env.deployment).not.toHaveBeenCalled();
});
it("renders only organization settings allowed by effective permissions", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  env.permissions = new Set([Perm.orgSettings]);
  render(<StartAdministration appAdmin={false} />);
  await openOrganizationSettings(false);
  await userEvent.click(screen.getByText("Approvals and public data"));
  expect(screen.getByRole("heading", { name: "Public data policy" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Workspace spending cap" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Approval rules" })).not.toBeInTheDocument();
});
it("blocks invitations with unusable local links while allowing setup to continue", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  env.local = true;
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await completePersonalization();
  expect(screen.getByRole("note")).toHaveTextContent("local address");
  expect(screen.getByRole("button", { name: "Invite by email" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Create an invitation link" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Continue setup" })).toBeEnabled();
});
it("does not offer invitations without member management permission", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  env.permissions = new Set([Perm.orgSettings]);
  render(<StartAdministration appAdmin={false} />);
  await selectCompany();
  await completePersonalization();
  expect(screen.queryByRole("button", { name: "Invite by email" })).not.toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent("do not have permission");
});
it("updates the preview while naming a workspace without creating anything", async () => {
  render(<StartAdministration appAdmin />);
  const preview = within(screen.getByRole("complementary", { name: "Workspace preview" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Organization name" }), "Acme Studio");
  expect(preview.getByText("Acme Studio")).toBeVisible();
  await userEvent.clear(screen.getByRole("textbox", { name: "Organization name" }));
  expect(preview.getByText("Your workspace")).toBeVisible();
  expect(env.create).not.toHaveBeenCalled();
});
it("offers a retry when the guided team permission check fails", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  env.permissionError = new Error("Permissions unavailable");
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await completePersonalization();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(env.refetch).toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Invite by email" })).not.toBeInTheDocument();
});

it("uses the organization's uploaded logo in the workspace picker", () => {
  const company = {
    ...org("company"),
    avatar_url: "avatars/company.png",
    updated_at: "2026-11-08T12:00:00Z",
  };
  env.orgs = [company];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  const avatar = within(screen.getByRole("button", { name: "Northwind" })).getByTestId(
    "org-avatar-company",
  );
  expect(avatar).toHaveAttribute("data-image", "/api/orgs/company/avatar?v=2026-11-08T12:00:00Z");
});

it("does not advance after a late profile save when the person has gone back", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  const late = env.profileCallbacks.get("identity");
  if (!late) throw new Error("Missing identity continuation");
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  act(() => late());
  expect(screen.getByRole("heading", { name: "Give your workspace an identity" })).toBeVisible();
});
it("returns to workspace choice after an external active-organization switch", async () => {
  env.orgs = [org("personal", true), org("company")];
  env.activeId = "company";
  const view = render(<StartAdministration appAdmin />);
  await selectCompany();
  env.activeId = "personal";
  view.rerender(<StartAdministration appAdmin />);
  expect(screen.getByRole("heading", { name: "Where will your team work?" })).toBeVisible();
});
it("removes the deployment step when application administration is revoked", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  const view = render(<StartAdministration appAdmin />);
  await selectCompany();
  await completePersonalization();
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  expect(await screen.findByRole("textbox", { name: "Deployment name" })).toBeVisible();
  view.rerender(<StartAdministration appAdmin={false} />);
  expect(screen.getByRole("heading", { name: "Where will your team work?" })).toBeVisible();
  expect(screen.queryByRole("textbox", { name: "Deployment name" })).not.toBeInTheDocument();
});

it("finishes after all questions while leaving optional setup empty", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));
  await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep current settings" }));
  await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(env.finish).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Finish setup and open the app" }));
  expect(env.finish).toHaveBeenCalledWith({ completed: true }, expect.any(Object));
});

it("resumes the matching organization's step after its membership list arrives", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.deployment&workspace=company",
  );
  env.orgs = [];
  env.activeId = "company";
  const view = render(<StartAdministration appAdmin />);
  env.orgs = [org("company")];
  view.rerender(<StartAdministration appAdmin />);
  expect(screen.getByRole("textbox", { name: "Deployment name" })).toBeVisible();
});
it("never resumes deployment administration for an organization-only administrator", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.deployment&workspace=company",
  );
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin={false} />);
  expect(screen.getByRole("heading", { name: "Where will your team work?" })).toBeVisible();
  expect(env.deployment).not.toHaveBeenCalled();
});

it("ignores a deployment continuation after leaving that step", async () => {
  env.orgs = [org("company")];
  env.activeId = "company";
  render(<StartAdministration appAdmin />);
  await selectCompany();
  await completePersonalization();
  await userEvent.click(screen.getByRole("button", { name: "Continue setup" }));
  const late = env.profileCallbacks.get("deployment");
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  act(() => late?.());
  expect(screen.getByRole("heading", { name: "Invite your team" })).toBeVisible();
});
