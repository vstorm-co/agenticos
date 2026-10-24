import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopState } from "@/lib/desktop/commands";
import { qk } from "@/lib/query-keys";

import {
  useDeviceStatus,
  useDeviceLink,
  useLocalFolders,
  useLocalWorkspace,
  useDesktopState,
  useSetBlobby,
  useSetPinned,
  useSetShortcut,
  useSetWindowPreferences,
  useShellEvent,
} from "./use-desktop";

const shell = vi.hoisted(() => ({
  getDeviceStatus: vi.fn(),
  linkDevice: vi.fn(),
  unlinkDevice: vi.fn(),
  getLocalState: vi.fn(),
  pickLocalFolder: vi.fn(),
  revokeLocalFolder: vi.fn(),
  listLocalFiles: vi.fn(),
  createPairingCode: vi.fn(),
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
  getDeviceStatus: shell.getDeviceStatus,
  linkDevice: shell.linkDevice,
  unlinkDevice: shell.unlinkDevice,
  getLocalState: shell.getLocalState,
  pickLocalFolder: shell.pickLocalFolder,
  revokeLocalFolder: shell.revokeLocalFolder,
  listLocalFiles: shell.listLocalFiles,
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
vi.mock("@/lib/pairing-api", () => ({ createPairingCode: shell.createPairingCode }));
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
  shell.listenShell.mockReset();
  shell.listenShell.mockResolvedValue(vi.fn());
  shell.getDeviceStatus.mockResolvedValue({ linked: true, connected: true });
  shell.getLocalState.mockResolvedValue({ grants: [], modes: ["read_only"] });
});

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});

describe("useDesktopState", () => {
  it("does not send desktop commands from the iPhone app", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "ios",
      version: "0.1.0",
      window: "main",
      vibrancy: false,
    };
    const { result } = renderHook(() => useDesktopState(), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(shell.getDesktopState).not.toHaveBeenCalled();
  });

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

describe("paired devices and native folders", () => {
  it("updates device state from native events and removes the listener", async () => {
    const stop = vi.fn();
    let emit: (payload: unknown) => void = () => {};
    shell.listenShell.mockImplementation(
      async (_name: string, handler: (payload: unknown) => void) => {
        emit = handler;
        return stop;
      },
    );
    const { result, unmount } = renderHook(() => useDeviceStatus(), { wrapper });
    await waitFor(() => expect(result.current.data?.connected).toBe(true));
    act(() => emit({ linked: true, connected: false }));
    await waitFor(() => expect(result.current.data?.connected).toBe(false));
    unmount();
    expect(stop).toHaveBeenCalledOnce();
  });
  it("mints one pairing code and keeps the native link/unlink result", async () => {
    shell.createPairingCode.mockResolvedValue({ code: "one-time" });
    shell.linkDevice.mockResolvedValue({ linked: true, connected: false });
    shell.unlinkDevice.mockResolvedValue({ linked: false, connected: false });
    const { result } = renderHook(() => useDeviceLink(), { wrapper });
    await act(() => result.current.link.mutateAsync());
    expect(shell.linkDevice).toHaveBeenCalledWith("one-time");
    expect(client.getQueryData(qk.desktop.device())).toEqual({ linked: true, connected: false });
    await act(() => result.current.unlink.mutateAsync());
    expect(client.getQueryData(qk.desktop.device())).toEqual({ linked: false, connected: false });
  });
  it("reports link and unlink failures without changing cached authority", async () => {
    shell.createPairingCode.mockRejectedValueOnce(new Error("offline"));
    shell.unlinkDevice.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useDeviceLink(), { wrapper });
    await act(() => result.current.link.mutateAsync().catch(() => undefined));
    await act(() => result.current.unlink.mutateAsync().catch(() => undefined));
    expect(toast.error).toHaveBeenCalledTimes(2);
    expect(client.getQueryData(qk.desktop.device())).toBeUndefined();
  });
  it("refreshes granted folders after a native selection and applies revocation", async () => {
    const grant = { path: "/approved", mode: "read_only" } as const;
    shell.pickLocalFolder.mockResolvedValue(grant);
    shell.revokeLocalFolder.mockResolvedValue({ grants: [], modes: ["read_only"] });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useLocalFolders(), { wrapper });
    await waitFor(() => expect(result.current.state.data).toBeDefined());
    await act(() => result.current.pick.mutateAsync("read_only"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.desktop.local() });
    await act(() => result.current.revoke.mutateAsync(grant.path));
    expect(client.getQueryData(qk.desktop.local())).toEqual({ grants: [], modes: ["read_only"] });
    shell.pickLocalFolder.mockRejectedValueOnce(new Error("refused"));
    shell.revokeLocalFolder.mockRejectedValueOnce(new Error("refused"));
    await act(() => result.current.pick.mutateAsync("read_only").catch(() => undefined));
    await act(() => result.current.revoke.mutateAsync(grant.path).catch(() => undefined));
    expect(shell.reportShellFailure).toHaveBeenCalledWith("revoking a folder", expect.any(Error));
    expect(toast.error).toHaveBeenCalledOnce();
  });
  it("presents bounded native files through the shared workspace contract", async () => {
    shell.listLocalFiles.mockResolvedValue([
      { path: "note.txt", size: 5, is_dir: false, modified: 1 },
      { path: "folder", size: null, is_dir: true, modified: null },
    ]);
    const { result } = renderHook(() => useLocalWorkspace("/approved", "This computer"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace?.total).toBe(2));
    expect(result.current.workspace).toMatchObject({
      scope: "local",
      bytes_total: 5,
      owner_label: "This computer",
    });
    expect(result.current.workspace?.items[0]?.modified_at).toBe("1970-01-01T00:00:01.000Z");
    await act(() => result.current.refresh());
    expect(shell.listLocalFiles).toHaveBeenCalledWith("/approved");
  });
  it("does not read an unselected folder and reports a native read failure", async () => {
    const unset = renderHook(() => useLocalWorkspace(null, "This computer"), { wrapper });
    await act(() => unset.result.current.refresh());
    expect(unset.result.current.workspace).toBeNull();
    expect(shell.listLocalFiles).not.toHaveBeenCalled();
    shell.listLocalFiles.mockRejectedValueOnce(new Error("refused"));
    const selected = renderHook(() => useLocalWorkspace("/missing", "This computer"), { wrapper });
    await waitFor(() => expect(selected.result.current.error).not.toBeNull());
    expect(selected.result.current.workspace).toBeNull();
  });
});
