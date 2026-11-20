import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConnectorsPage from "./page";
import { Perm } from "@/types/permissions";

/**
 * Connectors is two tabs over the same connections. Apps is the catalog and
 * what a person has connected; Advanced links to the lower-level pages, and a
 * card appears only for a caller who holds the permission its page reads - the
 * same gates the old nav entries carried, so a hidden entry is not a new
 * restriction.
 */

const state = vi.hoisted(() => ({
  granted: new Set<string>(),
  search: "",
  tab: undefined as string | null | undefined,
  setTab: vi.fn(),
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useSearchParams: () => new URLSearchParams(state.search),
}));

vi.mock("./apps-tab", () => ({
  AppsTab: () => <div>apps-tab-body</div>,
}));
vi.mock("./manual-connections", () => ({
  ManualConnections: () => <div>manual-connections-body</div>,
}));

vi.mock("@/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks")>()),
  usePermissions: () => ({
    can: (permission: string) => state.granted.has(permission),
    isLoading: false,
  }),
  useUrlState: () => [
    state.tab === undefined ? new URLSearchParams(state.search).get("tab") : state.tab,
    state.setTab,
  ],
  useMcpOAuthOutcome: () => undefined,
}));

describe("ConnectorsPage", () => {
  beforeEach(() => {
    state.granted = new Set([Perm.agentsView, Perm.secretsView, Perm.connectionsView]);
    state.search = "";
    state.tab = undefined;
    state.setTab.mockReset();
  });

  it("opens on Apps by default", () => {
    render(<ConnectorsPage />);

    expect(screen.getByText("apps-tab-body")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Vault" })).not.toBeInTheDocument();
  });

  it("shows the MCP catalog as a first-class tab", () => {
    state.search = "?tab=mcp";
    render(<ConnectorsPage />);

    expect(screen.getByRole("tab", { name: "MCP servers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("manual-connections-body")).toBeVisible();
  });

  it.each(["?server=googlecalendar", "?connect=googlecalendar"])(
    "opens manual MCP links on MCP (%s)",
    (query) => {
      state.search = query;
      render(<ConnectorsPage />);

      expect(screen.getByRole("tab", { name: "MCP servers" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(screen.getByText("manual-connections-body")).toBeVisible();
    },
  );

  it("maps the legacy advanced tab to MCP and writes canonical tab values", async () => {
    state.search = "?tab=advanced";
    const { unmount } = render(<ConnectorsPage />);

    expect(screen.getByRole("tab", { name: "MCP servers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("manual-connections-body")).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "More" }));
    expect(state.setTab).toHaveBeenLastCalledWith("more");
    unmount();

    state.search = "";
    state.setTab.mockClear();
    render(<ConnectorsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "MCP servers" }));
    expect(state.setTab).toHaveBeenLastCalledWith("mcp");
  });

  it("lists every More connection a caller may read, each linking under /connectors", async () => {
    state.search = "?tab=more";
    render(<ConnectorsPage />);

    const channels = screen.getByRole("link", { name: /Channels/ });
    const remote = screen.getByRole("link", { name: /Remote agents/ });
    const vault = screen.getByRole("link", { name: /Vault/ });
    const sandboxes = screen.getByRole("link", { name: /Sandboxes/ });

    expect(channels).toHaveAttribute("href", "/connectors/channels");
    expect(remote).toHaveAttribute("href", "/connectors/remote-agents");
    expect(vault).toHaveAttribute("href", "/connectors/vault");
    expect(sandboxes).toHaveAttribute("href", "/connectors/sandboxes");
  });

  it("hides a More card whose page the caller cannot read", () => {
    state.search = "?tab=more";
    state.granted = new Set([Perm.agentsView]);
    render(<ConnectorsPage />);

    const list = screen.getByRole("list");
    expect(within(list).getByRole("link", { name: /Channels/ })).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: /Remote agents/ })).toBeInTheDocument();
    expect(within(list).queryByRole("link", { name: /Vault/ })).not.toBeInTheDocument();
    expect(within(list).queryByRole("link", { name: /Sandboxes/ })).not.toBeInTheDocument();
  });

  it("gates each More card on the permission its page read before the move", () => {
    // Vault and Sandboxes were nav entries of their own, each gated by its own
    // permission. Moving them under More must not widen or narrow either gate.
    state.search = "?tab=more";
    state.granted = new Set([Perm.secretsView]);
    const { unmount } = render(<ConnectorsPage />);
    expect(
      within(screen.getByRole("list")).getByRole("link", { name: /Vault/ }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list")).queryByRole("link", { name: /Sandboxes/ }),
    ).not.toBeInTheDocument();
    unmount();

    state.granted = new Set([Perm.connectionsView]);
    render(<ConnectorsPage />);
    expect(
      within(screen.getByRole("list")).getByRole("link", { name: /Sandboxes/ }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list")).queryByRole("link", { name: /Vault/ }),
    ).not.toBeInTheDocument();
  });

  it("writes the tab to the URL, clearing it when going back to the default tab", async () => {
    const { unmount } = render(<ConnectorsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "More" }));
    expect(state.setTab).toHaveBeenLastCalledWith("more");
    unmount();

    state.setTab.mockClear();
    state.search = "?tab=more";
    render(<ConnectorsPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Apps" }));
    expect(state.setTab).toHaveBeenLastCalledWith(null);
  });
});
