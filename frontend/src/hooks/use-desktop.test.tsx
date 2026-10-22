import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopState } from "@/lib/desktop/commands";
import { qk } from "@/lib/query-keys";

import {
  useDesktopState,
  useSetBlobby,
  useSetPinned,
  useSetShortcut,
  useSetWindowPreferences,
  useShellEvent,
} from "./use-desktop";

const shell = vi.hoisted(() => ({
  getDesktopState: vi.fn(),
  setBlobby: vi.fn(),
  setShortcut: vi.fn(),
  setWindowPreferences: vi.fn(),
  pinAgent: vi.fn(),
  unpinAgent: vi.fn(),
  listenShell: vi.fn(),
  reportShellFailure: vi.fn(),
}));

vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  getDesktopState: shell.getDesktopState,
  setBlobby: shell.setBlobby,
  setShortcut: shell.setShortcut,
  setWindowPreferences: shell.setWindowPreferences,
  pinAgent: shell.pinAgent,
  unpinAgent: shell.unpinAgent,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  listenShell: shell.listenShell,
  reportShellFailure: shell.reportShellFailure,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const STATE: DesktopState = {
  appearance: { look: "standard", mode: "system" },
  blobby: {
    enabled: true,
    character: { kind: "cast", id: "pebble" },
    chatter: "normal",
    activity: true,
    roams: true,
    size: 1,
    position: null,
  },
  pinned: [],
  shortcuts: [
    { action: "quick_ask", accelerator: "Alt+Space", problem: "taken" },
    { action: "screenshot_chat", accelerator: "CmdOrCtrl+Shift+A", problem: null },
  ],
  window: { keep_running: true, badge: true, launch_at_login: false },
};

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  vi.clearAllMocks();
  shell.getDesktopState.mockResolvedValue(STATE);
});

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});

describe("useDesktopState", () => {
  it("reads the desktop app's state inside the app", async () => {
    const { result } = renderHook(() => useDesktopState(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(STATE));
  });

  it("asks nothing in a browser", () => {
    delete window.__AGENTICOS_SHELL__;
    const { result } = renderHook(() => useDesktopState(), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(shell.getDesktopState).not.toHaveBeenCalled();
  });
});

describe("the changes", () => {
  it("write what the shell took into the cache", async () => {
    client.setQueryData(qk.desktop.state(), STATE);
    shell.setBlobby.mockResolvedValue(undefined);
    shell.setWindowPreferences.mockResolvedValue(undefined);
    shell.setShortcut.mockResolvedValue("Alt+K");
    const blobby = { ...STATE.blobby, roams: false };
    const windowPrefs = { ...STATE.window, badge: false };

    const set = renderHook(
      () => ({ b: useSetBlobby(), w: useSetWindowPreferences(), s: useSetShortcut() }),
      {
        wrapper,
      },
    );
    await act(() => set.result.current.b.mutateAsync(blobby));
    await act(() => set.result.current.w.mutateAsync(windowPrefs));
    await act(() =>
      set.result.current.s.mutateAsync({ action: "quick_ask", accelerator: "Alt+K" }),
    );

    const state = client.getQueryData<DesktopState>(qk.desktop.state());
    expect(state?.blobby).toEqual(blobby);
    expect(state?.window).toEqual(windowPrefs);
    expect(state?.shortcuts).toEqual([
      { action: "quick_ask", accelerator: "Alt+K", problem: null },
      STATE.shortcuts[1],
    ]);
  });

  it("pin and unpin an agent, keeping the list the shell answers with", async () => {
    client.setQueryData(qk.desktop.state(), STATE);
    const support = { id: "00000000-0000-4000-8000-000000000001", name: "Support" };
    shell.pinAgent.mockResolvedValue([support]);
    shell.unpinAgent.mockResolvedValue([]);
    const { result } = renderHook(() => useSetPinned(), { wrapper });

    await act(() => result.current.mutateAsync({ agent: support, pinned: true }));
    expect(shell.pinAgent).toHaveBeenCalledWith(support);
    expect(client.getQueryData<DesktopState>(qk.desktop.state())?.pinned).toEqual([support]);

    await act(() => result.current.mutateAsync({ agent: support, pinned: false }));
    expect(shell.unpinAgent).toHaveBeenCalledWith(support.id);
    expect(client.getQueryData<DesktopState>(qk.desktop.state())?.pinned).toEqual([]);
  });

  it("leave an empty cache empty", async () => {
    shell.setBlobby.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSetBlobby(), { wrapper });
    await act(() => result.current.mutateAsync(STATE.blobby));
    expect(client.getQueryData(qk.desktop.state())).toBeUndefined();
  });

  it("say a refusal in the catalog's words and log the shell's", async () => {
    const refusal = new Error("refused: Cannot write");
    shell.setBlobby.mockRejectedValue(refusal);
    const { result } = renderHook(() => useSetBlobby(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(STATE.blobby).catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledWith("The desktop app did not take that change.");
    expect(shell.reportShellFailure).toHaveBeenCalledWith("a change was refused", refusal);
  });
});

describe("useShellEvent", () => {
  it("hands each payload to the latest handler and stops listening on unmount", async () => {
    const stop = vi.fn();
    let emit: (payload: unknown) => void = () => {};
    shell.listenShell.mockImplementation(
      async (_event: string, handler: (payload: unknown) => void) => {
        emit = handler;
        return stop;
      },
    );
    const first = vi.fn();
    const second = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ handler }) => useShellEvent("desktop:say", handler),
      {
        initialProps: { handler: first },
      },
    );
    await waitFor(() => expect(shell.listenShell).toHaveBeenCalledTimes(1));
    rerender({ handler: second });
    emit("hello");
    expect(second).toHaveBeenCalledWith("hello");
    expect(first).not.toHaveBeenCalled();
    expect(shell.listenShell).toHaveBeenCalledTimes(1);
    unmount();
    expect(stop).toHaveBeenCalled();
  });

  it("stops a listener that arrives after the component has gone", async () => {
    const stop = vi.fn();
    let resolve: (stop: () => void) => void = () => {};
    shell.listenShell.mockReturnValue(new Promise((r) => (resolve = r)));
    const { unmount } = renderHook(() => useShellEvent("desktop:say", () => {}));
    unmount();
    resolve(stop);
    await waitFor(() => expect(stop).toHaveBeenCalled());
  });

  it("reports a listener the shell would not register, and listens to nothing in a browser", async () => {
    shell.listenShell.mockRejectedValue(new Error("nope"));
    renderHook(() => useShellEvent("desktop:say", () => {}));
    await waitFor(() =>
      expect(shell.reportShellFailure).toHaveBeenCalledWith("desktop:say", expect.any(Error)),
    );

    vi.clearAllMocks();
    delete window.__AGENTICOS_SHELL__;
    renderHook(() => useShellEvent("desktop:say", () => {}));
    expect(shell.listenShell).not.toHaveBeenCalled();
  });
});
