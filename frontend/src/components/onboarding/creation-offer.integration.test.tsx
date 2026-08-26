import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreationOffer } from "./creation-offer";
import { qk } from "@/lib/query-keys";
import { useOnboardingStore } from "@/stores/onboarding-store";
import type { Permission } from "@/types/permissions";

const rig = vi.hoisted(() => ({ can: (_permission: Permission): boolean => true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: rig.can, isLoading: false, error: null }),
}));

// The offer reads the query cache to know whether a create is worth offering at
// all — the MCP catalog, and how many agents the organization has — so every
// render needs a client, and `seed` fills whichever of those a test is about.
function renderOffer(
  node: ReactElement,
  seed: { catalog?: { items: unknown[] }; agents?: number; anyRunnable?: boolean } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed.catalog) client.setQueryData(qk.mcpServers.catalog(), seed.catalog);
  if (seed.anyRunnable !== undefined) {
    client.setQueryData(qk.agents.anyRunnable(), seed.anyRunnable);
  }
  if (seed.agents !== undefined) {
    client.setQueryData(qk.agents.list(), { items: [], total: seed.agents });
  }
  return { client, ...render(<QueryClientProvider client={client}>{node}</QueryClientProvider>) };
}

beforeEach(() => {
  rig.can = () => true;
  useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour", flowId: null, offer: null });
});

describe("CreationOffer", () => {
  it("offers the flow the store names, and accepting starts it", async () => {
    useOnboardingStore.setState({ offer: "create-skill" });
    renderOffer(<CreationOffer />);
    expect(screen.getByText("Create a skill?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Yes, guide me" }));
    expect(useOnboardingStore.getState()).toMatchObject({
      isOpen: true,
      mode: "flow",
      flowId: "create-skill",
      offer: null,
    });
  });

  it("declining records nothing but clearing the prompt", async () => {
    useOnboardingStore.setState({ offer: "create-kb" });
    renderOffer(<CreationOffer />);
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(useOnboardingStore.getState()).toMatchObject({
      offer: null,
      mode: "tour",
      isOpen: false,
    });
  });

  it("makes no offer the caller may not act on", () => {
    rig.can = () => false;
    useOnboardingStore.setState({ offer: "create-skill" });
    renderOffer(<CreationOffer />);
    expect(screen.queryByText("Create a skill?")).toBeNull();
  });

  it("offers an unpermissioned create to anyone", () => {
    rig.can = () => false;
    useOnboardingStore.setState({ offer: "create-org" });
    renderOffer(<CreationOffer />);
    expect(screen.getByText("Create an organization?")).toBeInTheDocument();
  });

  it("suppresses the create-mcp offer when the catalog is empty — nothing to connect", () => {
    useOnboardingStore.setState({ offer: "create-mcp" });
    renderOffer(<CreationOffer />, { catalog: { items: [] } });
    expect(screen.queryByText("Connect an MCP server?")).toBeNull();
  });

  it("offers create-mcp when the catalog has servers to connect", () => {
    useOnboardingStore.setState({ offer: "create-mcp" });
    renderOffer(<CreationOffer />, { catalog: { items: [{ key: "github" }] } });
    expect(screen.getByText("Connect an MCP server?")).toBeInTheDocument();
  });

  it("does not offer a first agent to an organization that already has one", () => {
    // This is what the first-run tour ends with, having just walked the reader
    // through an existing agent's builder in detail — so to an organization with
    // six agents it answers a question nobody asked.
    useOnboardingStore.setState({ offer: "create-agent" });
    renderOffer(<CreationOffer />, { agents: 6 });
    expect(screen.queryByText("Create your first agent?")).toBeNull();
  });

  it("offers it where the organization has none", () => {
    useOnboardingStore.setState({ offer: "create-agent" });
    renderOffer(<CreationOffer />, { agents: 0 });
    expect(screen.getByText("Create your first agent?")).toBeInTheDocument();
  });

  it("renders nothing when there is no offer", () => {
    const { container } = renderOffer(<CreationOffer />);
    expect(container).toBeEmptyDOMElement();
  });

  it("suppresses the routine offer for a caller who can run no agent", () => {
    // Role-level `agents:run` passes the flow's own gate, but the flow's first
    // target is the Routines page's create buttons, which mount only on the
    // per-agent answer - and the coach waits on a flow target without a timeout.
    // The check reads the same cached answer the buttons read, so the two can
    // never disagree.
    useOnboardingStore.setState({ offer: "create-routine" });
    renderOffer(<CreationOffer />, { anyRunnable: false });
    expect(screen.queryByText("Set up your first routine?")).toBeNull();
  });

  it("offers the routine flow to a caller with a runnable agent", () => {
    useOnboardingStore.setState({ offer: "create-routine" });
    renderOffer(<CreationOffer />, { anyRunnable: true });
    expect(screen.getByText("Set up your first routine?")).toBeInTheDocument();
  });

  it("holds the routine offer until the runnable-agent answer lands, then shows it", async () => {
    // A walk can finish before the page's runnable-agent sweep resolves. The
    // offer is subscribed to that query, not snapshotting it: unanswered means
    // no dialog yet, and the store still holds the offer - so when the answer
    // lands as yes, the dialog appears rather than having been lost.
    useOnboardingStore.setState({ offer: "create-routine" });
    const { client } = renderOffer(<CreationOffer />);
    expect(screen.queryByText("Set up your first routine?")).toBeNull();

    act(() => client.setQueryData(qk.agents.anyRunnable(), true));
    expect(await screen.findByText("Set up your first routine?")).toBeInTheDocument();
  });
});
