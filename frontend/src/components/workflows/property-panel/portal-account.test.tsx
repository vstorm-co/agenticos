import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { portalConnectUrl } from "@/lib/portal-connect";

import { ACCOUNT_TRIGGERS, PortalAccount } from "./portal-account";

const state = vi.hoisted(() => ({
  canManage: true,
  isLoading: false,
  items: [] as unknown[],
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
  usePortals: () => ({ items: state.items, isLoading: state.isLoading }),
}));
vi.mock("@/lib/portal-connect", () => ({ portalConnectUrl: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const gmail = (action: string, blocked: string | null = null) => ({
  portal: { key: "google", name: "Gmail", connect_blocked_by: blocked },
  action,
});

const assign = vi.fn();
beforeEach(() => {
  state.canManage = true;
  state.isLoading = false;
  state.items = [];
  vi.clearAllMocks();
  Object.defineProperty(window, "location", { value: { assign }, writable: true });
});

describe("PortalAccount", () => {
  it("says a connected mailbox is read", () => {
    state.items = [gmail("create")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(screen.getByText(/mailbox is connected/)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("connects a mailbox nobody connected, through the portal's own flow", async () => {
    state.items = [gmail("connect")];
    vi.mocked(portalConnectUrl).mockResolvedValue("https://google/consent");
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);

    expect(screen.getByText(/Publishing waits for one/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(assign).toHaveBeenCalledWith("https://google/consent");
  });

  it("says why connecting failed, and offers it again", async () => {
    state.items = [
      {
        portal: { key: "github", name: "GitHub", connect_blocked_by: null },
        action: "reauthorize",
      },
    ];
    vi.mocked(portalConnectUrl).mockRejectedValue(new Error("no"));
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.github"]!} />);

    expect(screen.getByText(/cannot manage webhooks yet/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(toast.error).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeEnabled();
  });

  it("says what blocks connecting instead of offering it", () => {
    state.items = [gmail("connect", "oauth_unavailable")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(screen.getByText(/no way to connect Gmail/)).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("sends a missing OAuth app to the vault", () => {
    state.items = [gmail("connect", "oauth_app_secret")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(screen.getByText(/Gmail OAuth app credentials/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the vault" })).toHaveAttribute("href", "/vault");
  });

  it("offers nothing to connect to a member who may not manage connections", () => {
    state.canManage = false;
    state.items = [gmail("connect")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("waits for the catalog, and shows nothing for a portal it does not list", () => {
    state.isLoading = true;
    const { container, rerender } = render(
      <PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />,
    );
    expect(container.firstChild).not.toBeNull();
    state.isLoading = false;
    rerender(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(container).toBeEmptyDOMElement();
  });
});
