import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentsSection } from "./subagents-section";
import { apiClient } from "@/lib/api-client";
import type { Agent, CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { Permission } from "@/types/permissions";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const DELEGATION: CapabilityCatalogEntry = {
  id: "subagents",
  name: "Delegation",
  category: "orchestration",
  description: "Hand part of a task to another agent.",
  side_effecting: false,
  scopes: ["agents:delegate"],
  tools: [],
  contracts: [],
  config_schema: null,
  requires_secret: null,
};

const RESEARCHER: Agent = {
  id: "a1",
  slug: "researcher",
  name: "Researcher",
  description: null,
  status: "published",
  visibility: "private",
  owner_user_id: null,
  current_version_id: "v2",
};

const BINDING: CapabilityBindingSpec = {
  id: "subagents",
  config: {},
  approval: "default",
  tool_approval: {},
  tool_overrides: {},
  secret_id: null,
  enabled: true,
};

/** The API as this panel actually reads it: a permission set and the agents. */
function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") {
      return {
        organization_id: "org-1",
        role: "member",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      };
    }
    if (path === "/agents") return { items: [RESEARCHER], total: 1 };
    if (path.endsWith("/versions")) return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount() {
  render(
    <SubagentsSection
      definition={DELEGATION}
      binding={BINDING}
      catalog={[DELEGATION]}
      parentCapabilities={[BINDING]}
      parentModelProfileId={null}
      subagents={[]}
      onChange={vi.fn()}
      onSubagentsChange={vi.fn()}
    />,
    { wrapper },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

/**
 * Whether the delegate picker is rendered at all, against the real permission
 * hook and a mocked API.
 *
 * Publishing checks every delegate against the publisher's own right to run it,
 * so a member who cannot run agents cannot pin one. Offering the control and
 * failing at publish is the same refusal with an hour's delay and a form full of
 * work in between.
 */
describe("delegating is gated on being able to run an agent", () => {
  it("offers the picker to somebody who may run agents", async () => {
    serve(["agents:edit", "agents:run"]);
    mount();

    expect(await screen.findByRole("button", { name: "Add a delegate" })).toBeVisible();
  });

  it("does not render the picker for somebody who may not, and says why", async () => {
    serve(["agents:edit"]);
    mount();

    expect(await screen.findByText(/needs permission to run agents/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add a delegate" })).toBeNull();
  });

  it("renders no picker while the permission set is still unknown", async () => {
    // `can()` answers false until the request lands, which reveals the control
    // rather than briefly offering one that would be refused.
    serve(["agents:edit", "agents:run"]);
    mount();

    expect(screen.queryByRole("button", { name: "Add a delegate" })).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add a delegate" })).toBeVisible(),
    );
  });
});
