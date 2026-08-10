import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpendByPerson } from "./spend-by-person";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";
import type { PersonUsageRow, UnattributedUsage } from "@/types/stats";

/**
 * Who is spending, on the Spend tab.
 *
 * The load-bearing case is the refusal: this breakdown names the organization's
 * people, so a caller without `runs:view` must not see it - and not by a request
 * that 403s after the card is on screen, but by the card never rendering and its
 * question never being asked. The rest proves it obeys the tab's window, and that
 * a failed request reads as a failure rather than as "nobody spent anything".
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn() } };
});

// Full-key echo, so a chrome string is assertable and unambiguous.
vi.mock("next-intl", () => ({
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
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => auth }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function holds(...held: Permission[]) {
  return (permission: Permission) => held.includes(permission);
}

const PEOPLE: PersonUsageRow[] = [
  {
    user_id: "u1",
    email: "k.nowak@example.com",
    full_name: "Katarzyna Nowak",
    runs: 24,
    cost_usd: "1.1000",
    last_run_at: "2026-08-04T09:30:00Z",
  },
  {
    user_id: "u2",
    email: "j.wisniewski@example.com",
    full_name: null,
    runs: 16,
    cost_usd: "0.5400",
    last_run_at: "2026-08-03T17:05:00Z",
  },
];

function serve(
  byUser: PersonUsageRow[] | null,
  active: number | null = null,
  unattributed: UnattributedUsage | null = null,
) {
  vi.mocked(apiClient.get).mockImplementation((_path: string, options?: unknown) => {
    const params = (options as { params?: Record<string, string> } | undefined)?.params;
    if (params?.group_by === "user")
      return Promise.resolve({ by_user: byUser, unattributed_usage: unattributed });
    return Promise.resolve({
      active_users: active === null ? null : { active, total_members: active },
    });
  });
}

function usageCalls() {
  return vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/stats/usage");
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  auth.can = () => true;
});

describe("the per-person spend breakdown", () => {
  it("names the people who spent, and what their runs cost", async () => {
    serve(PEOPLE);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    // Data-borne, not chrome: the names and figures came from the response.
    expect(await screen.findByText("Katarzyna Nowak")).toBeVisible();
    expect(screen.getByText("$1.1000")).toBeVisible();
    // No display name stored - the email identifies the person instead.
    expect(screen.getByText("j.wisniewski@example.com")).toBeVisible();
    expect(screen.getByText("pages.runs.perPersonDisclosure")).toBeVisible();
  });

  it("says how many people the top rows leave unnamed", async () => {
    // A card is not a directory: the org has more active people than it lists, and
    // it says so rather than reading as the whole organization.
    serve(PEOPLE, 5);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("pages.runs.othersRanAgents")).toBeVisible();
  });

  it("claims no others when the rows already name everyone active", async () => {
    serve(PEOPLE, 2);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("Katarzyna Nowak")).toBeVisible();
    expect(screen.queryByText("pages.runs.othersRanAgents")).toBeNull();
  });

  it("shows an unattributed bucket so the total reconciles with by agent", async () => {
    // A deleted user's runs and account-less runs are counted by the by-agent
    // card; the bucket keeps them visible here rather than silently dropped.
    serve(PEOPLE, 2, { runs: 5, cost_usd: "0.9000", last_run_at: "2026-08-05T12:00:00Z" });

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("pages.runs.spendUnattributed")).toBeVisible();
    expect(screen.getByText("$0.9000")).toBeVisible();
  });

  it("omits the unattributed bucket when every run has a named user", async () => {
    serve(PEOPLE, 2, null);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("Katarzyna Nowak")).toBeVisible();
    expect(screen.queryByText("pages.runs.spendUnattributed")).toBeNull();
  });

  it("asks /stats/usage for the org's people over the window it was handed", async () => {
    serve(PEOPLE);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    await waitFor(() => expect(usageCalls().length).toBeGreaterThan(0));
    const [, options] = usageCalls().find(
      ([, opts]) => (opts as { params?: Record<string, string> }).params?.group_by === "user",
    )!;
    const params = (options as { params: Record<string, string> }).params;
    expect(params.group_by).toBe("user");
    expect(params.scope).toBe("org");
    expect(params.from).toBe("2026-07-08");
    expect(params.to).toBe("2026-08-07");
  });

  it("is absent for a caller without runs:view, and never asks who spent", async () => {
    // The refusal that is the point: not disabled, not a 403 after the fact - the
    // card is not rendered and the question is never put to the server.
    auth.can = holds("agents:view", "agents:run");
    serve(PEOPLE);

    const { container } = render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Katarzyna Nowak")).toBeNull();
    expect(usageCalls()).toHaveLength(0);
  });

  it("says the request failed rather than that nobody spent anything", async () => {
    // The empty-state trap on a page about money: a 502 and a quiet month are the
    // same pixels unless the card keeps them apart.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("pages.runs.whoIsSpendingCouldNotBeRead")).toBeVisible();
    expect(screen.queryByText("pages.runs.nobodyHasRunAnything")).toBeNull();

    // Retry re-asks rather than sitting on the stale failure.
    const before = usageCalls().length;
    await userEvent.click(screen.getByRole("button", { name: "pages.runs.tryAgain" }));
    await waitFor(() => expect(usageCalls().length).toBeGreaterThan(before));
  });

  it("says nobody has run anything when the window is genuinely empty", async () => {
    serve([]);

    render(<SpendByPerson from="2026-07-08" to="2026-08-07" />, { wrapper });

    expect(await screen.findByText("pages.runs.nobodyHasRunAnything")).toBeVisible();
    expect(screen.queryByText("pages.runs.whoIsSpendingCouldNotBeRead")).toBeNull();
  });
});
