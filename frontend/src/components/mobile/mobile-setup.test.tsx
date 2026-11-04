import { renderToString } from "react-dom/server";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { MobileSetupGate, MobileSetupPanel, mobileNotificationState } from "./mobile-setup";
const env = vi.hoisted(() => ({
  user: "existing-user",
  agentLoading: false,
  agentError: null as Error | null,
  shell: { platform: "ios", version: "1", window: "main", vibrancy: false } as unknown,
  agents: [] as unknown[],
  push: vi.fn(),
  settings: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: env.agents,
    isLoading: env.agentLoading,
    error: env.agentError,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (s: { user: { id: string } }) => unknown) =>
    pick({ user: { id: env.user } }),
}));
vi.mock("@/lib/mobile/settings", () => ({ mobileSettings: env.settings }));
vi.mock("@/lib/mobile/apns", () => ({ iphonePush: env.push }));
vi.mock("@/lib/mobile/push", () => ({ phonePushStatus: env.push }));
vi.mock("./iphone-push", () => ({ IphonePush: () => null }));
vi.mock("./phone-push", () => ({ PhonePush: () => null }));
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MobileSetupGate />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  env.user = "existing-user";
  env.agentLoading = false;
  env.agentError = null;
  env.agents = [];
  env.shell = { platform: "ios", version: "1", window: "main", vibrancy: false };
  env.settings.mockResolvedValue({ biometric_lock: true, biometric_available: true });
  env.push.mockResolvedValue({ configured: true, permission: "granted", token: "token" });
});
it("reviews an existing account, remembers postponement and isolates accounts", async () => {
  const first = show();
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText("An agent you can use")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  first.unmount();
  const next = show();
  await waitFor(() => expect(env.push.mock.calls.length).toBeGreaterThanOrEqual(2));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  next.unmount();
  env.user = "another-user";
  show();
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});
it("does not offer setup when everything is ready or show phone UI in a browser", async () => {
  env.agents = [{ status: "published", can_run: true }];
  const ready = show();
  await waitFor(() => expect(env.push).toHaveBeenCalled());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  ready.unmount();
  vi.clearAllMocks();
  env.shell = null;
  show();
  expect(env.push).not.toHaveBeenCalled();
});
it("reopens review after a permission is revoked", async () => {
  const first = show();
  await screen.findByRole("dialog");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  first.unmount();
  env.push.mockResolvedValue({ configured: true, permission: "denied", token: null });
  show();
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText("Notifications")).toBeInTheDocument();
});

function panel() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MobileSetupPanel />
    </QueryClientProvider>,
  );
}
it("offers the permanent phone checklist and refreshes its facts", async () => {
  const view = panel();
  expect(await screen.findByRole("link", { name: "Open" })).toHaveAttribute("href", "/agents");
  await userEvent.click(screen.getByRole("button", { name: "Check again" }));
  await waitFor(() => expect(env.settings.mock.calls.length).toBeGreaterThan(1));
  await act(async () => {
    window.dispatchEvent(new Event("mobile:push-changed"));
  });
  view.unmount();
  env.shell = null;
  panel();
  expect(screen.queryByRole("button")).toBeNull();
});
it("reports failed and unavailable probes without marking them ready", async () => {
  env.settings.mockRejectedValue(new Error("offline"));
  env.push.mockRejectedValue(new Error("offline"));
  env.agentError = new Error("offline");
  const view = panel();
  await waitFor(() => expect(screen.getAllByText("Could not check. Try again.")).toHaveLength(3));
  view.unmount();
  env.agentError = null;
  env.agentLoading = true;
  env.settings.mockResolvedValue({ biometric_available: false, biometric_lock: false });
  env.push.mockResolvedValue({ configured: false, permission: "denied", token: null });
  panel();
  expect(await screen.findByText("Not available on this device")).toBeVisible();
});
it("dismisses with Escape and tolerates unavailable browser storage", async () => {
  const get = vi.spyOn(localStorage, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const set = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const view = show();
  expect(await screen.findByRole("dialog")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  view.unmount();
  get.mockRestore();
  set.mockRestore();
  env.user = "";
  show();
  await waitFor(() => expect(env.push).toHaveBeenCalled());
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("keeps first server rendering free of a native setup dialog", () => {
  const html = renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MobileSetupGate />
    </QueryClientProvider>,
  );
  expect(html).not.toContain('role="dialog"');
});
it("distinguishes Android registration, denied permission and a wrong native response", () => {
  const base = { distributors: [], distributor: null, failed: null, subscription: null };
  expect(mobileNotificationState("android", base)).toBe("missing");
  const on = {
    ...base,
    subscription: { endpoint: "https://ntfy.example/t", keys: { p256dh: "key", auth: "auth" } },
  };
  expect(mobileNotificationState("android", on)).toBe("ready");
  expect(mobileNotificationState("android", { ...on, permission: "denied" })).toBe("missing");
  expect(mobileNotificationState("android", { ...on, permission: "granted" })).toBe("ready");
  expect(
    mobileNotificationState("android", { configured: true, permission: "granted", token: "token" }),
  ).toBe("error");
});
