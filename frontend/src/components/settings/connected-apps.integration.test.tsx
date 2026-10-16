import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectedApps } from "./connected-apps";
import type { ConnectedApp } from "@/types/mcp-oauth";

const useConnectedAppsMock = vi.fn();
let held: string[] = [];

vi.mock("@/hooks", () => ({
  useConnectedApps: () => useConnectedAppsMock(),
  usePermissions: () => ({ can: (perm: string) => held.includes(perm) }),
}));

const APP: ConnectedApp = {
  id: "g1",
  client_name: "Claude Code",
  client_uri: null,
  user_id: "u1",
  user_email: "ada@example.com",
  scopes: ["agents:view"],
  created_at: "2026-10-09T10:00:00Z",
};

function state(overrides: Record<string, unknown> = {}) {
  return {
    apps: [APP],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    disconnect: { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false },
    ...overrides,
  };
}

describe("ConnectedApps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    held = [];
  });

  it("lists an application and disconnects it after confirming", async () => {
    const current = state();
    useConnectedAppsMock.mockReturnValue(current);
    render(<ConnectedApps />);

    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("1 permission")).toBeInTheDocument();
    expect(screen.queryByText("Connected by")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));

    expect(current.disconnect.mutateAsync).toHaveBeenCalledWith("g1");
  });

  it("names who connected each app for somebody managing keys, and dismissing does nothing", async () => {
    held = ["api_keys:manage"];
    const current = state();
    useConnectedAppsMock.mockReturnValue(current);
    render(<ConnectedApps />);

    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(current.disconnect.mutateAsync).not.toHaveBeenCalled();
  });

  it("tells an empty list from a failed one", async () => {
    useConnectedAppsMock.mockReturnValue(state({ apps: [] }));
    const { rerender } = render(<ConnectedApps />);
    expect(screen.getByText("No connected applications")).toBeInTheDocument();

    const refetch = vi.fn();
    useConnectedAppsMock.mockReturnValue(state({ apps: [], error: new Error("502"), refetch }));
    rerender(<ConnectedApps />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });
});
