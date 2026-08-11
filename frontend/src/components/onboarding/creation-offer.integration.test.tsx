import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

// The offer reads the MCP catalog from the query cache to know whether a connect
// is worth offering, so every render needs a client — and a `catalog` seeds it.
function renderOffer(node: ReactElement, catalog?: { items: unknown[] }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (catalog) client.setQueryData(qk.mcpServers.catalog(), catalog);
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
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
    renderOffer(<CreationOffer />, { items: [] });
    expect(screen.queryByText("Connect an MCP server?")).toBeNull();
  });

  it("offers create-mcp when the catalog has servers to connect", () => {
    useOnboardingStore.setState({ offer: "create-mcp" });
    renderOffer(<CreationOffer />, { items: [{ key: "github" }] });
    expect(screen.getByText("Connect an MCP server?")).toBeInTheDocument();
  });

  it("renders nothing when there is no offer", () => {
    const { container } = renderOffer(<CreationOffer />);
    expect(container).toBeEmptyDOMElement();
  });
});
