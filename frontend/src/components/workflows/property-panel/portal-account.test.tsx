import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { Perm } from "@/types/permissions";
import { portalConnectUrl } from "@/lib/portal-connect";

import { ACCOUNT_TRIGGERS, PortalAccount } from "./portal-account";

const state = vi.hoisted(() => ({
  canManage: true,
  canStore: true,
  isLoading: false,
  items: [] as unknown[],
  save: vi.fn(),
  create: vi.fn(),
  invalidate: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ kinds: [], create: { mutateAsync: state.create, isPending: false } }),
  usePermissions: () => ({
    can: (permission: string) =>
      permission === Perm.secretsEdit ? state.canStore : state.canManage,
  }),
  usePortals: () => ({ items: state.items, isLoading: state.isLoading }),
  usePortalPollInterval: () => ({ mutateAsync: state.save, isPending: false }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: state.invalidate }),
}));
vi.mock("@/components/vault/secret-dialog", () => ({
  AddSecretDialog: ({
    purposeId,
    onSubmit,
  }: {
    purposeId: string;
    onSubmit: (data: object) => Promise<unknown>;
  }) => <button onClick={() => void onSubmit({ name: "Google" })}>Store {purposeId}</button>,
}));
vi.mock("@/lib/portal-connect", () => ({ portalConnectUrl: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const gmail = (action: string, blocked: string | null = null) => ({
  portal: { key: "google", name: "Gmail", connect_blocked_by: blocked },
  action,
});

const outlook = (action: string) => ({
  portal: { key: "microsoft", name: "Outlook", connect_blocked_by: null },
  action,
});

const assign = vi.fn();
beforeEach(() => {
  state.canManage = true;
  state.canStore = true;
  state.isLoading = false;
  state.items = [];
  state.save = vi.fn().mockResolvedValue({});
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

  it.each([
    ["trigger.gmail", "google", "Gmail"],
    ["trigger.outlook", "microsoft", "Outlook"],
  ])(
    "sets how often the %s mailbox is checked, for every trigger on it",
    async (trigger, key, name) => {
      state.items = [
        {
          portal: {
            key,
            name,
            connect_blocked_by: null,
            connection_id: "conn-1",
            connection_state: "connected",
            poll_interval_minutes: 5,
          },
          action: "create",
        },
      ];
      state.save = vi.fn().mockResolvedValue({});
      render(<PortalAccount account={ACCOUNT_TRIGGERS[trigger]!} />);

      expect(screen.getByText("This applies to every trigger on this mailbox.")).toBeVisible();
      await userEvent.click(screen.getByRole("combobox", { name: "Check for new mail every" }));
      expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
        "1 minute",
        "5 minutes",
        "15 minutes",
        "30 minutes",
        "60 minutes",
      ]);
      await userEvent.click(screen.getByRole("option", { name: "15 minutes" }));

      expect(state.save).toHaveBeenCalledWith({ connectionId: "conn-1", minutes: 15 });
      expect(toast.success).toHaveBeenCalled();
    },
  );

  it("only shows the interval to a member without mcp:manage", () => {
    state.canManage = false;
    state.items = [
      {
        portal: {
          key: "google",
          name: "Gmail",
          connect_blocked_by: null,
          connection_id: "conn-1",
          connection_state: "connected",
          poll_interval_minutes: 30,
        },
        action: "create",
      },
    ];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);

    expect(screen.getByText("30 minutes")).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("says so when the interval could not be saved", async () => {
    state.items = [
      {
        portal: {
          key: "google",
          name: "Gmail",
          connect_blocked_by: null,
          connection_id: "conn-1",
          connection_state: "connected",
          poll_interval_minutes: 1,
        },
        action: "create",
      },
    ];
    state.save = vi.fn().mockRejectedValue(new Error("no"));
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "5 minutes" }));

    expect(toast.error).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("connects a mailbox nobody connected, through the portal's own flow", async () => {
    state.items = [gmail("connect")];
    vi.mocked(portalConnectUrl).mockResolvedValue("https://google/consent");
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);

    expect(screen.getByText(/Publishing waits for one/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(assign).toHaveBeenCalledWith("https://google/consent");
  });

  it("says whether the Outlook mailbox is connected and connects it", async () => {
    state.items = [outlook("create")];
    const { unmount } = render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.outlook"]!} />);
    expect(screen.getByText(/Microsoft 365 mailbox is connected/)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();

    state.items = [outlook("connect")];
    vi.mocked(portalConnectUrl).mockResolvedValue("https://microsoft/consent");
    const second = render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.outlook"]!} />);
    expect(screen.getByText(/No Microsoft 365 mailbox is connected/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(assign).toHaveBeenCalledWith("https://microsoft/consent");
    second.unmount();

    state.items = [outlook("reauthorize")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.outlook"]!} />);
    expect(screen.getByText(/needs connecting again/)).toBeVisible();
  });

  it("hides connecting the Outlook mailbox from a member without mcp:manage", () => {
    state.canManage = false;
    state.items = [outlook("connect")];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.outlook"]!} />);
    expect(screen.queryByRole("button")).toBeNull();
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

  it("stores the missing OAuth app from the step and refreshes its connection prerequisites", async () => {
    state.items = [
      {
        ...gmail("connect", "oauth_app_secret"),
        portal: {
          key: "google",
          name: "Gmail",
          connect_blocked_by: "oauth_app_secret",
          oauth_app_kind: "google_oauth_app",
        },
      },
    ];
    state.create.mockResolvedValue({ id: "secret-id" });
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    await userEvent.click(screen.getByRole("button", { name: "Add credentials" }));
    await userEvent.click(screen.getByRole("button", { name: "Store google_oauth_app" }));
    expect(state.create).toHaveBeenCalledWith({ name: "Google", visibility: "org" });
    await vi.waitFor(() => expect(state.invalidate).toHaveBeenCalled());
  });

  it("does not offer to store OAuth credentials without secret edit permission", () => {
    state.canStore = false;
    state.items = [
      {
        ...gmail("connect", "oauth_app_secret"),
        portal: {
          key: "google",
          name: "Gmail",
          connect_blocked_by: "oauth_app_secret",
          oauth_app_kind: "google_oauth_app",
        },
      },
    ];
    render(<PortalAccount account={ACCOUNT_TRIGGERS["trigger.gmail"]!} />);
    expect(screen.queryByRole("button", { name: "Add credentials" })).toBeNull();
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
