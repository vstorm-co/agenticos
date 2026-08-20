import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  organizationInPath,
  refusesOrganization,
  useActiveOrganizationRecovery,
} from "./use-active-organization";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useAgentSelectionStore, useConversationStore, useOrgStore } from "@/stores";

vi.mock("@/lib/api-client", async () => {
  const { ApiError } = await import("@/lib/api-error");
  return { apiClient: { get: vi.fn() }, ApiError };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The path decides the tenant now, so this file needs to move it. The other
// exports are the ones `vitest.setup.ts` provides for the same reason it does:
// next-intl's `createNavigation` reads them at module scope.
const path = vi.fn(() => "/");
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => path(),
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const STALE = "11111111-1111-1111-1111-111111111111";
const PERSONAL = "22222222-2222-2222-2222-222222222222";

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The 404 `get_active_organization` raises for an id the caller cannot use. */
function organizationRefused(orgId: string) {
  const body = {
    error: {
      code: "NOT_FOUND",
      message: "Organization not found or access denied",
      details: { org_id: orgId },
    },
  };
  return new ApiError(404, body.error.message, body);
}

/** `/orgs` still answers when the active organization does not - it is keyed on the caller. */
function answerWith(orgs: Array<{ id: string; is_personal: boolean }>, permissions: unknown) {
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === "/orgs") {
      return Promise.resolve({
        items: orgs.map((org) => ({ ...org, name: `Org ${org.id.slice(0, 4)}` })),
        total: orgs.length,
      });
    }
    if (endpoint === "/me/permissions") {
      return permissions instanceof Error
        ? Promise.reject(permissions)
        : Promise.resolve(permissions);
    }
    throw new Error(`unexpected request to ${endpoint}`);
  });
}

describe("refusesOrganization", () => {
  it("recognises the server refusing the organization we are holding", () => {
    expect(refusesOrganization(organizationRefused(STALE), STALE)).toBe(true);
  });

  it("ignores a 404 about a different organization", () => {
    // A response to a request that was already in flight when the user
    // switched. Acting on it would move them off the org they just chose.
    expect(refusesOrganization(organizationRefused(PERSONAL), STALE)).toBe(false);
  });

  it("ignores a 404 that names no organization", () => {
    // "Run not found" is also a 404. Reassigning somebody's organization
    // because an agent id was mistyped is the failure this rules out.
    const missingRun = new ApiError(404, "Run not found", {
      error: { code: "NOT_FOUND", message: "Run not found", details: { run_id: "r1" } },
    });
    expect(refusesOrganization(missingRun, STALE)).toBe(false);
  });

  it("ignores a server fault", () => {
    // The organization may be perfectly fine; the server is not. Clearing the
    // selection here would turn an outage into a silent tenant switch.
    const broken = new ApiError(500, "Internal server error", {
      error: { code: "INTERNAL_ERROR", message: "Internal server error", details: null },
    });
    expect(refusesOrganization(broken, STALE)).toBe(false);
  });

  it("ignores a dropped connection", () => {
    // fetch rejects with a TypeError, which carries no status at all.
    expect(refusesOrganization(new TypeError("Failed to fetch"), STALE)).toBe(false);
  });

  it("does nothing when no organization is selected", () => {
    expect(refusesOrganization(organizationRefused(STALE), null)).toBe(false);
  });
});

describe("organizationInPath", () => {
  const ORG = "33333333-3333-3333-3333-333333333333";

  it("reads the organization a members or roles page names", () => {
    expect(organizationInPath(`/orgs/${ORG}/members`)).toBe(ORG);
    expect(organizationInPath(`/orgs/${ORG}/roles`)).toBe(ORG);
    expect(organizationInPath(`/orgs/${ORG}`)).toBe(ORG);
  });

  it("reads one through a locale prefix", () => {
    // `next/navigation` keeps the prefix, and `/pl/orgs/{id}` names the same
    // organization as `/orgs/{id}`.
    expect(organizationInPath(`/pl/orgs/${ORG}/members`)).toBe(ORG);
  });

  it("names none where the path names none", () => {
    expect(organizationInPath("/orgs")).toBeNull();
    expect(organizationInPath("/agents")).toBeNull();
    expect(organizationInPath("/")).toBeNull();
    expect(organizationInPath(`/agents/${ORG}`)).toBeNull();
  });

  it("takes a UUID and nothing else", () => {
    // A later `/orgs/new` would otherwise be adopted as a tenant id and
    // refused on every request the page made.
    expect(organizationInPath("/orgs/new")).toBeNull();
    expect(organizationInPath("/orgs/new/members")).toBeNull();
  });
});

describe("useActiveOrganizationRecovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
    path.mockReturnValue("/");
    client = new QueryClient({
      // Matching `app/providers.tsx`. At the library default of 0 a switch
      // refetches whether or not anything dropped the cache, which is the
      // harness answering the question instead of the code.
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
    });
  });

  it("drops what one organization cached when the caller switches to another", async () => {
    // Most keys do not name the organization, so without this the switch
    // changes a label and nothing else: `agents.list()` is the same key in
    // both, and at a five-minute `staleTime` nothing goes back to the server.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    const { rerender } = renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    client.setQueryData(["agents", "list", false], [{ id: "a-1", name: "Org A's agent" }]);

    useOrgStore.setState({ activeOrgId: STALE });
    rerender();

    // Removed, not marked stale: an invalidated query still serves its rows
    // while the refetch is in flight, which is the previous tenant on screen.
    await waitFor(() => expect(client.getQueryData(["agents", "list", false])).toBeUndefined());
  });

  it("empties the stores the query cache cannot reach", async () => {
    // A conversation, a chat transcript, an open preview and the sources
    // behind the last answer all belong to a tenant and none of them live in
    // the query cache - they are module-scope stores, so `removeQueries` goes
    // straight past them and organization A's chat stayed on screen under B.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    const { rerender } = renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    useConversationStore.getState().setCurrentConversationId("c-1");
    useAgentSelectionStore.getState().select("agent-1");

    useOrgStore.setState({ activeOrgId: STALE });
    rerender();

    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useAgentSelectionStore.getState().selectedAgentId).toBeNull();
  });

  it("leaves a mounted page asking again rather than showing nothing", async () => {
    // Dropping the data is only half an answer if the page then sits empty.
    // The claim is that every mounted query refetches, so this renders one.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    const agents = vi.fn().mockResolvedValue([{ id: "a-1" }]);
    const { result, rerender } = renderHook(
      () => {
        useActiveOrganizationRecovery();
        return useQuery({ queryKey: ["agents", "list", false], queryFn: agents });
      },
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toEqual([{ id: "a-1" }]));

    useOrgStore.setState({ activeOrgId: STALE });
    rerender();

    await waitFor(() => expect(agents).toHaveBeenCalledTimes(2));
  });

  it("drops the cache when the selection falls back to no organization at all", async () => {
    // The recovery sets `null` when there is no organization left to move to,
    // and `null` is not "no tenant" - the requests that follow are read as the
    // personal one. Without resolving it, this looked like "cannot tell yet"
    // and the organization just left stayed on screen.
    answerWith(
      [
        { id: PERSONAL, is_personal: true },
        { id: STALE, is_personal: false },
      ],
      { permissions: [] },
    );
    useOrgStore.setState({ activeOrgId: STALE });
    const { rerender } = renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    client.setQueryData(["agents", "list", false], [{ id: "a-1" }]);

    useOrgStore.setState({ activeOrgId: null });
    rerender();

    await waitFor(() => expect(client.getQueryData(["agents", "list", false])).toBeUndefined());
  });

  it("leaves the cache alone on the first render, when nothing has moved", async () => {
    // A page load starts with its own queries already in flight. Treating the
    // mount as a switch would cancel the fetch the page just made.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    const { rerender } = renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    client.setQueryData(["agents", "list", false], [{ id: "a-1" }]);

    rerender();

    expect(client.getQueryData(["agents", "list", false])).toEqual([{ id: "a-1" }]);
  });

  it("treats no selection and the personal organization as the same tenant", async () => {
    // Until the list loads there is no selection, and a request without
    // `X-Organization-Id` is read as the personal organization - so adopting
    // its id is a page finishing its first render, not a tenant switch. The
    // e2e seed caught this: it dropped the queries a freshly loaded page had
    // just started, and a secret that had been stored never appeared.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: null });
    const { rerender } = renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    client.setQueryData(["secrets", "list"], [{ id: "s-1" }]);

    useOrgStore.setState({ activeOrgId: PERSONAL });
    rerender();

    expect(client.getQueryData(["secrets", "list"])).toEqual([{ id: "s-1" }]);
  });

  it("falls back to an organization the caller belongs to", async () => {
    // The reported failure: a persisted org id outlived the org. `can()` is
    // false while permissions are unavailable, so a permanent refusal
    // permanently empties the sidebar - Agents, Skills, Activity, Knowledge
    // bases, RAG search, providers and MCP servers - with nothing said.
    useOrgStore.setState({ activeOrgId: STALE });
    answerWith([{ id: PERSONAL, is_personal: true }], organizationRefused(STALE));

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(PERSONAL));
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Switched to"));
  });

  it("says what happened rather than switching silently", async () => {
    useOrgStore.setState({ activeOrgId: STALE });
    answerWith([{ id: PERSONAL, is_personal: true }], organizationRefused(STALE));

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("no longer have access"));
  });

  it("clears the selection when there is nothing to fall back to", async () => {
    // Removed from their only organization. Clearing is still the right move:
    // with no header the server serves their personal organization.
    useOrgStore.setState({ activeOrgId: STALE });
    answerWith([], organizationRefused(STALE));

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(useOrgStore.getState().refusedOrgIds).toEqual([STALE]));
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("adopts the organization a page names, so the page judges its own tenant", async () => {
    // The whole of #1032: `/orgs/{B}/members` acted on B and read permissions
    // for whatever was active, and the organizations list opens that page
    // without switching - so an Owner of B was judged by their role in A.
    const OTHER = "33333333-3333-3333-3333-333333333333";
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    path.mockReturnValue(`/orgs/${OTHER}/members`);

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(OTHER));
  });

  it("leaves the selection alone on a page that names no organization", async () => {
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    path.mockReturnValue("/agents");

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(PERSONAL));
  });

  it("does not adopt an organization the server has already refused", async () => {
    // Otherwise opening its page hands the selection straight back to the one
    // the recovery has just moved off, which is how a switch loop starts.
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL, refusedOrgIds: [STALE] });
    path.mockReturnValue(`/orgs/${STALE}/members`);

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(PERSONAL));
  });

  it("keeps what a page loaded directly cached, rather than dropping it a commit later", async () => {
    // The cache's tenant is the URL's organization from the first commit, so
    // the reset does not fire on top of the requests the page has just started
    // - the failure mode the first-tenant skip exists for.
    const OTHER = "33333333-3333-3333-3333-333333333333";
    answerWith([{ id: PERSONAL, is_personal: true }], { permissions: [] });
    useOrgStore.setState({ activeOrgId: PERSONAL });
    path.mockReturnValue(`/orgs/${OTHER}/members`);

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });
    client.setQueryData(["agents", "list", false], [{ id: "a-1", name: "The page's own read" }]);

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(OTHER));
    expect(client.getQueryData(["agents", "list", false])).toEqual([
      { id: "a-1", name: "The page's own read" },
    ]);
  });

  it("leaves a working organization alone", async () => {
    useOrgStore.setState({ activeOrgId: PERSONAL });
    answerWith([{ id: PERSONAL, is_personal: true }], {
      organization_id: PERSONAL,
      role: "owner",
      is_app_admin: false,
      permissions: [],
    });

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    expect(useOrgStore.getState().activeOrgId).toBe(PERSONAL);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not reassign the organization when the server is broken", async () => {
    useOrgStore.setState({ activeOrgId: STALE });
    answerWith(
      [{ id: PERSONAL, is_personal: true }],
      new ApiError(500, "Internal server error", {
        error: { code: "INTERNAL_ERROR", message: "Internal server error", details: null },
      }),
    );

    renderHook(() => useActiveOrganizationRecovery(), { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    expect(useOrgStore.getState().activeOrgId).toBe(STALE);
    expect(useOrgStore.getState().refusedOrgIds).toEqual([]);
    expect(toast.error).not.toHaveBeenCalled();
  });
});
