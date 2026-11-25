import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useCodingAccounts } from "./use-coding-accounts";
import { useOrganizations } from "./use-organizations";
import { useAuthStore, useOrgStore } from "@/stores";

const personal = { id: "personal-org", is_default: false, is_personal: true };
const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

let releaseOrgs: () => void;
let requests: { path: string; org: string | null }[];

beforeEach(() => {
  requests = [];
  useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
  useAuthStore.setState({
    user: { id: "person", email: "p@example.com", is_active: true, created_at: "2026-11-01" },
  } as never);
  const orgsGate = new Promise<void>((resolve) => {
    releaseOrgs = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      requests.push({ path: String(url), org: headers.get("X-Organization-Id") });
      if (String(url).endsWith("/orgs")) {
        await orgsGate;
        return json({ items: [personal] });
      }
      return json({ items: [] });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

it("lists coding accounts only once the active organization is selected (#258)", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  renderHook(
    () => {
      // The page's coding hook mounts before the component that selects the
      // organization, so its effects run first.
      const accounts = useCodingAccounts();
      useOrganizations();
      return accounts;
    },
    { wrapper },
  );
  await act(async () => releaseOrgs());
  await waitFor(() => expect(requests.some((r) => r.path.endsWith("/coding-accounts"))).toBe(true));
  const listed = requests.filter((r) => r.path.endsWith("/coding-accounts"));
  expect(listed).toEqual([{ path: "/api/coding-accounts", org: "personal-org" }]);
});
