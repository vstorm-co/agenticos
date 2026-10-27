import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveBrowse } from "./use-live-browse";
import { useAuthStore } from "@/stores";
import type { BrowserFrame } from "@/types/chat";

interface SocketOptions {
  url: string;
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

function receive(data: unknown) {
  act(() => socket.options!.onMessage({ data: JSON.stringify(data) } as MessageEvent));
}

function frame(overrides: Partial<BrowserFrame>): BrowserFrame {
  return { kind: "browser_step", call_id: "c1", step: 1, ...overrides };
}

beforeEach(() => {
  socket.options = null;
  socket.connect.mockReset();
  socket.disconnect.mockReset();
  socket.sendMessage.mockReset();
  useAuthStore.setState({ accessToken: "jwt", user: { id: "u1" } as never });
});

describe("useLiveBrowse", () => {
  it("opens the browse's own socket, for the signed-in person, with the token as a subprotocol", () => {
    const { unmount } = renderHook(() => useLiveBrowse("run 1", "c1"));

    expect(socket.options?.url).toBe("wss://api.example.com/api/v1/ws/browse/run%201/c1");
    expect(socket.options?.protocols()).toEqual(["access_token.jwt", "browse"]);
    expect(socket.options?.identity).toBe("u1");
    expect(socket.connect).toHaveBeenCalled();

    unmount();
    expect(socket.disconnect).toHaveBeenCalled();
  });

  it("does not connect, or offer a token, before there is one", () => {
    useAuthStore.setState({ accessToken: null });
    renderHook(() => useLiveBrowse("run-1", "c1"));

    expect(socket.connect).not.toHaveBeenCalled();
    expect(socket.options?.protocols()).toBeUndefined();
  });

  it("stays closed while it has nothing live to reach", () => {
    renderHook(() => useLiveBrowse("run-1", "c1", false));
    expect(socket.connect).not.toHaveBeenCalled();
  });

  it("starts from the snapshot - where a browse opened mid-way already is", () => {
    const { result } = renderHook(() => useLiveBrowse("run-1", "c1"));
    expect(result.current).toMatchObject({ browse: null, status: "connecting" });

    receive({
      type: "browser_snapshot",
      task: "Sign in to the portal",
      can_control: true,
      trace: [frame({ kind: "browser_opened", step: 0, goal: "Sign in" }), frame({ step: 1 })],
      frame: frame({ kind: "browser_frame", step: 1, image: "data:image/jpeg;base64,A" }),
    });

    expect(result.current).toMatchObject({
      task: "Sign in to the portal",
      canControl: true,
      status: "live",
    });
    expect(result.current.browse?.image).toBe("data:image/jpeg;base64,A");
    expect(result.current.browse?.steps).toHaveLength(1);
  });

  it("folds each live frame in after the snapshot", () => {
    const { result } = renderHook(() => useLiveBrowse("run-1", "c1"));
    receive({
      type: "browser_snapshot",
      task: "t",
      can_control: false,
      trace: [frame({ kind: "browser_opened", step: 0 })],
      frame: null,
    });

    receive(frame({ kind: "browser_held", step: 1, by: "Ada" }));

    expect(result.current.browse?.heldBy).toBe("Ada");
    expect(result.current.browse?.image).toBeNull();
  });

  it.each([
    [4404, "gone"],
    [4403, "forbidden"],
    [1011, "unavailable"],
  ] as const)("reads close code %i as %s", (code, status) => {
    const { result } = renderHook(() => useLiveBrowse("run-1", "c1"));
    act(() => socket.options!.onClose({ code } as CloseEvent));
    expect(result.current.status).toBe(status);
  });

  it("keeps waiting through a close that says nothing about the browse", () => {
    const { result } = renderHook(() => useLiveBrowse("run-1", "c1"));
    act(() => socket.options!.onClose({ code: 1006 } as CloseEvent));
    expect(result.current.status).toBe("connecting");
  });

  it("sends a person's command as it is", () => {
    const { result } = renderHook(() => useLiveBrowse("run-1", "c1"));
    result.current.send({ type: "click", x: 4, y: 2 });
    expect(socket.sendMessage).toHaveBeenCalledWith({ type: "click", x: 4, y: 2 });
  });
});

it("fetches a completed snapshot once, releases the socket and retains the final image", () => {
  const { result, rerender } = renderHook(({ run }) => useLiveBrowse(run, "c1"), {
    initialProps: { run: "run-1" },
  });
  receive({
    type: "browser_snapshot",
    task: "done",
    can_control: true,
    trace: [
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_finished", outcome: "done" }),
    ],
    frame: frame({ kind: "browser_frame", image: "data:image/jpeg;base64,FINAL" }),
  });
  expect(result.current.browse?.image).toBe("data:image/jpeg;base64,FINAL");
  expect(result.current.browse?.outcome).toBe("done");
  expect(socket.disconnect).toHaveBeenCalledTimes(1);
  rerender({ run: "run-2" });
  expect(result.current.browse).toBeNull();
  expect(socket.connect).toHaveBeenCalledTimes(2);
});
