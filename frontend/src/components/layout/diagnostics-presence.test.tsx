import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiagnosticsPresence } from "./diagnostics-presence";

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  auth: { user: { id: "account-1" }, isAuthenticated: true },
  config: { diagnosticsUrl: "http://localhost:8010" as string | undefined },
  shell: null as { platform: string } | null,
}));
vi.mock("@/lib/diagnostics", () => ({ sendPresence: mocks.send }));
vi.mock("@/stores", () => ({
  useAuthStore: (select: (state: typeof mocks.auth) => unknown) => select(mocks.auth),
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => mocks.config,
}));
vi.mock("@/lib/desktop/shell", () => ({
  readShellInfo: () => mocks.shell,
  isDesktopShell: (s: { platform: string } | null) => s?.platform === "macos",
  isMobileShell: (s: { platform: string } | null) => s?.platform === "ios",
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-31T12:00:00Z"));
  mocks.send.mockReset().mockResolvedValue("sent");
  mocks.auth.isAuthenticated = true;
  mocks.config.diagnosticsUrl = "http://localhost:8010";
  mocks.shell = null;
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("requires foreground input and does not keep an idle tab active", async () => {
  const mounted = render(<DiagnosticsPresence />);
  await act(async () => {
    vi.advanceTimersByTime(30_000);
  });
  expect(mocks.send).not.toHaveBeenCalled();
  await act(async () => {
    fireEvent.keyDown(document);
  });
  expect(mocks.send).toHaveBeenCalledTimes(1);
  await act(async () => {
    vi.advanceTimersByTime(6 * 60_000);
  });
  expect(mocks.send).toHaveBeenCalledTimes(1);
  await act(async () => {
    fireEvent.pointerDown(document);
  });
  expect(mocks.send).toHaveBeenCalledTimes(2);
  const signal: AbortSignal = mocks.send.mock.calls[1]?.[2];
  mounted.unmount();
  expect(signal.aborted).toBe(true);
});

it("does not report hidden, unfocused, signed-out or disabled sessions", async () => {
  const mounted = render(<DiagnosticsPresence />);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => {
    fireEvent.keyDown(document);
  });
  expect(mocks.send).not.toHaveBeenCalled();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.spyOn(document, "hasFocus").mockReturnValue(false);
  await act(async () => {
    fireEvent.keyDown(document);
  });
  expect(mocks.send).not.toHaveBeenCalled();
  mocks.auth.isAuthenticated = false;
  mounted.rerender(<DiagnosticsPresence />);
  await act(async () => {
    fireEvent.keyDown(document);
  });
  expect(mocks.send).not.toHaveBeenCalled();
  mocks.auth.isAuthenticated = true;
  mocks.config.diagnosticsUrl = undefined;
  mounted.rerender(<DiagnosticsPresence />);
  await act(async () => {
    fireEvent.keyDown(document);
  });
  expect(mocks.send).not.toHaveBeenCalled();
  mounted.unmount();
});

it.each(["macos", "ios"])(
  "uses the native shell surface for %s and handles network failure without a retry loop",
  async (platform) => {
    mocks.shell = { platform };
    mocks.send.mockRejectedValue(new Error("offline"));
    const mounted = render(<DiagnosticsPresence />);
    await act(async () => {
      fireEvent.keyDown(document);
    });
    expect(mocks.send).toHaveBeenCalledWith(
      platform === "macos" ? "desktop" : "mobile",
      "http://localhost:8010",
      expect.any(AbortSignal),
    );
    await act(async () => {
      fireEvent.keyDown(document);
    });
    expect(mocks.send).toHaveBeenCalledTimes(1);
    mounted.unmount();
  },
);

it("aborts a claim in flight when the tab becomes hidden", async () => {
  mocks.send.mockReturnValue(new Promise(() => {}));
  const view = render(<DiagnosticsPresence />);
  await act(async () => {
    fireEvent.keyDown(document);
  });
  const signal: AbortSignal = mocks.send.mock.calls[0]?.[2];
  expect(signal.aborted).toBe(false);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  fireEvent(document, new Event("visibilitychange"));
  expect(signal.aborted).toBe(true);
  view.unmount();
});
