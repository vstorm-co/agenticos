import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { ReadinessScreen } from "./readiness-screen";
const env = vi.hoisted(() => ({
  finish: vi.fn<() => Promise<void>>(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  report: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "test", vibrancy: true }),
}));
vi.mock("@/hooks/use-desktop-setup", () => ({
  useDesktopSetup: () => ({ scope: "user-org", revision: "connection" }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => env }));
vi.mock("@/lib/desktop/commands", () => ({ finishOnboarding: env.finish }));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
vi.mock("./readiness-panel", () => ({ ReadinessPanel: () => <p>Permissions stay visible</p> }));
function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ReadinessScreen repair={null} connection />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  env.finish.mockResolvedValue();
});
it("prepares the dashboard and keeps setup visible with immediate feedback until saving finishes", async () => {
  let finish: (() => void) | undefined;
  env.finish.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  mount();
  expect(env.prefetch).toHaveBeenCalledWith("/dashboard");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("button", { name: "Opening your workspace…" })).toBeDisabled();
  expect(screen.getByText("Permissions stay visible")).toBeVisible();
  expect(env.replace).not.toHaveBeenCalled();
  await act(async () => finish?.());
  await waitFor(() => expect(env.replace).toHaveBeenCalledWith("/dashboard"));
});
it("retains a retryable screen when finishing fails", async () => {
  env.finish.mockRejectedValueOnce(new Error("Could not save"));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Please retry");
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  expect(env.replace).not.toHaveBeenCalled();
});
