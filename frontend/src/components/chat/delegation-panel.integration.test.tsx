import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { DelegationPanels } from "./delegation-panel";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ModelProfile } from "@/types/providers";
import type { Permission } from "@/types/permissions";
import type { Delegation } from "@/types";

// `get` rejects rather than resolves: every query this tree runs is seeded into
// the cache below, and a background refetch that *succeeded* with the wrong shape
// would clobber the seed (the permissions query has a zero stale time). A rejected
// refetch keeps the seeded value, which is what these tests assert against. Only
// `post` - the promote call - is driven per test.
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn().mockRejectedValue(new Error("not mocked")), post: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/**
 * Reaching the run a delegation produced, from the panel that streamed it.
 *
 * The link is the last mile of a chain that already existed and went nowhere:
 * the terminal frame carries `run_id`, the reducer keeps it, and the run row is
 * the only place this delegation's cost, model and tokens are written down as
 * its own rather than folded into the parent's. Before this the id arrived and
 * was dropped.
 *
 * Driven through the real `usePermissions`, because whether the link is rendered
 * is a permission decision and a stubbed `can: () => true` would assert nothing
 * about it. The permission answer is seeded into the cache rather than mocked
 * onto the network: `can()` returns false while the query is in flight, so a
 * test that asserted "no link" against a pending query would pass without ever
 * exercising the gate.
 */

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

/** A client that already knows what the caller may do. */
function wrapperGranting(...permissions: Permission[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.organizations.permissions("current"), {
      organization_id: "o1",
      role: "operator",
      is_app_admin: false,
      permissions: permissions.map((permission) => ({ permission, scope: "all" })),
    });
    // Seeded so the promote control's model lookup never reaches the network -
    // it needs no profile to render, only to resolve one when pressed.
    client.setQueryData(qk.providers.modelProfiles(), { items: [], total: 0 });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function finished(overrides: Partial<Delegation> = {}): Delegation {
  return {
    taskId: "4f2a1b8c",
    subagent: "researcher",
    depth: 0,
    mode: "sync",
    prompt: "find three papers on retrieval",
    parentTaskId: null,
    runId: "run-77",
    status: "completed",
    specialist: null,
    text: "found three",
    thinking: "",
    steps: [],
    costUsd: 0.4,
    inputTokens: 500,
    outputTokens: 50,
    error: null,
    ...overrides,
  };
}

/** The panel is closed once a delegation is over, and the link is in the body. */
async function openPanel() {
  const header = await screen.findByRole("button", { name: /researcher/ });
  header.click();
}

describe("the run behind a delegation panel", () => {
  it("links to the run the delegation produced", async () => {
    render(<DelegationPanels delegations={[finished()]} />, {
      wrapper: wrapperGranting("runs:view"),
    });
    await openPanel();

    expect(await screen.findByRole("link", { name: "Open in run history" })).toHaveAttribute(
      "href",
      "/runs?run=run-77",
    );
  });

  it("offers nothing to open for an inline specialist", async () => {
    // Defined inside its parent's spec, so it has no agent, no version and no
    // `agent_runs` row. An absent id means there is no page, exactly as it does
    // for an unlinked delegate in the approval queue - not a forgotten link.
    render(<DelegationPanels delegations={[finished({ runId: null })]} />, {
      wrapper: wrapperGranting("runs:view"),
    });
    await openPanel();

    expect(await screen.findByTestId("markdown")).toHaveTextContent("found three");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("does not offer a page to somebody who may not read run history", async () => {
    // Not rendered, rather than rendered and then refused: `GET /runs/{id}`
    // wants `runs:view`, so the link would land them on a page that answers 403
    // and draws as an empty table.
    render(<DelegationPanels delegations={[finished()]} />, {
      wrapper: wrapperGranting("approvals:decide"),
    });
    await openPanel();

    expect(await screen.findByTestId("markdown")).toHaveTextContent("found three");
    expect(screen.queryByRole("link", { name: "Open in run history" })).toBeNull();
  });
});

/**
 * Keeping a specialist the model invented, from the panel that streamed it.
 *
 * The definition arrives on the opening frame and nowhere else, so the offer to
 * keep it exists only while the run is on screen. It is gated on `agents:edit` -
 * promoting creates an agent - so a control the caller may not use is not rendered
 * rather than rendered and then refused, and driven through the real
 * `usePermissions` for the same reason the run link above is.
 */
describe("promoting a specialist the model invented", () => {
  const invented = {
    description: "Pulls line items out of an invoice",
    instructions: "Read the invoice and return its line items.",
    model: "GPT-4.1 (prod)",
  };

  const PROFILE: ModelProfile = {
    id: "m1",
    label: "GPT-4.1 (prod)",
    provider: "openai",
    model: "gpt-4.1",
    secret_id: null,
    params: {},
    allow_byo: false,
    fallback_profile_ids: [],
  };

  /** A caller who may create an agent, with the given model profiles on hand. */
  function keeperWith(profiles: ModelProfile[]) {
    return function Wrapper({ children }: { children: ReactNode }) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      client.setQueryData(qk.organizations.permissions("current"), {
        organization_id: "o1",
        role: "operator",
        is_app_admin: false,
        permissions: [{ permission: "agents:edit", scope: "all" }],
      });
      client.setQueryData(qk.providers.modelProfiles(), {
        items: profiles,
        total: profiles.length,
      });
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    };
  }

  async function promote() {
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Promote to a draft agent" }));
  }

  it("offers to keep a dynamic specialist to a caller who may create an agent", async () => {
    render(<DelegationPanels delegations={[finished({ specialist: invented, runId: null })]} />, {
      wrapper: wrapperGranting("agents:edit"),
    });
    await openPanel();

    expect(
      await screen.findByRole("button", { name: "Promote to a draft agent" }),
    ).toBeInTheDocument();
  });

  it("does not offer it to a caller who may not create an agent", async () => {
    render(<DelegationPanels delegations={[finished({ specialist: invented, runId: null })]} />, {
      wrapper: wrapperGranting("runs:view"),
    });
    await openPanel();

    expect(await screen.findByTestId("markdown")).toHaveTextContent("found three");
    expect(screen.queryByRole("button", { name: "Promote to a draft agent" })).toBeNull();
  });

  it("offers nothing to keep for a delegate that is already keepable", async () => {
    // No definition on the frame - a configured delegate or an inline specialist,
    // both of which are kept already. Nothing to promote even with the permission.
    render(<DelegationPanels delegations={[finished({ specialist: null })]} />, {
      wrapper: wrapperGranting("agents:edit"),
    });
    await openPanel();

    expect(await screen.findByTestId("markdown")).toHaveTextContent("found three");
    expect(screen.queryByRole("button", { name: "Promote to a draft agent" })).toBeNull();
  });

  it("promotes the invented specialist, resolving its model label to a profile", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a9", name: "researcher" });
    render(<DelegationPanels delegations={[finished({ specialist: invented, runId: null })]} />, {
      wrapper: keeperWith([PROFILE]),
    });

    await promote();

    expect(apiClient.post).toHaveBeenCalledWith("/agents/promote", {
      specialist: expect.objectContaining({
        name: "researcher",
        instructions: invented.instructions,
        // The label the model named, resolved to the profile's id.
        model_profile_id: "m1",
      }),
      fallback_model_profile_id: null,
    });
    expect(toast.success).toHaveBeenCalledWith("Promoted researcher to a draft agent");
  });

  it("promotes with no model when the named label no longer resolves, and reports a refusal", async () => {
    // The profile was deleted since the run: the draft is created without one and
    // asks for a model before it can publish, rather than the promote failing.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("no model set"));
    render(<DelegationPanels delegations={[finished({ specialist: invented, runId: null })]} />, {
      wrapper: keeperWith([]),
    });

    await promote();

    expect(apiClient.post).toHaveBeenCalledWith("/agents/promote", {
      specialist: expect.objectContaining({ model_profile_id: null }),
      fallback_model_profile_id: null,
    });
    expect(toast.error).toHaveBeenCalledWith("no model set");
  });
});
