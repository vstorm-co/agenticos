import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { ApiError } from "@/lib/api-error";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { useOrgStore } from "@/stores";
import DatasetPage from "./page";

/**
 * The dataset page when the active organization changes under it.
 *
 * The dataset lives in Acme. Switching to Globex has to leave the page saying it
 * is not found there - the answer opening the URL in Globex gives - whether the
 * page was reached plainly or through a link naming Acme in `?org=`, which stays
 * in the URL after the switch.
 */

const ACME = "11111111-1111-4111-8111-111111111111";
const GLOBEX = "22222222-2222-4222-8222-222222222222";

const search = vi.hoisted(() => ({ value: "" }));

const org = (id: string, name: string, personal: boolean) => ({
  id,
  name,
  slug: name.toLowerCase(),
  avatar_url: null,
  avatar_color: null,
  is_personal: personal,
  owner_id: "u1",
});

const DATASET = {
  id: "d1",
  name: "refunds",
  description: null,
  visibility: "org",
  owner_user_id: "u1",
  latest_version: 1,
  case_count: 0,
  can_edit: true,
  can_run: true,
  run_needs: [],
  scoring: DEFAULT_SCORING,
  judge_name: null,
  stats: {},
  created_at: "2026-10-13T00:00:00Z",
  updated_at: null,
};

/** Answers as the backend does, for whichever organization the request carries. */
function answer(path: string): unknown {
  const tenant = useOrgStore.getState().activeOrgId;
  if (path === "/orgs") return { items: [org(ACME, "Acme", true), org(GLOBEX, "Globex", false)] };
  if (path === "/me/permissions") {
    return { organization_id: tenant, user_id: "u1", role: "owner", permissions: [] };
  }
  if (path.startsWith("/datasets/d1")) {
    if (tenant !== ACME) throw new ApiError(404, "Dataset not found");
    return path === "/datasets/d1" ? DATASET : { items: [], total: 0 };
  }
  throw new ApiError(404, `unexpected request to ${path}`);
}

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(async (path: string) => answer(path)) },
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.value),
  usePathname: () => "/datasets/d1",
}));
vi.mock("@/components/sharing/sharing-panel", () => ({ SharingPanel: () => null }));
vi.mock("@/components/evals/dataset-evals-panel", () => ({
  DatasetEvalsPanel: () => null,
  DatasetRunEvalsButton: () => null,
}));
vi.mock("@/components/datasets/grading-panel", () => ({ GradingPanel: () => null }));
vi.mock("@/components/datasets/review-panel", () => ({ ReviewPanel: () => null }));
vi.mock("@/hooks/use-agents", () => ({ useCapabilityCatalog: () => ({ capabilities: [] }) }));

function wrapper({ children }: { children: ReactNode }) {
  // `app/providers.tsx`'s staleTime: at the library's 0 every rerender refetches,
  // and the harness would answer the question instead of the code.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PARAMS = Promise.resolve({ id: "d1" });

describe("the dataset page across an organization switch", () => {
  beforeEach(() => useOrgStore.setState({ activeOrgId: ACME, refusedOrgIds: [] }));
  afterEach(() => useOrgStore.setState({ activeOrgId: null }));

  it.each([
    ["reached plainly", ""],
    ["reached through a link naming its organization", `org=${ACME}`],
  ])("stops showing the dataset of the organization just left, %s", async (_arrival, query) => {
    search.value = query;
    await act(async () => {
      render(
        <>
          <ActiveOrgGuard />
          <Suspense fallback={null}>
            <DatasetPage params={PARAMS} />
          </Suspense>
        </>,
        { wrapper },
      );
      await PARAMS;
    });
    expect(await screen.findByRole("heading", { name: "refunds" })).toBeInTheDocument();

    await act(async () => useOrgStore.getState().setActiveOrgId(GLOBEX));

    expect(await screen.findByText("Dataset not found")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "refunds" })).toBeNull();
  });
});
