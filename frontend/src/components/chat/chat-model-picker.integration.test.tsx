import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatModelPicker } from "./chat-model-picker";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * Who is offered the chat's model picker at all, against a mocked backend.
 *
 * `chat-model-picker.test.tsx` covers what the control does with the hooks
 * stubbed out; this covers the one thing a stubbed hook cannot answer - whether
 * the permission the API enforces is the permission this component reads. The
 * form creates an organization-wide model profile, which is `connections:manage`,
 * and opening a conversation is not (#419).
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** A model somebody with `connections:manage` already registered for the org. */
const PROFILE = {
  id: "p-1",
  label: "Team gpt-5",
  provider: "openai",
  model: "gpt-5",
  secret_id: "s-openai",
  params: {},
  allow_byo: false,
  fallback_profile_ids: [],
};

const PURPOSES = {
  items: [
    {
      id: "openai",
      label: "OpenAI",
      category: "model_provider",
      kind: "api_key",
      help_url: null,
      description: "",
    },
  ],
  total: 1,
};

const SECRETS = {
  items: [
    {
      id: "s-openai",
      name: "OpenAI",
      description: null,
      kind: "api_key",
      hint: "1234",
      purpose: "openai",
    },
  ],
  total: 1,
};

/** The backend this picker reads, answering as it does for a member of one org. */
function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    // A list shape here is not "no permissions", it is a `TypeError` inside
    // `usePermissions`.
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "operator",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      };
    // Readable on `agents:view`, so it is populated for both callers below.
    if (path === "/providers/model-profiles") return { items: [PROFILE], total: 1 };
    if (path === "/providers/catalog") return { items: [], total: 0 };
    if (path === "/providers/openai/models") return { items: [], total: 0, source: null };
    if (path === "/secrets") return SECRETS;
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    if (path === "/secrets/purposes") return PURPOSES;
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount(permissions: Permission[], onChange = vi.fn()) {
  serve(permissions);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ChatModelPicker
        value={null}
        agentModel={{
          profile_id: "ap",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          label: "Claude Sonnet",
        }}
        onChange={onChange}
      />
    </QueryClientProvider>,
  );
  // Waited for, not assumed: `can()` answers false until the permission set
  // lands, so a form asserted absent before then is absent for the wrong reason
  // and the test would pass with the gate deleted.
  await waitFor(() =>
    expect(client.getQueryData(qk.organizations.permissions("current"))).toBeDefined(),
  );
  return onChange;
}

const submit = () => screen.queryByRole("button", { name: "Run on this model" });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("who may move this conversation onto another model", () => {
  it("offers the whole form to a caller holding connections:manage", async () => {
    await mount([Perm.agentsView, Perm.connectionsManage]);

    expect(screen.getByRole("combobox", { name: "Provider" })).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toBeInTheDocument();
    expect(submit()).toBeInTheDocument();
    expect(screen.queryByText(/permission you do not hold/)).toBeNull();
  });

  it("offers none of the fields without, but still says what it runs on", async () => {
    // An operator: they may run this agent, which is what opens the popover, and
    // may not define a model for the organization, which is what the form does.
    await mount([Perm.agentsView, Perm.agentsRun]);

    expect(screen.queryByRole("combobox", { name: "Provider" })).toBeNull();
    expect(screen.queryByLabelText("Model")).toBeNull();
    expect(submit()).toBeNull();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
    // Reading which model the conversation runs on is agents:view, not the
    // permission being refused - so the model is shown even here.
    expect(screen.getByText("Claude Sonnet")).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("still reuses a model somebody else registered, and writes nothing to do it", async () => {
    // The gate covers the form rather than the submit, so this path is only
    // reachable by a caller who holds the permission. It is asserted because the
    // gate must not have turned a read into a write: a provider and model that
    // match an existing profile select it, and `POST /providers/model-profiles`
    // is never sent.
    const onChange = await mount([Perm.agentsView, Perm.connectionsManage]);

    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));
    await userEvent.type(screen.getByLabelText("Model"), "gpt-5");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(onChange).toHaveBeenCalledWith("p-1");
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
