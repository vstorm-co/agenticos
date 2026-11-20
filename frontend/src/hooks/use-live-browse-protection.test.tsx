import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useCallback, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLiveBrowse } from "./use-live-browse";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  applyBrowserProtection,
  withLivePreview,
  type Browse,
  type BrowserProtection,
} from "@/lib/browse";
import type { BrowserFrame } from "@/types/chat";

interface SocketOptions {
  identity?: string;
  protocols: () => string[] | undefined;
  onMessage: (message: MessageEvent) => void;
  onClose: (event: CloseEvent) => void;
}
const socket = vi.hoisted(() => ({
  options: null as SocketOptions | null,
  connect: vi.fn(),
  disconnect: vi.fn(),
  sendMessage: vi.fn(),
}));
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (options: SocketOptions) => {
    socket.options = options;
    return {
      connect: socket.connect,
      disconnect: socket.disconnect,
      sendMessage: socket.sendMessage,
    };
  },
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ wsUrl: "wss://api.example.com" }),
}));
const frame = (overrides: Partial<BrowserFrame>): BrowserFrame => ({
  kind: "browser_frame",
  call_id: "call",
  run_id: "run",
  tab_id: "main",
  step: 2,
  ...overrides,
});
function receive(value: unknown, options = socket.options!) {
  act(() => options.onMessage({ data: JSON.stringify(value) } as MessageEvent));
}
const rawSnapshot = () => ({
  type: "browser_snapshot",
  task: "private task",
  can_control: true,
  can_remember: true,
  trace: [
    frame({ kind: "browser_opened", goal: "private goal", navigable: true, native_id: "native" }),
  ],
  frame: frame({ image: "OLD", url: "https://portal.example/private", title: "private title" }),
});
beforeEach(() => {
  vi.clearAllMocks();
  socket.options = null;
  useAuthStore.setState({ accessToken: "jwt", user: { id: "user" } as never });
  useOrgStore.setState({ activeOrgId: "org" });
});

describe("protected live browse", () => {
  it("does not connect or expose a protocol for an anonymous viewer", () => {
    useAuthStore.setState({ user: null });
    const { result } = renderHook(() => useLiveBrowse("run", "call"));
    expect(socket.connect).not.toHaveBeenCalled();
    expect(socket.options!.protocols()).toBeUndefined();
    result.current.send({ type: "click", x: 0, y: 0 });
    expect(socket.sendMessage).not.toHaveBeenCalled();
  });
  it("keeps early addressed events without inventing permission, then protects a tab with no supplied tab ID", () => {
    const onProtected = vi.fn();
    const { result } = renderHook(() => useLiveBrowse("run", "call", true, onProtected));
    receive(frame({ kind: "browser_opened", tab_id: undefined }));
    expect(result.current).toMatchObject({
      task: "",
      canControl: false,
      canRemember: false,
      status: "connecting",
    });
    receive(frame({ kind: "browser_protected", tab_id: undefined }));
    expect(onProtected).toHaveBeenCalledExactlyOnceWith({
      callId: "call",
      runId: "run",
      tabId: null,
    });
    expect(result.current.browse).toMatchObject({ outputProtected: true, image: null });
  });
  it("retains only the scrubbed receipt metadata if a protected connection is later refused", () => {
    const { result } = renderHook(() => useLiveBrowse("run", "call"));
    receive(rawSnapshot());
    receive(frame({ kind: "browser_protected" }));
    act(() => socket.options!.onClose({ code: 4403 } as CloseEvent));
    expect(result.current).toMatchObject({
      status: "forbidden",
      task: "",
      canControl: false,
      canRemember: false,
    });
    expect(result.current.browse).toMatchObject({
      outputProtected: true,
      image: null,
      url: null,
      title: null,
    });
  });
  it("also clears this view and its parent from an authoritative protected HTTP receipt", () => {
    const onProtected = vi.fn();
    const { result } = renderHook(() => useLiveBrowse("run", "call", true, onProtected));
    receive(rawSnapshot());
    const sendBefore = result.current.send;
    act(() => result.current.protect());
    act(() => result.current.protect());
    expect(onProtected).toHaveBeenCalledExactlyOnceWith({ callId: "call", runId: "run" });
    expect(result.current.browse).toMatchObject({ outputProtected: true, image: null, url: null });
    expect(result.current).toMatchObject({ task: "", canControl: false, canRemember: false });
    sendBefore({ type: "click", x: 1, y: 1 });
    expect(socket.sendMessage).not.toHaveBeenCalled();
  });

  it("does not expose the first snapshot if a protected receipt arrived before it", () => {
    const { result } = renderHook(() => useLiveBrowse("run", "call"));
    act(() => result.current.protect());
    receive(rawSnapshot());
    expect(result.current.browse).toMatchObject({ outputProtected: true, image: null });
  });

  it("ignores a late receipt callback from the previous organization", () => {
    const onProtected = vi.fn();
    const { result } = renderHook(() => useLiveBrowse("run", "call", true, onProtected));
    const old = result.current.protect;
    act(() => useOrgStore.setState({ activeOrgId: "other" }));
    act(() => old());
    expect(onProtected).not.toHaveBeenCalled();
    expect(result.current.browse).toBeNull();
  });
  it("derives protection from every nested event and discards a mixed cached image and controls", () => {
    const onProtected = vi.fn();
    const { result } = renderHook(() => useLiveBrowse("run", "call", true, onProtected));
    const snapshot = rawSnapshot();
    receive({
      ...snapshot,
      trace: [...snapshot.trace, frame({ kind: "browser_protected", step: 3 })],
    });
    expect(result.current).toMatchObject({
      task: "",
      canControl: false,
      canRemember: false,
      status: "live",
    });
    expect(result.current.browse).toMatchObject({
      outputProtected: true,
      image: null,
      title: null,
      url: null,
      steps: [],
      goal: "",
      nativeId: null,
    });
    expect(onProtected).toHaveBeenCalledWith({ callId: "call", runId: "run", tabId: "main" });
    result.current.send({ type: "type", text: "never send" });
    expect(socket.sendMessage).not.toHaveBeenCalled();
  });

  it("reconstructs only the addressed authorized protected snapshot when there is no opening event", () => {
    const { result } = renderHook(() => useLiveBrowse("run", "call"));
    receive({
      type: "browser_snapshot",
      task: "must hide",
      can_control: true,
      trace: [],
      frame: frame({ kind: "browser_step", output_protected: true, image: "LEAK" }),
    });
    expect(result.current.browse).toMatchObject({
      callId: "call",
      runId: "run",
      outputProtected: true,
      image: null,
    });
    expect(result.current.task).toBe("");
  });

  it("cannot restore an older preview after protection, a late false flag, reconnect or completion", () => {
    const { result } = renderHook(() => useLiveBrowse("run", "call"));
    receive(rawSnapshot());
    const sendBefore = result.current.send;
    receive(frame({ kind: "browser_protected" }));
    receive(frame({ image: "LATE", output_protected: false }));
    receive(rawSnapshot());
    receive(frame({ kind: "browser_finished", outcome: "done", image: "FINISHED" }));
    expect(result.current.browse).toMatchObject({
      outputProtected: true,
      image: null,
      url: null,
      outcome: "done",
    });
    expect(result.current.task).toBe("");
    sendBefore({ type: "click", x: 1, y: 1 });
    expect(socket.sendMessage).not.toHaveBeenCalled();
  });

  it.each(["account", "organization", "run", "call"] as const)(
    "hides the old view immediately and rejects delayed callbacks after a %s change",
    (changed) => {
      const onProtected = vi.fn();
      const { result, rerender } = renderHook(
        ({ run, call }) => useLiveBrowse(run, call, true, onProtected),
        { initialProps: { run: "run", call: "call" } },
      );
      receive(rawSnapshot());
      const before = socket.options!;
      const sendBefore = result.current.send;
      act(() => {
        if (changed === "account") useAuthStore.setState({ user: { id: "new-user" } as never });
        if (changed === "organization") useOrgStore.setState({ activeOrgId: "new-org" });
      });
      rerender({
        run: changed === "run" ? "new-run" : "run",
        call: changed === "call" ? "new-call" : "call",
      });
      expect(result.current).toMatchObject({
        browse: null,
        task: "",
        canControl: false,
        canRemember: false,
        status: "connecting",
      });
      receive(frame({ kind: "browser_protected" }), before);
      act(() => before.onClose({ code: 4403 } as CloseEvent));
      sendBefore({ type: "click", x: 1, y: 1 });
      expect(result.current.status).toBe("connecting");
      expect(result.current.browse).toBeNull();
      expect(onProtected).not.toHaveBeenCalled();
      expect(before.protocols()).toBeUndefined();
      expect(socket.sendMessage).not.toHaveBeenCalled();
    },
  );

  it("ignores unrelated snapshot calls and callbacks after the view was closed", () => {
    const onProtected = vi.fn();
    const { result, unmount } = renderHook(() => useLiveBrowse("run", "call", true, onProtected));
    receive({
      ...rawSnapshot(),
      trace: [frame({ kind: "browser_protected", call_id: "other" })],
      frame: null,
    });
    expect(result.current.browse).toBeNull();
    const before = socket.options!;
    unmount();
    receive(frame({ kind: "browser_protected" }), before);
    expect(onProtected).not.toHaveBeenCalled();
  });

  it("clears the parent cache so a closed and reopened panel has no old image while reconnecting", () => {
    const initial: Browse = {
      callId: "call",
      runId: "run",
      tabId: "main",
      goal: "",
      maxSteps: null,
      url: "https://portal.example/private",
      title: "private",
      steps: [],
      image: "OLD",
      imageStep: 1,
      outcome: null,
      detail: null,
    };
    function View({
      browse,
      protect,
    }: {
      browse: Browse;
      protect: (value: BrowserProtection) => void;
    }) {
      const live = useLiveBrowse("run", "call", true, protect);
      const current = withLivePreview(browse, live.browse);
      return <div data-testid="view">{current.outputProtected ? "Protected" : current.image}</div>;
    }
    function Harness() {
      const [browses, setBrowses] = useState([initial]);
      const [open, setOpen] = useState(true);
      const protect = useCallback(
        (value: BrowserProtection) => setBrowses((before) => applyBrowserProtection(before, value)),
        [],
      );
      return (
        <>
          <button onClick={() => setOpen((value) => !value)}>Toggle view</button>
          {open && <View browse={browses[0]!} protect={protect} />}
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByTestId("view")).toHaveTextContent("OLD");
    receive(rawSnapshot());
    receive(frame({ kind: "browser_protected" }));
    expect(screen.getByTestId("view")).toHaveTextContent("Protected");
    fireEvent.click(screen.getByRole("button", { name: "Toggle view" }));
    fireEvent.click(screen.getByRole("button", { name: "Toggle view" }));
    expect(screen.getByTestId("view")).toHaveTextContent("Protected");
    expect(screen.queryByText("OLD")).not.toBeInTheDocument();
  });
});
