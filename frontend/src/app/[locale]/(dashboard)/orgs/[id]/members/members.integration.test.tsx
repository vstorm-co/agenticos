import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MembersPage from "./page";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { DEFAULT_CHAT_HOME, type ConsoleExperience } from "@/lib/console-experience-api";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOrgStore } from "@/stores";
import { permissionsOf, ROLE_CATALOG } from "@/test-utils/role-catalog";
import { assignableRoles } from "@/lib/assignable-roles";
import type { MyPermissions } from "@/types/permissions";
import { Perm } from "@/types/permissions";
import type { Organization, OrgRole } from "@/types/organization";

/**
 * Which rows offer a role picker, and which offer a label instead.
 *
 * The picker used to be drawn for every row an Admin could act on and filled
 * with every role in the catalog bar `owner` - so an Admin was offered Admin,
 * and `change_role` refused it. Worse on a *peer Admin's* row: Radix draws the
 * chosen item's text in the trigger, and `admin` was not among the items, so the
 * control rendered blank (#1028).
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The tenant is the organization in the path, so this file needs to move it.
// The rest are what `vitest.setup.ts` provides, and for its reason.
const path = vi.fn(() => "/");
const query = vi.fn(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => query(),
  usePathname: () => path(),
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const CONSOLE_EXPERIENCE: ConsoleExperience = {
  availability: DEFAULT_CHAT_HOME,
  organization_defaults: {},
  preferences: {},
  effective: DEFAULT_CHAT_HOME,
  reminders: {
    availability: true,
    organization_defaults: {},
    preferences: {},
    effective: { enabled: true, snooze_days: 1 },
  },
};

const ME = "user-me";

/**
 * Whether the caller may change this row's role, as the *server* answers it.
 *
 * Derived rather than hardcoded, and derived the same way `MemberService.list`
 * derives it: the caller holds `roles:manage` and their own role strictly
 * outranks the role this member holds now. A fixture that returned `true` for
 * every row would test a server this one is not.
 */
function mayChangeRole(callerRole: string, targetRole: string): boolean {
  return assignableRoles(ROLE_CATALOG, callerRole).includes(targetRole as OrgRole);
}

function member(
  id: string,
  email: string,
  role: string,
  canChangeRole = false,
  source: "manual" | "directory" = "manual",
) {
  return {
    // `id` as well as `user_id`: the table keys its rows on it, and four rows
    // keyed `undefined` collapse into one.
    id: `membership-${id}`,
    user_id: id,
    email,
    // Not the email: the row prints the name *and* the address, so a name that
    // is the address makes every `findByText` ambiguous.
    full_name: email.split("@")[0],
    avatar_url: null,
    avatar_color: null,
    role,
    joined_at: "2026-07-01T00:00:00Z",
    // The server's own answer to whether `change_role` would accept this, so the
    // page draws a selector only where a change would land rather than one whose
    // result is a 403 toast (#700).
    can_change_role: canChangeRole,
    source,
  };
}

/** Answer every request the page makes, as a caller holding `role`. */
function serve(
  role: string,
  extraPermissions: MyPermissions["permissions"] = [],
  configuration: Partial<Organization> = {},
) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/users/me/console-experience") return Promise.resolve(CONSOLE_EXPERIENCE);
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions"))
      return Promise.resolve({
        ...permissionsOf(role),
        permissions: [...permissionsOf(role).permissions, ...extraPermissions],
      });
    if (url === "/system-agents")
      return Promise.resolve({
        items: [
          {
            role: "memory_maintenance",
            enabled: false,
            model_profile_id: null,
            model_label: null,
            monthly_budget_usd: null,
            spent_this_month: "0",
            unavailable: null,
            managed_in: null,
            runs: [],
          },
        ],
      });
    if (url === "/orgs")
      return Promise.resolve({
        items: [{ id: "org-1", name: "Acme", avatar_color: null, ...configuration }],
        total: 1,
      });
    if (url.includes("/members")) {
      return Promise.resolve({
        items: [
          member(ME, "me@acme.test", role, mayChangeRole(role, role)),
          member("user-peer", "peer@acme.test", "admin", mayChangeRole(role, "admin")),
          member(
            "user-builder",
            "builder@acme.test",
            "builder",
            mayChangeRole(role, "builder"),
            "directory",
          ),
          member("user-owner", "owner@acme.test", "owner", mayChangeRole(role, "owner")),
        ],
        total: 4,
      });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

/**
 * `params` is a promise the page unwraps with `use`, so the first render
 * suspends - and a suspension inside a synchronous `act` never resolves. Awaited
 * here, which is what React's own warning asks for.
 */
async function mount(orgId = "org-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      {/* Before the page, as the dashboard layout has it: the guard adopts the
          organization the path names, and it has to happen before the page's
          own requests go out (#1032). */}
      <ActiveOrgGuard />
      <Suspense>{children}</Suspense>
    </QueryClientProvider>
  );
  const params = Promise.resolve({ id: orgId });
  const result: { view?: { rerender: (ui: ReactNode) => void } } = {};
  await act(async () => {
    result.view = render(<MembersPage params={params} />, { wrapper });
  });
  return () => result.view?.rerender(<MembersPage params={params} />);
}

/** The table cell holding `email`'s role. */
async function roleCell(email: string): Promise<HTMLElement> {
  const cell = await screen.findByText(email);
  const row = cell.closest("tr");
  if (row === null) throw new Error(`no row for ${email}`);
  return row as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  query.mockImplementation(() => new URLSearchParams());
  window.history.replaceState({}, "", "/orgs/org-1/members");
  path.mockReturnValue("/orgs/org-1/members");
  useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
  useAuthStore.setState({
    user: {
      id: ME,
      email: "me@acme.test",
      full_name: "Me",
      is_active: true,
      created_at: "2026-07-01T00:00:00Z",
    },
    isAuthenticated: true,
  });
});

describe("the members table's role control", () => {
  it("offers an Admin only the roles they outrank, on a row they may change", async () => {
    serve("admin");
    await mount();

    const row = await roleCell("builder@acme.test");
    await userEvent.click(within(row).getByRole("combobox"));

    const labels = screen.getAllByRole("option").map((option) => option.textContent?.trim());
    expect(labels).toEqual(["builder", "operator", "member", "viewer"]);
  });

  it("offers a peer Admin no control at all, because the server would refuse it", async () => {
    // This asserted the opposite until #700, on the reading that `change_role`
    // judges the role being handed out and not the one being replaced - so an
    // Admin demoting a peer Admin to Builder was a supported action a picker
    // ought to offer. It was the hole: `remove` refuses one Admin removing
    // another, and demote-then-remove took the same authority by another door.
    // The server now refuses it, so the row shows the role as a label.
    serve("admin");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByText("admin")).toBeVisible());
    expect(within(row).queryByRole("combobox")).toBeNull();
  });

  it("judges the organization in its URL, not whichever one is active", async () => {
    // #1032: `X-Organization-Id` names the *active* organization on every
    // request, and the organizations list opens any org's members page without
    // switching - so this page judged Acme's members by the caller's role in
    // Globex. The guard adopts the path's organization, so what the page offers
    // is what the caller may do *there*.
    //
    // The mock answers per organization, which is what makes the difference
    // visible: an Owner of the org in the URL, an Admin of the active one.
    const URL_ORG = "22222222-2222-2222-2222-222222222222";
    path.mockReturnValue(`/orgs/${URL_ORG}/members`);
    useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: [] });
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === "/users/me/console-experience") return Promise.resolve(CONSOLE_EXPERIENCE);
      if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
      if (url.startsWith("/me/permissions")) {
        const asked = useOrgStore.getState().activeOrgId;
        return Promise.resolve(permissionsOf(asked === URL_ORG ? "owner" : "admin"));
      }
      if (url === "/system-agents")
        return Promise.resolve({
          items: [
            {
              role: "memory_maintenance",
              enabled: false,
              model_profile_id: null,
              model_label: null,
              monthly_budget_usd: null,
              spent_this_month: "0",
              unavailable: null,
              managed_in: null,
              runs: [],
            },
          ],
        });
      if (url === "/orgs")
        return Promise.resolve({
          items: [
            { id: "org-1", name: "Globex", avatar_color: null },
            { id: URL_ORG, name: "Acme", avatar_color: null },
          ],
          total: 2,
        });
      if (url.includes("/members"))
        return Promise.resolve({
          items: [
            member(ME, "me@acme.test", "owner", mayChangeRole("owner", "owner")),
            member("user-peer", "peer@acme.test", "admin", mayChangeRole("owner", "admin")),
          ],
          total: 2,
        });
      return Promise.resolve({ items: [], total: 0 });
    });

    await mount(URL_ORG);

    const row = await roleCell("peer@acme.test");
    await userEvent.click(within(row).getByRole("combobox"));

    // An Owner's five, not an Admin's four - and `admin` selectable rather than
    // the disabled placeholder an Admin would see on this row.
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      "admin",
      "builder",
      "operator",
      "member",
      "viewer",
    ]);
    expect(options[0]).not.toHaveAttribute("data-disabled");
  });

  it("says so when the role catalog could not be read, rather than showing labels", async () => {
    // Offering nothing and being unable to answer are the same pixels and a
    // different fact.
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === "/users/me/console-experience") return Promise.resolve(CONSOLE_EXPERIENCE);
      if (url === "/roles/catalog") return Promise.reject(new Error("nope"));
      if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf("admin"));
      if (url === "/system-agents")
        return Promise.resolve({
          items: [
            {
              role: "memory_maintenance",
              enabled: false,
              model_profile_id: null,
              model_label: null,
              monthly_budget_usd: null,
              spent_this_month: "0",
              unavailable: null,
              managed_in: null,
              runs: [],
            },
          ],
        });
      if (url === "/orgs")
        return Promise.resolve({
          items: [{ id: "org-1", name: "Acme", avatar_color: null }],
          total: 1,
        });
      if (url.includes("/members"))
        return Promise.resolve({ items: [member(ME, "me@acme.test", "admin")], total: 1 });
      return Promise.resolve({ items: [], total: 0 });
    });
    await mount();

    expect(await screen.findByText(/role list could not be loaded/i)).toBeVisible();
  });

  it("marks a membership the directory sync maintains, beside its role", async () => {
    serve("admin");
    await mount();

    const builder = await roleCell("builder@acme.test");
    await waitFor(() => expect(within(builder).getByRole("combobox")).toBeVisible());
    const badge = within(builder).getByText("Directory");
    expect(badge.closest("[title]")).toHaveAttribute(
      "title",
      expect.stringContaining("Changing the role here takes it over"),
    );
    expect(within(await roleCell("peer@acme.test")).queryByText("Directory")).toBeNull();
  });

  it("marks it beside the plain label too, for a caller who cannot change it", async () => {
    serve("viewer");
    await mount();

    const builder = await roleCell("builder@acme.test");
    expect(within(builder).getByText("Directory")).toBeVisible();
    expect(within(builder).queryByRole("combobox")).toBeNull();
  });

  it("links to the groups for everyone, and to the directory only for a member manager", async () => {
    serve("viewer");
    await mount();

    expect(await screen.findByRole("link", { name: "Groups" })).toHaveAttribute(
      "href",
      "/orgs/org-1/groups",
    );
    expect(screen.queryByRole("link", { name: "Directory" })).toBeNull();
  });

  it("links a member manager to the directory mappings", async () => {
    serve("admin");
    await mount();

    expect(await screen.findByRole("link", { name: "Directory" })).toHaveAttribute(
      "href",
      "/orgs/org-1/directory",
    );
  });

  it("lets an Owner change a peer Admin, whose role they do outrank", async () => {
    serve("owner");
    await mount();

    const row = await roleCell("peer@acme.test");

    await waitFor(() => expect(within(row).getByRole("combobox")).toBeVisible());
  });
});

describe("organization settings tabs", () => {
  it("keeps setup controls outside the tablist", async () => {
    serve("owner", [{ permission: Perm.orgSettings, scope: "all" }]);
    await mount();
    await screen.findByRole("tab", { name: "AI & services" });
    expect(within(screen.getByRole("tablist")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("opens the workspace in a modal and guards closing an edited name", async () => {
    serve("owner");
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Edit workspace" }));
    const dialog = screen.getByRole("dialog", { name: "Edit workspace" });
    expect(within(dialog).queryByRole("heading", { name: "Voice" })).not.toBeInTheDocument();
    const name = within(dialog).getByDisplayValue("Acme");
    await userEvent.clear(name);
    await userEvent.type(name, "New workspace");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(dialog).toBeVisible();
    const store = (await import("@/stores/unsaved-changes-store")).useUnsavedChangesStore;
    expect(store.getState().prompt?.ids).toEqual(["org-profile:org-1"]);
    await act(async () => {
      await store.getState().answer("discard");
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit workspace" }));
    expect(screen.getByDisplayValue("Acme")).toBeVisible();
  });

  it("keeps public data controls reachable with only the settings grant", async () => {
    serve("viewer", [{ permission: Perm.orgSettings, scope: "all" }]);
    await mount();
    await userEvent.click(await screen.findByRole("tab", { name: "Budget and approvals" }));
    expect(screen.getByRole("switch", { name: "Public pages with live data" })).toBeVisible();
  });

  it("opens Voice in services from its legacy URL", async () => {
    query.mockImplementation(() => new URLSearchParams("tab=voice"));
    serve("owner", [{ permission: Perm.orgSettings, scope: "all" }]);
    await mount();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "AI & services" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(document.querySelector('[data-tour="org-voice"]')).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("follows a profile deep link without remounting", async () => {
    serve("viewer");
    const rerender = await mount();
    await screen.findByText("peer@acme.test");
    query.mockImplementation(() => new URLSearchParams("tab=profile"));
    await act(async () => {
      rerender();
    });
    expect(await screen.findByRole("dialog", { name: "Edit workspace" })).toBeVisible();
    expect(screen.getByDisplayValue("Acme")).toBeVisible();
  });

  it("combines service settings while preserving drafts across tabs and disclosure changes", async () => {
    serve(
      "owner",
      [
        { permission: Perm.orgSettings, scope: "all" },
        { permission: Perm.budgetsManage, scope: "all" },
      ],
      { proactive_model_profile_id: "profile-1" },
    );
    await mount();
    await screen.findByRole("tab", { name: "AI & services" });
    expect(screen.getAllByRole("tab").map((item) => item.textContent)).toEqual([
      "Members",
      "Budget and approvals",
      "AI & services",
    ]);
    await userEvent.click(screen.getByRole("tab", { name: "AI & services" }));
    const expand = screen.getByRole("button", {
      name: "Daily briefing & suggestions",
    });
    await userEvent.click(expand);
    const nightly = screen.getByRole("switch", { name: "Daily briefing & suggestions" });
    await userEvent.click(nightly);
    expect(nightly).toBeChecked();
    const limit = screen.getByLabelText("Limit per person (USD a month)");
    await userEvent.clear(limit);
    await userEvent.type(limit, "5");
    await userEvent.click(expand);
    expect(nightly).toBeVisible();
    expect(limit).not.toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "Members" }));
    await userEvent.click(screen.getByRole("tab", { name: "AI & services" }));
    await userEvent.click(expand);
    expect(nightly).toBeChecked();
    expect(nightly).toBeVisible();
    expect(limit).toHaveValue(5);
    expect(limit).toBeVisible();
  });

  it("uses one service-card header for all seven functions, with independent keyboard disclosures", async () => {
    serve(
      "owner",
      [
        { permission: Perm.orgSettings, scope: "all" },
        { permission: Perm.budgetsManage, scope: "all" },
      ],
      { welcome_dm_enabled: true },
    );
    const original = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === "/users/me/console-experience") return Promise.resolve(CONSOLE_EXPERIENCE);
      if (url === "/assistant")
        return Promise.resolve({
          status: "ready",
          agent_id: "architect",
          slug: "ai-architect",
          name: "Architect",
          named_by_default: true,
          greeting: null,
          avatar_url: null,
          avatar_color: null,
          wears_mark: true,
          can_use: true,
          can_configure: true,
        });
      return original(url);
    });
    await mount();
    await userEvent.click(await screen.findByRole("tab", { name: "AI & services" }));
    const titles = [
      "Memory maintenance",
      "AI Architect",
      "Daily briefing & suggestions",
      "Allow read-only monitoring routines",
      "Welcome message in chat apps",
      "Speech to text",
      "Text to speech",
    ];
    const headers: HTMLElement[] = [];
    for (const title of titles) {
      const card = await screen.findByRole("region", { name: title });
      expect(card).toHaveAttribute("data-slot", "service-card");
      const chatHome = screen.getByRole("region", { name: "Chat home" });
      expect(
        card.compareDocumentPosition(chatHome) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      const header = card.querySelector("header");
      expect(header).not.toBeNull();
      headers.push(header!);
      expect(header!.querySelector('[data-slot="service-icon"] > svg')).not.toBeNull();
      if (title === "AI Architect") {
        expect(within(header!).getByRole("link", { name: "Open in Agent Builder" })).toBeVisible();
        expect(within(header!).queryByRole("button", { name: title })).toBeNull();
        expect(within(header!).getByRole("switch")).toBeVisible();
        continue;
      }
      const trigger = within(header!).getByRole("button", { name: title });
      const toggle = within(header!).getByRole("switch");
      expect(trigger).not.toContainElement(toggle);
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      trigger.focus();
      await userEvent.keyboard("{Enter}");
      expect(trigger).toHaveAttribute("aria-expanded", "true");
      await userEvent.keyboard(" ");
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(toggle).toBeVisible();
    }
    expect(new Set(headers.map((header) => header.className)).size).toBe(1);
    expect(document.querySelectorAll('[data-slot="service-card"]')).toHaveLength(9);
  });

  it("groups background services without adding a second interactive disclosure", async () => {
    serve("viewer", [{ permission: Perm.budgetsManage, scope: "all" }]);
    await mount();
    await userEvent.click(await screen.findByRole("tab", { name: "AI & services" }));
    expect(screen.getByRole("heading", { name: "Background services", level: 2 })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Assistant and conversations", level: 2 }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Background services" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Memory maintenance/ }));
    expect(await screen.findByRole("region", { name: "Memory maintenance" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Voice" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI Architect" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Speech to text" })).not.toBeInTheDocument();
    expect(document.querySelectorAll('[data-slot="service-card"]')).toHaveLength(3);
  });

  it("shows actionable Voice setup without warning about disabled services", async () => {
    serve(
      "owner",
      [
        { permission: Perm.orgSettings, scope: "all" },
        { permission: Perm.budgetsManage, scope: "all" },
      ],
      {
        speech_to_text_provider: null,
        speech_to_text_model: null,
        speech_to_text_secret_id: null,
        proactive_enabled: false,
      },
    );
    await mount();
    const services = await screen.findByRole("tab", { name: "AI & services" });
    await waitFor(() =>
      expect(services).toHaveAccessibleDescription(/Voice has no default provider/),
    );
    expect(services).not.toHaveAccessibleDescription(/Nightly suggestions|Memory maintenance/);
    expect(screen.queryByRole("tab", { name: "Workspace" })).not.toBeInTheDocument();
  });

  it("filters members by name or email and role, with a recoverable empty result", async () => {
    serve("owner");
    await mount();
    await screen.findByText("peer@acme.test");
    const search = screen.getByPlaceholderText("Search members…");
    await userEvent.type(search, "PEER@");
    expect(screen.getByText("peer@acme.test")).toBeVisible();
    expect(screen.queryByText("builder@acme.test")).not.toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by role" }));
    await userEvent.click(screen.getByRole("option", { name: "builder" }));
    expect(screen.getByText("builder@acme.test")).toBeVisible();
    expect(screen.queryByText("peer@acme.test")).not.toBeInTheDocument();
    await userEvent.type(search, "missing");
    expect(screen.getByText("No members match your search.")).toBeVisible();
  });

  it.each(["voice", "governance", "proactivity", "assistant", "unknown"])(
    "falls back to members for unavailable tab %s",
    async (tab) => {
      query.mockImplementation(() => new URLSearchParams({ tab }));
      serve("viewer");
      await mount();
      await screen.findByText("peer@acme.test");
      expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getAllByRole("tab").map((item) => item.textContent)).toEqual(["Members"]);
    },
  );
});

it("shows the membership's onboarding status and readable current step", async () => {
  serve("owner");
  const fallback = vi.mocked(apiClient.get).getMockImplementation()!;
  vi.mocked(apiClient.get).mockImplementation((url) =>
    url.includes("/members")
      ? Promise.resolve({
          items: [
            {
              ...member(ME, "me@acme.test", "owner"),
              onboarding_completed_at: null,
              onboarding_current_step: "member.profile",
              onboarding_updated_at: "2026-11-22T10:00:00Z",
            },
          ],
          total: 1,
        })
      : fallback(url),
  );
  await mount();
  const row = await roleCell("me@acme.test");
  expect(within(row).getByText("In progress")).toBeVisible();
  expect(within(row).getByText("Your profile")).toBeVisible();
});
