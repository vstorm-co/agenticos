import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DelegationPanels } from "./delegation-panel";
import { qk } from "@/lib/query-keys";
import type { Permission } from "@/types/permissions";
import type { Delegation } from "@/types";

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
