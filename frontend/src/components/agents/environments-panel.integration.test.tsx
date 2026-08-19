import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EnvironmentsPanel } from "./environments-panel";
import { apiClient } from "@/lib/api-client";
import type { AgentEnvironment, AgentVersion } from "@/types/agents";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const AGENT_ID = "a1";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function environment(overrides: Partial<AgentEnvironment> = {}): AgentEnvironment {
  return {
    id: "env-dev",
    agent_id: AGENT_ID,
    name: "dev",
    version_id: "v5-id",
    version: 5,
    is_default: false,
    tracks_latest: false,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function version(n: number): AgentVersion {
  return { id: `v${n}-id`, version: n, note: null, published_by_user_id: null };
}

function serve(environments: AgentEnvironment[], versions: AgentVersion[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/agents/${AGENT_ID}/environments`) {
      return { items: environments, total: environments.length };
    }
    if (path === `/agents/${AGENT_ID}/versions`) {
      return { items: versions, total: versions.length };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.patch).mockResolvedValue(environment());
});

describe("the environments panel against the real hooks", () => {
  it("repoints an environment from its own row and re-reads what it serves", async () => {
    // The acceptance path of #134: dev serves v5, its row's select picks v3,
    // and after the refetch the row states serves v3.
    const dev = environment();
    serve([dev], [version(5), version(4), version(3)]);
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await screen.findByText(/serves v5/);

    serve([{ ...dev, version_id: "v3-id", version: 3 }], [version(5), version(4), version(3)]);
    await userEvent.click(screen.getByRole("combobox", { name: "Pin a version for dev" }));
    await userEvent.click(screen.getByRole("option", { name: "v3" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-dev`, {
      version_id: "v3-id",
    });
    await screen.findByText(/serves v3/);
  });

  it("renames from the row, sending the name and nothing else", async () => {
    const dev = environment();
    serve([dev], [version(5)]);
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await screen.findByText(/serves v5/);

    serve([{ ...dev, name: "canary" }], [version(5)]);
    await userEvent.click(screen.getByRole("button", { name: "Rename dev" }));
    const field = screen.getByRole("textbox", { name: "Rename dev" });
    await userEvent.clear(field);
    await userEvent.type(field, "canary{enter}");

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-dev`, {
      name: "canary",
    });
    await screen.findByText("canary");
  });

  it("renders no version control, rename or removal to a caller who may not manage", async () => {
    // The rule is not-rendered, not rendered-then-403: somebody without
    // agents:publish reads what each name serves and can change none of it.
    serve(
      [environment({ id: "env-prod", name: "production", is_default: true }), environment()],
      [version(5), version(3)],
    );
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage={false} />, { wrapper });
    await screen.findByText("production");

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Rename dev" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove dev" })).toBeNull();
    expect(screen.queryByLabelText("New environment")).toBeNull();
    await waitFor(() => expect(apiClient.patch).not.toHaveBeenCalled());
  });
});
