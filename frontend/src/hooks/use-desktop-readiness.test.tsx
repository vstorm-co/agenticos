import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { toast } from "sonner";
import type { ReactNode } from "react";
import { useDesktopReadiness } from "./use-desktop-readiness";
import { readDesktopReadiness, requestDesktopPermission } from "@/lib/desktop/readiness";
vi.mock("./use-shell", () => ({ useShell: () => ({ platform: "macos" }) }));
vi.mock("@/lib/desktop/readiness", () => ({
  readDesktopReadiness: vi.fn(),
  requestDesktopPermission: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
it("preflights without prompting, refreshes after consent and surfaces refusal", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const data = {
    connection_revision: "c",
    screen_capture: "granted",
    accessibility: "granted",
    microphone: "granted",
    notifications: "granted",
  } as const;
  vi.mocked(readDesktopReadiness).mockResolvedValue(data);
  vi.mocked(requestDesktopPermission).mockResolvedValue();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(useDesktopReadiness, { wrapper });
  await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
  expect(requestDesktopPermission).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.request.mutateAsync("microphone");
  });
  expect(vi.mocked(requestDesktopPermission).mock.calls[0]?.[0]).toBe("microphone");
  vi.mocked(requestDesktopPermission).mockRejectedValue(new Error("denied"));
  await act(async () => {
    await result.current.request.mutateAsync("notifications").catch(() => undefined);
  });
  expect(toast.error).toHaveBeenCalled();
});
