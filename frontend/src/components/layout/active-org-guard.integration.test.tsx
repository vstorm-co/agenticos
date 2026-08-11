import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveOrgGuard } from "./active-org-guard";
import { SidebarNav } from "./app-sidebar";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  // Wrapped at module scope by the language switcher's locale-aware navigation,
  // which this tree imports; without them the file fails to import at all.
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api-client", async () => {
  const { ApiError } = await import("@/lib/api-error");
  return { apiClient: { get: vi.fn() }, ApiError };
});

const STALE = "11111111-1111-1111-1111-111111111111";
const PERSONAL = "22222222-2222-2222-2222-222222222222";

/** Every permission the nav gates an entry on. */
const GRANTED = [
  "agents:view",
  "skills:view",
  "runs:view",
  "collections:view",
  "connections:manage",
].map((permission) => ({ permission, scope: "all" }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * A backend that refuses one organization and serves another.
 *
 * The refusal is keyed on the store rather than hard-coded, because that is what
 * makes the test a test: it answers whatever organization the app is actually
 * holding at the moment of the call, so a recovery that switched to something
 * still refused would not pass.
 */
function backendRefusing(refusedOrgId: string) {
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === "/orgs") {
      return Promise.resolve({
        items: [{ id: PERSONAL, name: "Personal", is_personal: true }],
        total: 1,
      });
    }
    if (endpoint === "/me/permissions") {
      const holding = useOrgStore.getState().activeOrgId;
      if (holding === refusedOrgId) {
        return Promise.reject(
          new ApiError(404, "Organization not found or access denied", {
            error: {
              code: "NOT_FOUND",
              message: "Organization not found or access denied",
              details: { org_id: refusedOrgId },
            },
          }),
        );
      }
      return Promise.resolve({
        organization_id: holding,
        role: "owner",
        is_app_admin: false,
        permissions: GRANTED,
      });
    }
    throw new Error(`unexpected request to ${endpoint}`);
  });
}

describe("a stale organization does not permanently empty the navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
  });

  it("puts back every entry a refused organization stripped", async () => {
    // This is the reported screenshot, reproduced: the persisted organization no
    // longer exists, `/me/permissions` 404s, and because `can()` answers false
    // whenever permissions are unavailable, the sidebar keeps only the four
    // ungated entries. No error, no route back except knowing that the
    // organization switcher exists.
    useOrgStore.setState({ activeOrgId: STALE });
    backendRefusing(STALE);

    render(
      <>
        <ActiveOrgGuard />
        <SidebarNav />
      </>,
      { wrapper },
    );

    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
    expect(screen.queryByText("agents")).not.toBeInTheDocument();

    // What the fix adds: the refusal is recognised, the selection moves to an
    // organization the caller belongs to, and the nav comes back on its own.
    await waitFor(() => expect(screen.getByText("agents")).toBeInTheDocument());
    for (const entry of ["skills", "activity", "knowledgeBases"]) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
    expect(useOrgStore.getState().activeOrgId).toBe(PERSONAL);
  });

  it("keeps the navigation stripped while the server is merely broken", async () => {
    // The other half of the same behaviour. A 500 says nothing about whether
    // the caller still belongs to this organization, so reassigning them would
    // turn an outage into a silent tenant switch - and the nav staying reduced
    // is the correct, conservative outcome, not a bug to paper over.
    useOrgStore.setState({ activeOrgId: STALE });
    vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
      if (endpoint === "/orgs") {
        return Promise.resolve({
          items: [{ id: PERSONAL, name: "Personal", is_personal: true }],
          total: 1,
        });
      }
      return Promise.reject(
        new ApiError(500, "Internal server error", {
          error: { code: "INTERNAL_ERROR", message: "Internal server error", details: null },
        }),
      );
    });

    render(
      <>
        <ActiveOrgGuard />
        <SidebarNav />
      </>,
      { wrapper },
    );

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/orgs"));
    expect(screen.queryByText("agents")).not.toBeInTheDocument();
    expect(useOrgStore.getState().activeOrgId).toBe(STALE);
  });
});
