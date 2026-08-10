import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDetailTargets } from "./detail-targets";
import { AGENT_BUILDER, KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

// A list left unseeded would fetch for real in jsdom; an empty answer keeps the
// resolver's arithmetic (active-org fallback, empty-list skip) the only variable.
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(async () => ({ items: [] })) },
}));

// Each list is seeded in the exact shape its owning page hook stores under the
// same key — `useAgents` caches the whole `AgentList`, `useKnowledgeBases` and
// `useOrganizationList` cache the `.items` array. `staleTime: Infinity` keeps the
// seeded data from being refetched, so the test reads only how the resolver
// interprets that cache, which is the thing that broke.
function wrapperWith(seed: (client: QueryClient) => void) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    seed(client);
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  // The resolver prefers the active organization; nulling it exercises the list
  // fallback, which is the path that has a shape to get wrong.
  useOrgStore.setState({ activeOrgId: null });
});

describe("useDetailTargets", () => {
  it("resolves each detail route from the cache shape its owning hook stores", () => {
    const wrapper = wrapperWith((client) => {
      // `AgentList` object — what `useAgents` caches.
      client.setQueryData(qk.agents.list(false), {
        items: [{ id: "agent-1", slug: "getting-started" }],
        total: 1,
      });
      // Bare arrays — what `useKnowledgeBases` and `useOrganizationList` cache.
      // Reading these as `{ items }` (the bug) throws on `.items.find`.
      client.setQueryData(qk.kb.list(), [{ id: "kb-1", is_default: true }]);
      client.setQueryData(qk.organizations.list(), [{ id: "org-1", is_personal: true }]);
    });

    const { result } = renderHook(() => useDetailTargets(true), { wrapper });

    expect(result.current[AGENT_BUILDER]?.href).toBe("/agents/agent-1");
    expect(result.current[KB_DETAIL]?.href).toBe("/rag/kb-1");
    expect(result.current[ORG_MEMBERS]?.href).toBe("/orgs/org-1/members");
    expect(result.current[ORG_ROLES]?.href).toBe("/orgs/org-1/roles");
  });

  it("prefers the seeded getting-started agent and default collection over the first row", () => {
    const wrapper = wrapperWith((client) => {
      client.setQueryData(qk.agents.list(false), {
        items: [
          { id: "agent-other", slug: "something-else" },
          { id: "agent-gs", slug: "getting-started" },
        ],
        total: 2,
      });
      client.setQueryData(qk.kb.list(), [
        { id: "kb-other", is_default: false },
        { id: "kb-default", is_default: true },
      ]);
    });

    const { result } = renderHook(() => useDetailTargets(true), { wrapper });

    expect(result.current[AGENT_BUILDER]?.href).toBe("/agents/agent-gs");
    expect(result.current[KB_DETAIL]?.href).toBe("/rag/kb-default");
  });

  it("gives a null href for an empty list so the engine skips that walk", () => {
    const wrapper = wrapperWith((client) => {
      client.setQueryData(qk.agents.list(false), { items: [], total: 0 });
      client.setQueryData(qk.kb.list(), []);
      client.setQueryData(qk.organizations.list(), []);
    });

    const { result } = renderHook(() => useDetailTargets(true), { wrapper });

    expect(result.current[AGENT_BUILDER]?.href).toBeNull();
    expect(result.current[KB_DETAIL]?.href).toBeNull();
    expect(result.current[ORG_MEMBERS]?.href).toBeNull();
    expect(result.current[ORG_ROLES]?.href).toBeNull();
  });

  it("resolves both organization routes from the active org, list untouched", () => {
    useOrgStore.setState({ activeOrgId: "active-org" });
    const wrapper = wrapperWith(() => {
      // No org list seeded: the active org alone must answer both routes.
    });

    const { result } = renderHook(() => useDetailTargets(true), { wrapper });

    expect(result.current[ORG_MEMBERS]?.href).toBe("/orgs/active-org/members");
    expect(result.current[ORG_ROLES]?.href).toBe("/orgs/active-org/roles");
  });
});
