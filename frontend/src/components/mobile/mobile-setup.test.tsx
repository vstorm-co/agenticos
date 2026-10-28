import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { MobileSetupGate } from "./mobile-setup";
const env = vi.hoisted(() => ({
  user: "existing-user",
  shell: { platform: "ios", version: "1", window: "main", vibrancy: false } as unknown,
  agents: [] as unknown[],
  push: vi.fn(),
  settings: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: env.agents, isLoading: false, error: null, refetch: vi.fn() }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (s: { user: { id: string } }) => unknown) =>
    pick({ user: { id: env.user } }),
}));
vi.mock("@/lib/mobile/settings", () => ({ mobileSettings: env.settings }));
vi.mock("@/lib/mobile/apns", () => ({ iphonePush: env.push }));
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
