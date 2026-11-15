import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Organization } from "@/types";
import { Perm, type Permission } from "@/types/permissions";
import { StartDeployment } from "./start-deployment";
import { StartBudget } from "./start-budget";
import { StartOrganizationSettings } from "./start-organization-settings";

const env = vi.hoisted(() => ({
  settings: {
    signup_mode: "open",
    default_organization_id: null as string | null,
    default_organization_role: "member",
    personal_organizations: true,
    announcement: null as string | null,
    announcement_level: "info",
    maintenance_mode: false,
    allowed_email_domains: ["example.com"],
  },
  save: vi.fn(),
  budget: vi.fn(),
  next: vi.fn(),
  pending: false,
  permissions: new Set<Permission>(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/hooks/use-deployment-settings", () => ({
  useDeploymentSettings: () => ({
    settings: env.settings,
    isLoading: false,
    save: { mutateAsync: env.save, isPending: env.pending },
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ setMonthlyBudget: env.budget }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: Permission) => env.permissions.has(permission),
    isLoaded: true,
  }),
}));
vi.mock("@/components/teams", () => ({
  OrgApprovalWaiver: () => <p>Approval policy</p>,
  OrgPublicLiveData: () => <p>Data policy</p>,
  OrgVoiceSettings: () => <p>Voice controls</p>,
  OrgProactivity: () => <p>Automation</p>,
  OrgAssistant: () => <p>Assistant</p>,
  OrgSystemAgents: () => <p>System agents</p>,
}));
vi.mock("./start-guide", () => ({
  StartGuide: ({ message }: { message: string }) => <aside>{message}</aside>,
}));
const org: Organization = {
  id: "company",
  name: "Northwind",
  slug: "northwind",
  is_personal: false,
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
  created_at: "2026-11-09T00:00:00Z",
  updated_at: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/onboarding");
  env.pending = false;
  env.permissions = new Set();
  env.save.mockResolvedValue({});
  env.budget.mockResolvedValue(org);
  Object.assign(env.settings, {
    signup_mode: "open",
    default_organization_id: null,
    default_organization_role: "member",
    personal_organizations: true,
    announcement: null,
    announcement_level: "info",
    maintenance_mode: false,
  });
});
const proceed = () => userEvent.click(screen.getByRole("button", { name: "Save and continue" }));

it("sends only the access decision and advances only after its save", async () => {
  let resolve: (() => void) | undefined;
  env.save.mockImplementation(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  render(<StartDeployment org={org} onContinue={env.next} />);
  await userEvent.click(screen.getByRole("button", { name: /By invitation/ }));
  expect(env.save).not.toHaveBeenCalled();
  await proceed();
  expect(env.save).toHaveBeenCalledWith({ signup_mode: "invite_only" });
  expect(screen.getByRole("heading", { name: "Who should be able to join?" })).toBeVisible();
  await act(async () => resolve?.());
  expect(
    await screen.findByRole("heading", { name: "Where should new accounts start?" }),
  ).toBeVisible();
});
it("keeps the current answer and reports a failed save", async () => {
  env.save.mockRejectedValueOnce(new Error("Unavailable"));
  render(<StartDeployment org={org} onContinue={env.next} />);
  await userEvent.click(screen.getByRole("button", { name: /By invitation/ }));
  await proceed();
  expect(screen.getByRole("alert")).toHaveTextContent("weren't saved");
  expect(screen.getByRole("button", { name: /By invitation/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(env.next).not.toHaveBeenCalled();
  await proceed();
  expect(
    await screen.findByRole("heading", { name: "Where should new accounts start?" }),
  ).toBeVisible();
});
it("skips optional decisions without applying their unsaved changes", async () => {
  render(<StartDeployment org={org} onContinue={env.next} />);
  await userEvent.click(screen.getByRole("button", { name: /By invitation/ }));
  await userEvent.click(screen.getByRole("button", { name: "Keep current settings" }));
  await proceed();
  await userEvent.type(screen.getByRole("textbox", { name: "Team announcement" }), "Hello team");
  expect(screen.getByText("Live preview")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Keep current settings" }));
  expect(screen.getByRole("heading", { name: "The rest can wait" })).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  await proceed();
  expect(env.next).toHaveBeenCalledOnce();
  expect(env.save).not.toHaveBeenCalled();
});
it("does not move old users or change the default role when choosing a company", async () => {
  render(<StartDeployment org={org} onContinue={env.next} />);
  await proceed();
  await userEvent.click(screen.getByRole("button", { name: /Northwind/ }));
  await userEvent.click(screen.getByRole("switch", { name: "Also create personal workspaces" }));
  await proceed();
  expect(env.save).toHaveBeenCalledWith({
    default_organization_id: "company",
    personal_organizations: false,
  });
});
it("keeps drafts when navigating between questions and does not write on view", async () => {
  render(<StartDeployment org={org} onContinue={env.next} />);
  await proceed();
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("button", { name: /Self-service sign-up/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(env.save).not.toHaveBeenCalled();
});
it("offers maintenance guidance without an activation switch", async () => {
  env.settings.maintenance_mode = true;
  render(<StartDeployment org={org} onContinue={env.next} />);
  for (let index = 0; index < 3; index++)
    await userEvent.click(screen.getByRole("button", { name: "Keep current settings" }));
  expect(screen.getByRole("status")).toHaveTextContent("currently active");
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(env.save).not.toHaveBeenCalled();
});
it("changes a budget by preset and slider but saves only on Continue", async () => {
  render(<StartBudget org={org} onContinue={env.next} />);
  expect(env.budget).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "$100" }));
  fireEvent.change(screen.getByRole("slider"), { target: { value: "350" } });
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  expect(screen.getByRole("slider")).toHaveValue("350");
  expect(env.budget).not.toHaveBeenCalled();
  await proceed();
  expect(env.budget).toHaveBeenCalledWith("company", 350);
  expect(env.next).toHaveBeenCalledOnce();
});
it("preserves an existing decimal cap without an unnecessary write", async () => {
  render(<StartBudget org={{ ...org, monthly_budget_usd: "1250.120000" }} onContinue={env.next} />);
  expect(screen.getByRole("slider")).toHaveValue("1250");
  expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext", "$1,250");
  await proceed();
  expect(env.budget).not.toHaveBeenCalled();
  expect(env.next).toHaveBeenCalledOnce();
});
it("keeps a failed budget save in the same question", async () => {
  env.budget.mockRejectedValue(new Error("Denied"));
  render(<StartBudget org={org} onContinue={env.next} />);
  await userEvent.click(screen.getByRole("button", { name: "$25" }));
  await proceed();
  expect(screen.getByRole("alert")).toHaveTextContent("weren't saved");
  expect(env.next).not.toHaveBeenCalled();
});
it("keeps the slider above zero and supports no ceiling", async () => {
  render(<StartBudget org={{ ...org, monthly_budget_usd: "100" }} onContinue={env.next} />);
  fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
  expect(screen.getByRole("slider")).toHaveValue("1");
  await userEvent.click(screen.getByRole("button", { name: "No limit" }));
  await proceed();
  expect(env.budget).toHaveBeenCalledWith("company", null);
});
it("never offers a budget or approval change without its effective permission", async () => {
  env.permissions.add(Perm.orgSettings);
  render(<StartOrganizationSettings org={org} onContinue={env.next} />);
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Approvals and public data"));
  expect(screen.getByText("Data policy")).toBeVisible();
  expect(screen.queryByText("Approval policy")).not.toBeInTheDocument();
  expect(env.budget).not.toHaveBeenCalled();
  await proceed();
  expect(env.next).toHaveBeenCalledOnce();
});

it("resumes a deployment question without applying a draft", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.deployment&workspace=company&question=announcement",
  );
  render(<StartDeployment org={org} onContinue={env.next} />);
  expect(screen.getByRole("textbox", { name: "Team announcement" })).toBeVisible();
  expect(env.save).not.toHaveBeenCalled();
});

it("does not let a hidden deployment flow replace another step's position", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.organization&workspace=company&question=budget",
  );
  render(<StartDeployment org={org} active={false} onContinue={env.next} />);
  expect(new URLSearchParams(window.location.search).get("question")).toBe("budget");
});

const openAnnouncement = () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.deployment&workspace=company&question=announcement",
  );
  render(<StartDeployment org={org} onContinue={env.next} />);
};

it("prefills the welcome message and saves it only on Continue", async () => {
  openAnnouncement();
  const message = screen.getByRole("textbox", { name: "Team announcement" });
  expect(message).toHaveValue(
    "Welcome! Start a conversation with AgenticOS, or ask your team for help.",
  );
  expect(screen.getByRole("region", { name: "Live preview" })).toHaveTextContent(
    "Welcome! Start a conversation with AgenticOS, or ask your team for help.",
  );
  expect(env.save).not.toHaveBeenCalled();
  await proceed();
  expect(env.save).toHaveBeenCalledWith({
    announcement: "Welcome! Start a conversation with AgenticOS, or ask your team for help.",
  });
});

it("preserves an existing announcement", async () => {
  env.settings.announcement = "Our existing welcome";
  openAnnouncement();
  expect(screen.getByRole("textbox", { name: "Team announcement" })).toHaveValue(
    "Our existing welcome",
  );
  await proceed();
  expect(env.save).not.toHaveBeenCalled();
});

it("allows clearing the suggested welcome message", async () => {
  openAnnouncement();
  await userEvent.clear(screen.getByRole("textbox", { name: "Team announcement" }));
  expect(screen.getByRole("region", { name: "Live preview" })).toHaveTextContent("No announcement");
  await proceed();
  expect(env.save).toHaveBeenCalledWith({ announcement: null });
});

it("shows every deployment extras link without expanding a section", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.deployment&workspace=company&question=extras",
  );
  render(<StartDeployment org={org} onContinue={env.next} />);
  const links = screen.getAllByRole("link", { name: /Open settings/ });
  expect(links).toHaveLength(4);
  for (const [index, section] of ["identity", "services", "services", "operations"].entries()) {
    expect(links[index]).toBeVisible();
    expect(links[index]).toHaveAttribute("href", `/admin/settings?section=${section}`);
    expect(links[index]).toHaveAttribute("target", "_blank");
  }
  expect(document.querySelector("details")).not.toBeInTheDocument();
});

it("selects and saves a budget in whole dollars", async () => {
  render(<StartBudget org={{ ...org, monthly_budget_usd: "100" }} onContinue={env.next} />);
  const slider = screen.getByRole("slider");
  expect(slider).toHaveAttribute("step", "1");
  fireEvent.change(slider, { target: { value: "354.4" } });
  expect(slider).toHaveValue("354");
  expect(slider).toHaveAttribute("aria-valuetext", "$354");
  await proceed();
  expect(env.budget).toHaveBeenCalledWith("company", 354);
});
