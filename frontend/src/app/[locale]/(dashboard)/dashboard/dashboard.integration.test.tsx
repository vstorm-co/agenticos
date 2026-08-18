import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TooltipProvider } from "@/components/ui";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "./page";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOrgStore } from "@/stores";
import type { Permission } from "@/types/permissions";

/**
 * The page's whole contract, per role: which sections render, which queries
 * are issued - and, just as deliberately, which are *not*. A viewer's browser
 * asking for /stats/usage would be a permission leak the backend happens to
 * catch; the assertion here is that the question is never asked at all.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Full-key echo, so "dashboard.errors.title" is assertable and unambiguous.
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: (namespace?: string) => (key: string) =>
    namespace ? `${namespace}.${key}` : key,
}));

const auth = {
  can: (_permission: Permission) => true,
  canAll: () => true,
  scopeOf: () => "all" as const,
  role: "owner",
  isAppAdmin: false,
  isLoading: false,
  error: null,
};
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => auth,
}));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/dashboard",
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // The same two providers `app/providers.tsx` mounts around the real page.
  // Every widget header carries a tooltip for its explanation, and Radix throws
  // rather than degrading when one is rendered outside a provider.
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}

function holds(...held: Permission[]) {
  return (permission: Permission) => held.includes(permission);
}

const USAGE = {
  from: "2026-07-07",
  to: "2026-08-05",
  scope: "org",
  total_runs: 40,
  previous_total_runs: 31,
  by_day: [{ date: "2026-08-01", runs: 40 }],
  by_surface: [{ surface: "web", runs: 40 }],
  by_agent: [{ agent_id: "a1", name: "Support triage", runs: 40 }],
  by_status: [
    { status: "completed", runs: 36 },
    { status: "failed", runs: 2 },
    { status: "budget_exceeded", runs: 1 },
    { status: "awaiting_approval", runs: 1 },
  ],
  by_model: [{ model_label: "claude-sonnet-5", runs: 40 }],
  latency_ms: { p50: 3200, p95: 14800 },
  cost: {
    period_usd: "1.64",
    previous_period_usd: "1.24",
    by_provider: [{ provider: "anthropic", cost_usd: "1.64" }],
  },
  active_users: { active: 14, total_members: 23 },
  pending_approvals: null,
  agent_id: null,
  by_version: null,
  by_user: null,
};

const PEOPLE = [
  {
    user_id: "u1",
    email: "k.nowak@example.com",
    full_name: "Katarzyna Nowak",
    runs: 24,
    cost_usd: "1.10",
    last_run_at: "2026-08-04T09:30:00Z",
  },
  {
    user_id: "u2",
    email: "j.wisniewski@example.com",
    full_name: null,
    runs: 16,
    cost_usd: "0.54",
    last_run_at: "2026-08-03T17:05:00Z",
  },
];

const RATINGS = {
  from: "2026-07-07",
  to: "2026-08-05",
  scope: "org",
  total_ratings: 12,
  like_count: 11,
  dislike_count: 1,
  average_rating: 0.83,
  with_comments: 0,
  ratings_by_day: [{ date: "2026-08-01", likes: 11, dislikes: 1 }],
};

// The caller's saved arrangement, as GET /me/dashboard-layout would answer.
// `null` is the common case - no saved layout, so the audience default stands.
// A test sets it to a StoredLayout to exercise the personalization layer.
let savedLayout: { entries: { widget: string; span: string; rows?: string }[] } | null = null;

// The caller's named presets, as GET /me/dashboard-layout/presets would answer.
let presets: { items: { id: string; name: string; entries: unknown[] }[]; total: number } = {
  items: [],
  total: 0,
};

function respond(path: string, options?: { params?: Record<string, string> }): unknown {
  if (path === "/me/dashboard-layout") return savedLayout;
  if (path === "/me/dashboard-layout/presets") return presets;
  // The sandbox cards carry their query in the path rather than in params, so
  // they are matched before the switch. What they answer is exercised properly in
  // `widgets/sandbox.integration.test.tsx`; here it only has to be well-shaped.
  if (path.startsWith("/sandbox-connections/")) {
    return path.includes("/policy")
      ? { kind: "docker", runtimes: [], default_runtime: null, max_sessions_per_tenant: 8 }
      : { sessions: [], limit: null, open_limit: null, tenant_limit: 8 };
  }
  switch (path) {
    case "/sandbox-connections":
      return {
        items: [
          { id: "sb1", name: "Local Docker", kind: "docker", is_default: true, is_active: true },
        ],
        total: 1,
      };
    case "/stats/usage":
      if (options?.params?.group_by === "user") {
        return { ...USAGE, by_user: PEOPLE };
      }
      if (options?.params?.group_by === "version") {
        return { ...USAGE, by_version: [], agent_id: options.params.agent_id };
      }
      if (options?.params?.scope === "own") {
        return { ...USAGE, scope: "own", active_users: null, pending_approvals: 2 };
      }
      return USAGE;
    case "/ratings/summary":
      return { ...RATINGS, scope: options?.params?.scope ?? "org" };
    case "/approvals":
      return {
        items: [
          {
            id: "ap1",
            run_id: "r1",
            agent_id: "a1",
            tool_id: "send_email",
            tool_args: {},
            status: "pending",
            created_at: "2026-08-05T08:00:00Z",
          },
        ],
        total: 3,
      };
    case "/spend":
      return {
        period_days: 30,
        month_to_date_usd: "142.63",
        by_agent: [],
        by_provider: [],
        by_key: [],
      };
    case "/agents":
      return {
        items: [
          {
            id: "a1",
            slug: "support",
            name: "Support triage",
            description: null,
            status: "published",
            visibility: "org",
            owner_user_id: "u2",
            current_version_id: "v1",
          },
        ],
        total: 4,
      };
    case "/kb":
      return { items: [{ id: "k1" }, { id: "k2" }, { id: "k3" }] };
    case "/skills":
      return { items: [], total: 6 };
    case "/conversations":
      return {
        items: [
          {
            id: "c1",
            title: "Q3 pipeline summary",
            created_at: "2026-08-05T08:00:00Z",
            updated_at: "2026-08-05T08:00:00Z",
            is_archived: false,
          },
        ],
      };
    case "/orgs":
      return { items: [{ id: "org1", name: "Acme Corp", monthly_budget_usd: 180 }] };
    case "/orgs/org1/members":
      return {
        items: [
          {
            id: "m1",
            organization_id: "org1",
            user_id: "u1",
            role: "owner",
            email: "owner@acme.test",
            full_name: null,
            avatar_url: null,
            joined_at: "2026-01-01T00:00:00Z",
          },
          {
            id: "m2",
            organization_id: "org1",
            user_id: "u2",
            role: "member",
            email: "member@acme.test",
            full_name: null,
            avatar_url: null,
            joined_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 2,
      };
    case "/mcp-connections":
      return { items: [], total: 0 };
    case "/rag/sync/sources":
      return { items: [], total: 0 };
    case "/admin/stats":
      return {
        total_organizations: 12,
        total_users: 247,
        active_users_24h: 41,
        total_agents: 86,
        total_conversations: 1912,
      };
    case "/admin/system":
      return {
        checked_at: "2026-08-05T08:00:00Z",
        checks: [{ key: "database", status: "healthy", detail: "", latency_ms: 3 }],
      };
    case "/admin/organizations":
      return {
        items: [
          {
            id: "org1",
            name: "Acme Corp",
            slug: "acme",
            is_personal: false,
            member_count: 23,
            agent_count: 14,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      };
    case "/admin/ratings/summary":
      return RATINGS;
    default:
      return { items: [], total: 0 };
  }
}

function callsTo(path: string) {
  return vi.mocked(apiClient.get).mock.calls.filter(([requested]) => requested === path);
}

beforeEach(() => {
  params.delete("period");
  params.delete("sections");
  savedLayout = null;
  presets = { items: [], total: 0 };
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(apiClient.put).mockReset();
  vi.mocked(apiClient.delete).mockReset();
  vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) =>
    Promise.resolve(respond(path, options as { params?: Record<string, string> })),
  );
  vi.mocked(apiClient.post).mockResolvedValue({ id: "p1", name: "Monday review", entries: [] });
  vi.mocked(apiClient.put).mockImplementation((_path: string, body?: unknown) =>
    Promise.resolve(body as { entries: unknown[] }),
  );
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  useOrgStore.setState({ activeOrgId: "org1" });
  useAuthStore.setState({ user: { id: "u1" } as never });
  auth.can = () => true;
  auth.role = "owner";
  auth.isAppAdmin = false;
  auth.isLoading = false;
});

describe("the steward's dashboard", () => {
  it("renders the five sections and reads org-scoped usage", async () => {
    render(<DashboardPage />, { wrapper });

    expect(screen.getByText("dashboard.sections.attention")).toBeInTheDocument();
    expect(screen.getByText("dashboard.sections.usage")).toBeInTheDocument();
    expect(screen.getByText("dashboard.sections.people")).toBeInTheDocument();
    expect(screen.getByText("dashboard.sections.sandboxes")).toBeInTheDocument();
    expect(screen.getByText("dashboard.sections.workspace")).toBeInTheDocument();
    expect(screen.queryByText("dashboard.sections.deployment")).not.toBeInTheDocument();

    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    const orgCalls = callsTo("/stats/usage").filter(
      ([, options]) => (options as { params: Record<string, string> }).params.scope === "org",
    );
    expect(orgCalls.length).toBeGreaterThan(0);
    expect(callsTo("/admin/stats")).toHaveLength(0);

    // Data-borne proof, not chrome: the agent's name arrived from /agents.
    expect((await screen.findAllByText("Support triage")).length).toBeGreaterThan(0);
  });

  it("names the people who used it, and says how far the list reaches", async () => {
    render(<DashboardPage />, { wrapper });

    expect(await screen.findByText("Katarzyna Nowak")).toBeInTheDocument();
    // No display name stored, so the row is the address - drawn by the shared
    // `MemberIdentity`, which is why it reads as the local part with the face
    // beside it rather than as a bare mailbox. The whole product identifies a
    // person that way; this card used to print a name and nothing else, which
    // cannot tell two colleagues called Bob apart.
    expect(screen.getByText("j.wisniewski")).toBeInTheDocument();
    // The one card that answers with names carries its own audience note.
    expect(screen.getByText("dashboard.widgets.top-people.disclosure")).toBeInTheDocument();

    const [, options] = callsTo("/stats/usage").find(
      ([, opts]) => (opts as { params: Record<string, string> }).params.group_by === "user",
    )!;
    expect((options as { params: Record<string, string> }).params.limit).toBe("6");
  });

  it("a 502 on the stats endpoint costs the usage cards, not the page", async () => {
    vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) =>
      path === "/stats/usage"
        ? Promise.reject(new Error("502"))
        : Promise.resolve(respond(path, options as { params?: Record<string, string> })),
    );

    render(<DashboardPage />, { wrapper });

    const failures = await screen.findAllByText("dashboard.errors.title");
    expect(failures.length).toBeGreaterThan(0);
    // The cards on other endpoints are unaffected - every card fails alone.
    expect(
      (await screen.findAllByText("dashboard.widgets.approvals.wants")).length,
    ).toBeGreaterThan(0);
    expect((await screen.findAllByText("Support triage")).length).toBeGreaterThan(0);

    const before = callsTo("/stats/usage").length;
    const retry = (await screen.findAllByText("dashboard.errors.retry"))[0];
    await userEvent.click(retry!);
    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(before));
  });

  it("switching the period asks the window again and writes the URL", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    render(<DashboardPage />, { wrapper });
    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    const before = callsTo("/stats/usage").length;

    await userEvent.click(screen.getByText("dashboard.period.7d"));

    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(before));
    const lastUrl = String(replaceState.mock.calls.at(-1)?.[2] ?? "");
    expect(lastUrl).toContain("period=7d");
    replaceState.mockRestore();
  });

  it("the sections URL filter hides sections but can never reveal one", async () => {
    params.set("sections", "usage,deployment");

    render(<DashboardPage />, { wrapper });

    expect(screen.getByText("dashboard.sections.usage")).toBeInTheDocument();
    expect(screen.queryByText("dashboard.sections.attention")).not.toBeInTheDocument();
    // "deployment" is somebody else's section; a pasted URL cannot conjure it.
    expect(screen.queryByText("dashboard.sections.deployment")).not.toBeInTheDocument();
  });
});

describe("the sandbox section", () => {
  it("is there for an operator, who holds connections:view, and asks the host about itself", async () => {
    // The audience #129 wrote the cards for: an operator watches where agents
    // run without the manage authority to point a host somewhere.
    auth.role = "operator";
    auth.can = holds(
      "agents:view",
      "agents:run",
      "approvals:decide",
      "runs:view",
      "connections:view",
    );

    render(<DashboardPage />, { wrapper });

    expect(screen.getByText("dashboard.sections.sandboxes")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/sandbox-connections").length).toBeGreaterThan(0));
  });

  it("is absent without connections:view, and the browser never asks where agents run code", async () => {
    // Not rendered, not rendered-then-403: the operator layout lists the
    // section, so this proves the per-widget gate withholds it when the read is
    // missing rather than the layout simply omitting it.
    auth.role = "operator";
    auth.can = holds("agents:view", "agents:run", "approvals:decide", "runs:view");

    render(<DashboardPage />, { wrapper });

    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    expect(screen.queryByText("dashboard.sections.sandboxes")).not.toBeInTheDocument();
    expect(callsTo("/sandbox-connections")).toHaveLength(0);
  });
});

describe("the app admin's dashboard", () => {
  it("adds the deployment strip and the organization divider", async () => {
    auth.isAppAdmin = true;
    auth.role = "";

    render(<DashboardPage />, { wrapper });

    expect(screen.getByText("dashboard.sections.deployment")).toBeInTheDocument();
    expect(screen.getByText("dashboard.orgDivider.label")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/admin/stats").length).toBeGreaterThan(0));
  });
});

describe("the viewer's dashboard", () => {
  it("shows the shared shelf and asks no org-analytics question at all", async () => {
    auth.role = "viewer";
    auth.can = holds("agents:view", "collections:view");

    render(<DashboardPage />, { wrapper });

    // The my-agents card under its overridden title.
    expect(screen.getByText("dashboard.widgets.my-agents.sharedTitle")).toBeInTheDocument();
    await waitFor(() => expect(callsTo("/agents").length).toBeGreaterThan(0));

    // Not merely unrendered - never fetched.
    expect(callsTo("/stats/usage")).toHaveLength(0);
    expect(callsTo("/approvals")).toHaveLength(0);
    expect(callsTo("/spend")).toHaveLength(0);
    expect(callsTo("/orgs/org1/members")).toHaveLength(0);
    expect(callsTo("/admin/stats")).toHaveLength(0);
  });
});

describe("the member's dashboard", () => {
  it("asks for usage and quality only at own scope", async () => {
    auth.role = "member";
    auth.can = holds("agents:view", "agents:edit", "agents:run", "collections:view");

    render(<DashboardPage />, { wrapper });

    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    for (const [, options] of callsTo("/stats/usage")) {
      expect((options as { params: Record<string, string> }).params.scope).toBe("own");
    }
    await waitFor(() => expect(callsTo("/ratings/summary").length).toBeGreaterThan(0));
    for (const [, options] of callsTo("/ratings/summary")) {
      expect((options as { params: Record<string, string> }).params.scope).toBe("own");
    }
    expect(callsTo("/approvals")).toHaveLength(0);
    expect(callsTo("/orgs/org1/members")).toHaveLength(0);
  });

  it("never asks who else is using it", async () => {
    auth.role = "member";
    auth.can = holds("agents:view", "agents:edit", "agents:run", "collections:view");

    render(<DashboardPage />, { wrapper });

    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    const named = callsTo("/stats/usage").filter(
      ([, options]) => (options as { params: Record<string, string> }).params.group_by === "user",
    );
    expect(named).toHaveLength(0);
  });
});

describe("the arrangeable dashboard", () => {
  it("drops a widget a stored layout names but the caller may no longer see", async () => {
    // The test the feature rests on: a person arranged their page as an admin,
    // was demoted to member, and their saved layout still names the approvals
    // queue. The gate runs last, so it is dropped at render - and never fetched.
    savedLayout = {
      entries: [
        { widget: "approvals", span: "s7" },
        { widget: "my-agents", span: "s6" },
      ],
    };
    auth.role = "member";
    auth.can = holds("agents:view", "agents:run");

    render(<DashboardPage />, { wrapper });

    // The saved arrangement settles in: the member default's other cards give
    // way to the two the person saved (of which only one survives the gate).
    await waitFor(() => expect(screen.queryByText("Q3 pipeline summary")).not.toBeInTheDocument());
    // The forbidden widget is not merely unrendered - its query was never issued,
    // even though the stored layout asked for it.
    expect(callsTo("/approvals")).toHaveLength(0);
    // The permitted one did render.
    expect(callsTo("/agents").length).toBeGreaterThan(0);
  });

  it("renders a saved arrangement as one flat page, without section headings", async () => {
    savedLayout = {
      entries: [
        { widget: "spend", span: "s6" },
        { widget: "runs", span: "s8" },
      ],
    };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });

    // The steward default's section spine gives way to the person's own flat
    // arrangement - the cards render, the headings do not.
    await waitFor(() =>
      expect(screen.queryByText("dashboard.sections.usage")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("dashboard.widgets.runs.title")).toBeInTheDocument();
  });

  it("drops a widget id the registry no longer knows and renders the rest", async () => {
    savedLayout = {
      entries: [
        { widget: "a-widget-that-was-removed", span: "s6" },
        { widget: "runs", span: "s8" },
      ],
    };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });

    // The unknown id is dropped rather than rendered as a blank card; the known
    // one still renders.
    expect(await screen.findByText("dashboard.widgets.runs.title")).toBeInTheDocument();
  });

  it("offers reset, not a blank page, when a person has hidden everything", async () => {
    savedLayout = { entries: [] };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });

    expect(await screen.findByText("dashboard.edit.emptyTitle")).toBeInTheDocument();
    expect(screen.getByText("dashboard.edit.reset")).toBeInTheDocument();
  });

  it("does not offer a widget the caller cannot see in the add catalog", async () => {
    // The catalog is a second surface with the same secrets: a member must not
    // be offered the deployment strip they could never render.
    auth.role = "member";
    auth.can = holds("agents:view", "agents:run");

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.my-agents.title");

    await userEvent.click(screen.getByText("dashboard.edit.customize"));
    await userEvent.click(screen.getByText("dashboard.edit.addWidget"));

    // Scope to the catalog list: opening the dialog focuses the first row, which
    // previews that widget alongside - so the widget's own title also appears in
    // the preview pane, and the guarantee under test is about the *offer* list.
    const dialog = await screen.findByRole("dialog");
    const catalog = within(dialog).getByRole("group", { name: "dashboard.edit.addTitle" });
    expect(within(catalog).queryByText("dashboard.widgets.platform.title")).not.toBeInTheDocument();
    expect(within(catalog).getByText("dashboard.widgets.my-agents.title")).toBeInTheDocument();
  });

  it("renders a saved arrangement at the heights the person chose", async () => {
    savedLayout = {
      entries: [
        { widget: "runs", span: "s8", rows: "r5" },
        { widget: "spend", span: "s6", rows: "r2" },
      ],
    };
    auth.role = "owner";

    const { container } = render(<DashboardPage />, { wrapper });

    // The stored height reaches the grid as a row-span class, not just the width.
    await waitFor(() => expect(container.querySelector(".lg\\:row-span-5")).toBeTruthy());
    expect(container.querySelector(".lg\\:row-span-2")).toBeTruthy();
  });

  it("edit mode shows the real cards, not placeholders, so arranging is not blind", async () => {
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.runs.title");

    await userEvent.click(screen.getByText("dashboard.edit.customize"));

    // The editor mounts the live widget - its data-borne text is on screen while
    // arranging, and the widget's own query was issued.
    await waitFor(() => expect(callsTo("/stats/usage").length).toBeGreaterThan(0));
    expect((await screen.findAllByText("dashboard.widgets.runs.title")).length).toBeGreaterThan(0);
  });
});

describe("the saved-dashboards switcher", () => {
  it("applies a preset by writing its entries as the active arrangement", async () => {
    presets = {
      items: [
        {
          id: "p1",
          name: "Monday review",
          entries: [{ widget: "spend", span: "s6", rows: "r3" }],
        },
      ],
      total: 1,
    };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.runs.title");

    await userEvent.click(screen.getByText("dashboard.presets.menu"));
    await userEvent.click(await screen.findByText("Monday review"));

    // Applying is a PUT of the preset's entries - the one write path the active
    // arrangement has.
    await waitFor(() =>
      expect(
        vi.mocked(apiClient.put).mock.calls.some(([path]) => path === "/me/dashboard-layout"),
      ).toBe(true),
    );
    const [, body] = vi
      .mocked(apiClient.put)
      .mock.calls.find(([path]) => path === "/me/dashboard-layout")!;
    expect(body).toEqual({ entries: [{ widget: "spend", span: "s6", rows: "r3" }] });
  });

  it("drops a retired widget when applying a preset saved before it was retired", async () => {
    presets = {
      items: [
        {
          id: "p1",
          name: "Old setup",
          entries: [
            { widget: "a-widget-that-was-removed", span: "s6", rows: "r3" },
            { widget: "runs", span: "s8", rows: "r3" },
          ],
        },
      ],
      total: 1,
    };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.runs.title");

    await userEvent.click(screen.getByText("dashboard.presets.menu"));
    await userEvent.click(await screen.findByText("Old setup"));

    // The unknown id is sanitized out before the write, so the apply succeeds
    // with the widgets that still exist rather than 422-ing the whole preset.
    await waitFor(() =>
      expect(
        vi.mocked(apiClient.put).mock.calls.some(([path]) => path === "/me/dashboard-layout"),
      ).toBe(true),
    );
    const [, body] = vi
      .mocked(apiClient.put)
      .mock.calls.find(([path]) => path === "/me/dashboard-layout")!;
    expect(body).toEqual({ entries: [{ widget: "runs", span: "s8", rows: "r3" }] });
  });

  it("returns to the audience default from the switcher", async () => {
    savedLayout = { entries: [{ widget: "spend", span: "s6", rows: "r3" }] };
    presets = { items: [], total: 0 };
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.spend.title");

    await userEvent.click(screen.getByText("dashboard.presets.menu"));
    await userEvent.click(await screen.findByText("dashboard.presets.default"));

    await waitFor(() =>
      expect(
        vi.mocked(apiClient.delete).mock.calls.some(([path]) => path === "/me/dashboard-layout"),
      ).toBe(true),
    );
  });

  it("saves the current arrangement as a named preset without leaving edit mode", async () => {
    auth.role = "owner";

    render(<DashboardPage />, { wrapper });
    await screen.findByText("dashboard.widgets.runs.title");

    await userEvent.click(screen.getByText("dashboard.edit.customize"));
    await userEvent.click(screen.getByText("dashboard.edit.saveAsPreset"));

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("dashboard.presets.nameLabel"), "Q3 review");
    await userEvent.click(within(dialog).getByText("dashboard.edit.save"));

    await waitFor(() =>
      expect(
        vi
          .mocked(apiClient.post)
          .mock.calls.some(([path]) => path === "/me/dashboard-layout/presets"),
      ).toBe(true),
    );
    const [, body] = vi
      .mocked(apiClient.post)
      .mock.calls.find(([path]) => path === "/me/dashboard-layout/presets")!;
    expect((body as { name: string }).name).toBe("Q3 review");
    // Still in edit mode - Save as… does not leave.
    expect(screen.getByText("dashboard.edit.saveAsPreset")).toBeInTheDocument();
  });
});
