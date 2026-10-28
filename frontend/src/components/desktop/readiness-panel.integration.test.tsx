import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { SetupItem } from "@/hooks/use-desktop-setup";
import { ReadinessPanel } from "./readiness-panel";
import { DesktopSetupGate } from "./desktop-setup-gate";
import { useDesktopPreferencesStore } from "@/stores/desktop-preferences-store";

const setup = vi.hoisted(() => ({
  items: [{ key: "screen_capture", state: "missing" }] as SetupItem[],
  scope: "existing-user-server-one",
  revision: "connection-one",
  canManageAgents: false,
  native: {
    status: { data: { screen_capture: "denied" } },
    request: { mutate: vi.fn(), isPending: false },
  },
  link: { mutate: vi.fn(), isPending: false },
  refresh: vi.fn(),
}));
const events = vi.hoisted(() => new Map<string, (v: unknown) => void>());
const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("@/hooks/use-desktop-setup", () => ({ useDesktopSetup: () => setup }));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "test", vibrancy: false }),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (event: string, callback: (v: unknown) => void) => events.set(event, callback),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => router }));
function mount(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
}
beforeEach(async () => {
  vi.clearAllMocks();
  events.clear();
  setup.items = [{ key: "screen_capture", state: "missing" }];
  setup.scope = "existing-user-server-one";
  setup.revision = "connection-one";
  setup.canManageAgents = false;
  useDesktopPreferencesStore.setState({ reviewed: {}, notifications: {} });
  await useDesktopPreferencesStore.persist.rehydrate();
  useDesktopPreferencesStore.setState({ reviewed: {}, notifications: {} });
});
it("checks an existing account after connection, honours Later and rechecks a new connection", async () => {
  const user = userEvent.setup();
  const view = mount(<DesktopSetupGate />);
  expect(await screen.findByRole("dialog")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Later" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(useDesktopPreferencesStore.getState().reviewed[setup.scope]).toBe("connection-one");
  view.unmount();
  const again = mount(<DesktopSetupGate />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  setup.revision = "connection-two";
  again.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <DesktopSetupGate />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
});
it("requests one permission only on a click and offers connection repair", async () => {
  setup.items = [
    { key: "screen_capture", state: "missing" },
    { key: "microphone", state: "ready" },
    { key: "device", state: "missing" },
  ];
  mount(<ReadinessPanel />);
  expect(setup.native.request.mutate).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Set up" }));
  expect(setup.native.request.mutate).toHaveBeenCalledWith("screen_capture");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(setup.link.mutate).toHaveBeenCalled();
});
it("does not offer administrator controls to an existing member", () => {
  setup.items = [
    { key: "model", state: "missing" },
    { key: "agent", state: "missing", href: "/agents" },
  ];
  mount(<ReadinessPanel />);
  expect(screen.getByText(/Ask an administrator to configure/)).toBeVisible();
  expect(screen.getByText(/Ask an administrator to publish/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Configure" })).not.toBeInTheDocument();
});
it("reports failed probes instead of pretending they are unconfigured", async () => {
  setup.items = [{ key: "notifications", state: "error" }];
  mount(<ReadinessPanel />);
  expect(screen.getByText("Could not check — retry")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(setup.refresh).toHaveBeenCalled();
});
