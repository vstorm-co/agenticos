import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { viewState } from "@/lib/voice/call-reducer";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";
import { useAuthStore, useOrgStore, useVoiceCallStore } from "@/stores";
import type { VoiceServerFrame } from "@/types/voice";

import { PLAYED_EVERY_MS } from "@/lib/voice/pcm";

import { RECONNECT_DELAY_MS, RESUME_WINDOW_MS, useVoiceSession } from "./use-voice-session";

/** The relay's audio, faked: what matters here is what the hook wires to what. */
const relay = vi.hoisted(() => ({
  context: { sampleRate: 48_000 } as unknown,
  onChunk: null as ((pcm: ArrayBuffer) => void) | null,
  onDrained: null as (() => void) | null,
  played: 4800,
  capture: { stop: () => {} },
  player: {
    stream: { id: "agent" },
    enqueue: (_pcm: ArrayBuffer) => {},
    playedBytes: () => relay.played,
    clear: () => {},
    close: () => {},
  },
}));

vi.mock("voice-glow", async (original) => ({
  ...(await original<typeof import("voice-glow")>()),
  getAudioContext: vi.fn(() => relay.context),
}));

vi.mock("@/lib/voice/pcm", async (original) => ({
  ...(await original<typeof import("@/lib/voice/pcm")>()),
  createPcmCapture: vi.fn(
    (_context: unknown, _stream: unknown, _rate: number, onChunk: (pcm: ArrayBuffer) => void) => {
      relay.onChunk = onChunk;
      return relay.capture;
    },
  ),
  createPcmPlayer: vi.fn((_context: unknown, _rate: number, onDrained: () => void) => {
    relay.onDrained = onDrained;
    return relay.player;
  }),
}));

/** A fake socket: what the hook must get right is which frames it sends, and when. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static last = () => FakeSocket.instances[FakeSocket.instances.length - 1]!;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  binaryType = "blob";
  onclose: (() => void) | null = null;
  readyState = 0;
  sent: unknown[] = [];
  close = vi.fn(() => {
    this.readyState = 3;
  });

  constructor(
    readonly url: string,
    readonly protocols?: string[],
  ) {
    FakeSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(typeof data === "string" ? JSON.parse(data) : { binary: data.byteLength });
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(frame: VoiceServerFrame) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  receiveAudio(pcm: ArrayBuffer) {
    this.onmessage?.({ data: pcm });
  }

  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

let offerSdp = "v=0\r\nm=audio 9 UDP 111\r\n";

class FakePc {
  static instances: FakePc[] = [];
  static last = () => FakePc.instances[FakePc.instances.length - 1]!;

  ontrack: ((event: { streams: MediaStream[] }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  oniceconnectionstatechange: (() => void) | null = null;
  connectionState = "new";
  iceConnectionState = "new";
  localDescription: { sdp: string } | null = null;
  addTrack = vi.fn();
  createDataChannel = vi.fn();
  close = vi.fn();
  setRemoteDescription = vi.fn().mockResolvedValue(undefined);
  createOffer = vi.fn(async () => ({ type: "offer", sdp: offerSdp }));
  setLocalDescription = vi.fn(async (description: { sdp: string }) => {
    this.localDescription = description;
  });

  constructor() {
    FakePc.instances.push(this);
  }
}

let micTrack: { enabled: boolean; stop: ReturnType<typeof vi.fn>; kind: string };
let micStream: MediaStream;

function stubMic(answer: () => Promise<MediaStream>) {
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn(answer) } });
}

const READY: VoiceServerFrame = {
  type: "ready",
  call_id: "c1",
  run_id: "r1",
  conversation_id: "conv1",
  transport: "webrtc",
  input_sample_rate: 24000,
  output_sample_rate: 24000,
  cap_seconds: 600,
  resume_token: "tok1",
};

function wrapper({ children }: { children: ReactNode }) {
  return (
    <PublicConfigProvider config={{ ...DEFAULT_PUBLIC_CONFIG, wsUrl: "wss://x" }}>
      {children}
    </PublicConfigProvider>
  );
}

beforeEach(() => {
  FakeSocket.instances = [];
  FakePc.instances = [];
  offerSdp = "v=0\r\nm=audio 9 UDP 111\r\n";
  micTrack = { enabled: true, stop: vi.fn(), kind: "audio" };
  micStream = {
    getAudioTracks: () => [micTrack],
    getTracks: () => [micTrack],
  } as unknown as MediaStream;
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("RTCPeerConnection", FakePc);
  stubMic(() => Promise.resolve(micStream));
  useAuthStore.setState({
    accessToken: "jwt",
    user: { id: "user1", email: "user1@example.com", is_active: true, created_at: "2026-10-24" },
  });
  useOrgStore.setState({ activeOrgId: "org1" });
  useVoiceCallStore.setState({ pushToTalk: false });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useVoiceSession", () => {
  it("offers without a data channel, sends start, and applies the answer", async () => {
    const onConversation = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onConversation }), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: "conv0",
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());

    expect(socket.url).toBe("wss://x/api/v1/ws/voice?organization_id=org1");
    expect(socket.protocols).toEqual(["access_token.jwt", "voice"]);
    expect(socket.sent[0]).toMatchObject({
      type: "start",
      agent_id: "a1",
      conversation_id: "conv0",
      sdp_offer: offerSdp,
    });
    expect(socket.sent[0]).not.toHaveProperty("resume_of");
    expect(FakePc.last().createDataChannel).not.toHaveBeenCalled();
    expect(FakePc.last().addTrack).toHaveBeenCalledWith(micTrack, micStream);
    expect(result.current.localStream).toBe(micStream);

    act(() => socket.receive({ type: "answer", sdp: "answer-sdp" }));
    expect(FakePc.last().setRemoteDescription).toHaveBeenCalledWith({
      type: "answer",
      sdp: "answer-sdp",
    });
    act(() => socket.receive(READY));
    expect(result.current.call.phase).toBe("live");
    // The server started a new conversation in place of the one asked for.
    expect(onConversation).toHaveBeenCalledWith("conv1");
  });

  it("does not report the conversation it was already in", async () => {
    const onConversation = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onConversation }), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: "conv1",
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
    });
    expect(onConversation).not.toHaveBeenCalled();
  });

  it("plays what the agent says through the remote stream", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const remote = {} as MediaStream;
    act(() => FakePc.last().ontrack?.({ streams: [remote] }));
    expect(result.current.remoteStream).toBe(remote);
    act(() => FakePc.last().ontrack?.({ streams: [] }));
    expect(result.current.remoteStream).toBeNull();
  });

  it.each([
    ["NotAllowedError", "mic_denied"],
    ["SecurityError", "mic_denied"],
    ["NotFoundError", "mic_not_found"],
    ["OverconstrainedError", "mic_not_found"],
    ["NotReadableError", "mic_busy"],
  ])("says why the microphone did not open (%s), and opens no socket", async (name, failure) => {
    stubMic(() => Promise.reject(Object.assign(new Error("no"), { name })));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(result.current.call.failure).toBe(failure);
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("treats a thrown non-error as a busy microphone", async () => {
    stubMic(() => Promise.reject("nope"));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(result.current.call.failure).toBe("mic_busy");
  });

  it("says the page cannot ask for a microphone where the browser offers none", async () => {
    vi.stubGlobal("navigator", {});
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(result.current.call.failure).toBe("mic_insecure");
    expect(viewState(result.current.call)).toBe("micblocked");
  });

  it("refuses an offer carrying a data channel before any socket opens", async () => {
    offerSdp = "v=0\r\nm=audio 9 x\r\nm=application 9 x\r\n";
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(FakeSocket.instances).toHaveLength(0);
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("says the call could not connect when the socket closes before it is ready", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().drop());
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(FakeSocket.instances).toHaveLength(1);
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("retries once, resuming the call, when a live socket drops", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const first = FakeSocket.last();
    act(() => {
      first.open();
      first.receive(READY);
      first.drop();
    });
    expect(result.current.call.phase).toBe("reconnecting");
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(micTrack.stop).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    const second = FakeSocket.last();
    expect(second).not.toBe(first);
    act(() => second.open());
    // The call's id alone proves nothing: the token its `ready` gave this caller does.
    expect(second.sent[0]).toMatchObject({
      type: "start",
      resume_of: "c1",
      resume_token: "tok1",
      conversation_id: "conv1",
    });
    act(() => second.receive({ ...READY, call_id: "c2", resume_token: "tok2" }));
    expect(result.current.call.phase).toBe("live");

    // One logical retry: a resumed call that drops again is over.
    act(() => second.drop());
    expect(result.current.call.phase).toBe("ended");
    expect(viewState(result.current.call)).toBe("dropped");
    expect(micTrack.stop).toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(RESUME_WINDOW_MS));
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("tells the server a muted caller is still muted once the call resumes", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const first = FakeSocket.last();
    act(() => {
      first.open();
      first.receive(READY);
    });
    // A fresh call's ready re-sends nothing: nobody muted it yet.
    expect(first.sent.filter((frame) => (frame as { type: string }).type === "mute")).toEqual([]);
    act(() => result.current.setMuted(true));
    act(() => first.drop());
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    const second = FakeSocket.last();
    act(() => {
      second.open();
      second.receive({ ...READY, call_id: "c2" });
    });
    expect(second.sent.at(-1)).toEqual({ type: "mute", muted: true });
    expect(result.current.call.muted).toBe(true);
    expect(micTrack.enabled).toBe(false);
  });

  it.each(["connectionState", "iceConnectionState"] as const)(
    "ends a call whose audio cannot get through (%s failed), closing everything",
    async (field) => {
      const { result } = renderHook(() => useVoiceSession(), { wrapper });
      await act(() =>
        result.current.start({
          kind: "console",
          agentId: "a1",
          conversationId: null,
          transport: "webrtc",
        }),
      );
      const socket = FakeSocket.last();
      const pc = FakePc.last();
      act(() => {
        socket.open();
        socket.receive(READY);
      });
      // A state that is not a failure changes nothing.
      pc[field] = "disconnected";
      act(() => pc.onconnectionstatechange?.());
      expect(result.current.call.phase).toBe("live");

      pc[field] = "failed";
      act(() =>
        field === "connectionState"
          ? pc.onconnectionstatechange?.()
          : pc.oniceconnectionstatechange?.(),
      );
      expect(viewState(result.current.call)).toBe("connfailed");
      expect(result.current.call.startedAt).not.toBeNull();
      expect(socket.close).toHaveBeenCalled();
      expect(pc.close).toHaveBeenCalled();
      expect(micTrack.stop).toHaveBeenCalled();
      // Nothing the socket says afterwards brings the call back.
      act(() => socket.receive({ type: "state", state: "listening" }));
      expect(result.current.call.phase).toBe("ended");
    },
  );

  it("ignores a failure reported by a peer connection the call has already let go", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const pc = FakePc.last();
    act(() => FakeSocket.last().open());
    act(() => result.current.end());
    pc.connectionState = "failed";
    act(() => pc.onconnectionstatechange?.());
    expect(result.current.call.failure).toBeNull();
  });

  it("keeps trying the resumed socket until the window closes, then says the call dropped", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().drop();
    });
    // Each resumed socket fails before it is set up, as one does while offline.
    for (let tries = 0; tries < 3; tries++) {
      await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
      expect(FakeSocket.last().protocols).toEqual(["access_token.jwt", "voice"]);
      // Every try resumes with the token of the connection that dropped.
      act(() => FakeSocket.last().open());
      expect(FakeSocket.last().sent[0]).toMatchObject({ resume_of: "c1", resume_token: "tok1" });
      act(() => FakeSocket.last().drop());
      expect(viewState(result.current.call)).toBe("reconnecting");
    }
    await act(() => vi.advanceTimersByTimeAsync(RESUME_WINDOW_MS));
    act(() => FakeSocket.last().drop());
    expect(viewState(result.current.call)).toBe("dropped");
    const tried = FakeSocket.instances.length;
    await act(() => vi.advanceTimersByTimeAsync(RESUME_WINDOW_MS));
    expect(FakeSocket.instances).toHaveLength(tried);
  });

  it("tries again at once when the browser is back online", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().drop();
    });
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });
    expect(FakeSocket.instances).toHaveLength(2);
    // The timer it replaced does not open a third.
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    expect(FakeSocket.instances).toHaveLength(2);
    expect(viewState(result.current.call)).toBe("reconnecting");
  });

  it("gives up when the retry cannot even build its offer", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().drop();
    });
    offerSdp = "v=0\r\nm=application 9 x\r\n";
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    expect(FakeSocket.instances).toHaveLength(1);
    expect(viewState(result.current.call)).toBe("dropped");
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("does not retry a call the server ended", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => {
      socket.open();
      socket.receive(READY);
      socket.receive({ type: "ended", reason: "time_limit" });
      socket.drop();
    });
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(viewState(result.current.call)).toBe("limitend");
  });

  it("ignores the close of a socket it has already let go", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => result.current.end());
    act(() => socket.drop());
    expect(FakeSocket.instances).toHaveLength(1);
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("ends a call the person hung up on while the browser was still asking for the microphone", async () => {
    let grant: (stream: MediaStream) => void = () => undefined;
    stubMic(() => new Promise((resolve) => (grant = resolve)));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    let starting: Promise<void> = Promise.resolve();
    act(() => {
      starting = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    act(() => result.current.end());
    await act(async () => {
      grant(micStream);
      await starting;
    });
    expect(micTrack.stop).toHaveBeenCalled();
    expect(FakeSocket.instances).toHaveLength(0);
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("opens no socket for a call ended while its offer was being made", async () => {
    let offered: (offer: { type: string; sdp: string }) => void = () => undefined;
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    const pending = new Promise<{ type: string; sdp: string }>((resolve) => (offered = resolve));
    vi.stubGlobal(
      "RTCPeerConnection",
      class extends FakePc {
        override createOffer = vi.fn(() => pending);
      },
    );
    let starting: Promise<void> = Promise.resolve();
    await act(async () => {
      starting = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
      await Promise.resolve();
    });
    act(() => result.current.end());
    await act(async () => {
      offered({ type: "offer", sdp: offerSdp });
      await starting;
    });
    expect(FakeSocket.instances).toHaveLength(0);
    expect(FakePc.last().close).toHaveBeenCalled();
  });

  it("hangs up a live call by asking the server to end it", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
    });
    act(() => result.current.end());
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "end" });
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
    expect(viewState(result.current.call)).toBe("ended");
    act(() => {
      FakeSocket.last().receive({ type: "ended", reason: "user" });
      FakeSocket.last().drop();
    });
    expect(viewState(result.current.call)).toBe("ended");
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("closes its own socket after End when the server never does", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
    });

    act(() => result.current.end());
    expect(FakeSocket.last().close).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(5000));

    expect(FakeSocket.last().close).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("ends a call still connecting without letting it start", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => result.current.end());
    expect(socket.close).toHaveBeenCalled();
    expect(socket.sent).toEqual([]);
    expect(viewState(result.current.call)).toBe("ended");
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("cancels the pending retry when the call is ended while reconnecting", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().drop();
    });
    act(() => result.current.end());
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    expect(FakeSocket.instances).toHaveLength(1);
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("starts every call unmuted", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    act(() => result.current.setMuted(true));
    act(() => result.current.end());

    micTrack = { enabled: true, stop: vi.fn(), kind: "audio" };
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    expect(micTrack.enabled).toBe(true);
    expect(result.current.call.muted).toBe(false);
  });

  it("lets nothing of a call ended during the microphone prompt outlive the next one's start", async () => {
    const grants: ((stream: MediaStream) => void)[] = [];
    stubMic(() => new Promise((resolve) => grants.push(resolve)));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    let first: Promise<void> = Promise.resolve();
    let second: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    act(() => result.current.end());
    act(() => {
      second = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    const firstTrack = { enabled: true, stop: vi.fn(), kind: "audio" };
    const firstStream = {
      getAudioTracks: () => [firstTrack],
      getTracks: () => [firstTrack],
    } as unknown as MediaStream;
    await act(async () => {
      grants[0]!(firstStream);
      await first;
    });
    expect(firstTrack.stop).toHaveBeenCalled();
    expect(FakePc.instances).toHaveLength(0);
    expect(FakeSocket.instances).toHaveLength(0);

    await act(async () => {
      grants[1]!(micStream);
      await second;
    });
    expect(FakePc.instances).toHaveLength(1);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(result.current.call.phase).toBe("connecting");
  });

  it("ignores a microphone refusal that arrives after the call was replaced", async () => {
    const refusals: ((error: Error) => void)[] = [];
    stubMic(() => new Promise((_, reject) => refusals.push(reject)));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    act(() => {
      void result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    await act(async () => {
      refusals[0]!(Object.assign(new Error("no"), { name: "NotAllowedError" }));
      await first;
    });
    expect(result.current.call.failure).toBeNull();
    expect(result.current.call.phase).toBe("connecting");
  });

  it("ends a live call before starting another", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const first = FakeSocket.last();
    act(() => first.open());
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a2",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(first.sent.at(-1)).toEqual({ type: "end" });
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("lets nothing but the end through once the call was hung up", async () => {
    const onConversation = vi.fn();
    const onTurnSaved = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onConversation, onTurnSaved }), {
      wrapper,
    });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());
    act(() => result.current.end());
    act(() => {
      socket.receive({ type: "answer", sdp: "late" });
      socket.receive(READY);
      socket.receive({ type: "state", state: "agent_speaking" });
    });
    expect(FakePc.last().setRemoteDescription).not.toHaveBeenCalled();
    expect(onConversation).not.toHaveBeenCalled();
    expect(viewState(result.current.call)).toBe("ended");
    act(() => {
      socket.receive({
        type: "turn_saved",
        message: { id: "m", role: "user", content: "bye", interrupted: false, turn_id: "t" },
      });
      socket.receive({ type: "ended", reason: "user" });
    });
    // With the message, so a page that keeps no transcript of its own can draw it.
    expect(onTurnSaved).toHaveBeenCalledWith({
      id: "m",
      role: "user",
      content: "bye",
      interrupted: false,
      turn_id: "t",
    });
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("ignores frames from a socket a newer call replaced", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const old = FakeSocket.last();
    act(() => old.open());
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a2",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => old.receive({ type: "ended", reason: "time_limit" }));
    expect(result.current.call.phase).toBe("connecting");
  });

  it("gives up a call whose answer the browser cannot apply", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());
    FakePc.last().setRemoteDescription.mockRejectedValueOnce(new Error("bad sdp"));
    await act(async () => {
      socket.receive({ type: "answer", sdp: "garbled" });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(socket.close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("does not give up a call already ended when a late answer fails to apply", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());
    let reject: (error: Error) => void = () => undefined;
    FakePc.last().setRemoteDescription.mockReturnValueOnce(
      new Promise((_, fail) => (reject = fail)),
    );
    act(() => socket.receive({ type: "answer", sdp: "slow" }));
    act(() => result.current.end());
    await act(async () => {
      reject(new Error("closed"));
      await Promise.resolve();
    });
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("forgets an ended call on dismiss, but never a live one", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    act(() => result.current.dismiss());
    expect(result.current.call.phase).toBe("connecting");
    act(() => result.current.end());
    expect(result.current.call.phase).toBe("ended");
    act(() => result.current.dismiss());
    expect(result.current.call.phase).toBe("idle");
  });

  it("lets go of the peer connection and the microphone as soon as the server ends the call", async () => {
    const onTurnSaved = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onTurnSaved }), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => {
      socket.open();
      socket.receive(READY);
      socket.receive({ type: "ended", reason: "time_limit" });
    });
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
    expect(result.current.localStream).toBeNull();
    // The socket stays open for the turns saved on the way out.
    expect(socket.close).not.toHaveBeenCalled();
    act(() =>
      socket.receive({
        type: "turn_saved",
        message: { id: "m", role: "assistant", content: "Bye.", interrupted: false, turn_id: "t" },
      }),
    );
    expect(onTurnSaved).toHaveBeenCalledOnce();
  });

  it("does nothing on end when no call is in progress", () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    act(() => result.current.end());
    expect(result.current.call.phase).toBe("idle");
  });

  it("closes the peer connection and stops the microphone on pagehide", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    act(() => window.dispatchEvent(new Event("pagehide")));
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "end" });
  });

  it("ends the call when the page that holds it goes away", async () => {
    const { result, unmount } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    unmount();
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "end" });
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("holds the microphone closed in push-to-talk until the button is held", async () => {
    useVoiceCallStore.setState({ pushToTalk: true });
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    expect(micTrack.enabled).toBe(false);
    const before = FakeSocket.last().sent.length;
    act(() => result.current.pressToTalk(true));
    expect(micTrack.enabled).toBe(true);
    act(() => result.current.pressToTalk(false));
    expect(micTrack.enabled).toBe(false);
    // The browser alone gates the microphone; the server has nothing to hear.
    expect(FakeSocket.last().sent.slice(before)).toEqual([]);
    // Switching back to hands-free opens it again.
    act(() => useVoiceCallStore.setState({ pushToTalk: false }));
    expect(micTrack.enabled).toBe(true);
  });

  it("mutes the microphone and tells the server", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    act(() => result.current.setMuted(true));
    expect(micTrack.enabled).toBe(false);
    expect(result.current.call.muted).toBe(true);
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "mute", muted: true });
  });

  it("sends nothing and touches no track before a call starts", () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    act(() => result.current.setMuted(true));
    act(() => result.current.decide("a9", true));
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("sends a decision for the approval on screen", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    act(() => result.current.decide("a9", true));
    expect(FakeSocket.last().sent.at(-1)).toEqual({
      type: "approval",
      id: "a9",
      decision: "approve",
    });
    act(() => result.current.decide("a9", false));
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "approval", id: "a9", decision: "deny" });
  });

  it("sends the caller's answers to the agent's questions", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => FakeSocket.last().open());
    const answers = [{ question: "Which report?", answer: "Q3" }] as never;
    act(() => result.current.answer("q1", answers));
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "answers", id: "q1", answers });
  });

  it("dismisses an approval the caller cannot give", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().receive({ type: "approval_unavailable", tool: "send_invoice", args: {} });
    });
    expect(viewState(result.current.call)).toBe("noapproval");
    act(() => result.current.dismissUnavailable());
    expect(viewState(result.current.call)).toBe("listening");
  });

  it("tells the chat a turn was saved", async () => {
    const onTurnSaved = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onTurnSaved }), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive({
        type: "turn_saved",
        message: { id: "m1", role: "user", content: "hi", interrupted: false, turn_id: "t" },
      });
    });
    expect(onTurnSaved).toHaveBeenCalledOnce();
  });

  it("opens a console socket without a token protocol when there is no token", async () => {
    useAuthStore.setState({ accessToken: null, user: null });
    useOrgStore.setState({ activeOrgId: null });
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(FakeSocket.last().url).toBe("wss://x/api/v1/ws/voice");
    expect(FakeSocket.last().protocols).toBeUndefined();
  });

  it("calls an embed by its public key, naming no agent and no conversation", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "embed",
        publicKey: "pk",
        visitorKey: null,
        token: "t1",
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());
    expect(socket.url).toBe("wss://x/api/v1/embed/pk/voice/ws?token=t1");
    expect(socket.protocols).toBeUndefined();
    expect(socket.sent[0]).toEqual({ type: "start", sdp_offer: offerSdp });
  });

  it("briefs an embed's call with the page's supplied variables, on a resume too", async () => {
    // The `context` a typed message carries, so a call is told what text chat is.
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "embed",
        publicKey: "pk",
        visitorKey: "v1",
        token: null,
        transport: "webrtc",
        context: { order: "123" },
      }),
    );
    const first = FakeSocket.last();
    act(() => first.open());
    expect(first.sent[0]).toEqual({
      type: "start",
      sdp_offer: offerSdp,
      context: { order: "123" },
    });

    act(() => {
      first.receive(READY);
      first.drop();
    });
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    const second = FakeSocket.last();
    act(() => second.open());
    expect(second.sent[0]).toMatchObject({ resume_of: "c1", context: { order: "123" } });
  });
});

describe("useVoiceSession over the relay (Gemini, xAI, Azure; fakes only, not verified live)", () => {
  const RELAY_READY: VoiceServerFrame = {
    ...READY,
    transport: "relay",
    input_sample_rate: 16_000,
    output_sample_rate: 24_000,
  } as VoiceServerFrame;

  async function relayCall() {
    const pcm = await import("@/lib/voice/pcm");
    const hook = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      hook.result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "relay",
      }),
    );
    const socket = FakeSocket.last();
    return { ...hook, socket, pcm };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    relay.onChunk = null;
    relay.onDrained = null;
    relay.played = 4800;
    relay.capture.stop = vi.fn();
    relay.player.enqueue = vi.fn();
    relay.player.clear = vi.fn();
    relay.player.close = vi.fn();
    relay.context = { sampleRate: 48_000 };
  });

  it("opens no peer connection and starts without an offer", async () => {
    const { socket } = await relayCall();
    act(() => socket.open());

    expect(FakePc.instances).toHaveLength(0);
    expect(socket.binaryType).toBe("arraybuffer");
    expect(socket.sent[0]).toEqual({ type: "start", agent_id: "a1", conversation_id: null });
  });

  it("captures and plays at the rates the server names, and sends the microphone as binary", async () => {
    const { result, socket, pcm } = await relayCall();
    act(() => socket.open());
    // Audio before the call is set up has nowhere to go.
    act(() => socket.receiveAudio(new ArrayBuffer(8)));
    act(() => socket.receive(RELAY_READY));

    expect(pcm.createPcmCapture).toHaveBeenCalledWith(
      relay.context,
      micStream,
      16_000,
      expect.any(Function),
    );
    expect(pcm.createPcmPlayer).toHaveBeenCalledWith(relay.context, 24_000, expect.any(Function));
    expect(result.current.remoteStream).toBe(relay.player.stream);

    relay.onChunk!(new ArrayBuffer(4096));
    expect(socket.sent).toContainEqual({ binary: 4096 });

    const agent = new ArrayBuffer(960);
    act(() => socket.receiveAudio(agent));
    expect(relay.player.enqueue).toHaveBeenCalledTimes(1);
    expect(relay.player.enqueue).toHaveBeenCalledWith(agent);
  });

  it("reports what was played on a timer and drops the queue when the server says", async () => {
    vi.useFakeTimers();
    const { socket } = await relayCall();
    act(() => {
      socket.open();
      socket.receive(RELAY_READY);
    });

    await act(() => vi.advanceTimersByTimeAsync(PLAYED_EVERY_MS));
    expect(socket.sent).toContainEqual({ type: "played", bytes: 4800 });
    // A position that did not move is not sent again.
    await act(() => vi.advanceTimersByTimeAsync(PLAYED_EVERY_MS * 3));
    expect(
      socket.sent.filter((frame) => (frame as { type?: string }).type === "played"),
    ).toHaveLength(1);
    // The end of playback is reported at once, not at the next tick.
    relay.played = 9600;
    relay.onDrained!();
    expect(socket.sent).toContainEqual({ type: "played", bytes: 9600 });

    act(() => socket.receive({ type: "clear_playback" }));
    expect(relay.player.clear).toHaveBeenCalled();
  });

  it("sends nothing into a socket that is closing", async () => {
    vi.useFakeTimers();
    const { socket } = await relayCall();
    act(() => {
      socket.open();
      socket.receive(RELAY_READY);
    });
    const before = socket.sent.length;
    socket.readyState = 2;

    relay.onChunk!(new ArrayBuffer(16));
    await act(() => vi.advanceTimersByTimeAsync(PLAYED_EVERY_MS));

    expect(socket.sent).toHaveLength(before);
  });

  it("stops the capture, the player and the reports when the call ends", async () => {
    vi.useFakeTimers();
    const { result, socket } = await relayCall();
    act(() => {
      socket.open();
      socket.receive(RELAY_READY);
    });

    act(() => result.current.end());
    const sent = socket.sent.length;
    await act(() => vi.advanceTimersByTimeAsync(PLAYED_EVERY_MS * 4));

    expect(relay.capture.stop).toHaveBeenCalled();
    expect(relay.player.close).toHaveBeenCalled();
    expect(socket.sent).toHaveLength(sent);
    expect(result.current.remoteStream).toBeNull();
  });

  it("starts fresh audio on the resumed connection after a drop", async () => {
    vi.useFakeTimers();
    const { socket, pcm } = await relayCall();
    act(() => {
      socket.open();
      socket.receive(RELAY_READY);
      socket.drop();
    });
    expect(relay.player.close).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
    const second = FakeSocket.last();
    act(() => {
      second.open();
      second.receive({ ...RELAY_READY, call_id: "c2" } as VoiceServerFrame);
    });
    expect(second.sent[0]).toMatchObject({ type: "start", resume_of: "c1" });
    expect(pcm.createPcmPlayer).toHaveBeenCalledTimes(2);
  });

  it("gives the call up in a browser without Web Audio", async () => {
    relay.context = null;
    const { result, socket } = await relayCall();
    act(() => {
      socket.open();
      socket.receive(RELAY_READY);
    });
    // The call never carried audio: it could not connect, and its socket is closed.
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(socket.close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("gives up when the server sets the call up on another transport", async () => {
    const { result, socket, pcm } = await relayCall();
    act(() => {
      socket.open();
      socket.receive({ ...RELAY_READY, transport: "webrtc" } as VoiceServerFrame);
    });
    expect(pcm.createPcmCapture).not.toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalled();
    expect(viewState(result.current.call)).toBe("connfailed");
  });

  it("creates the audio context in the click that starts the call, not when it is ready", async () => {
    const voiceGlow = await import("voice-glow");
    stubMic(() => new Promise<MediaStream>(() => {}));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    void act(() => {
      void result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "relay",
      });
    });
    expect(voiceGlow.getAudioContext).toHaveBeenCalledTimes(1);
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("does not touch Web Audio for a WebRTC call", async () => {
    const voiceGlow = await import("voice-glow");
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    expect(voiceGlow.getAudioContext).not.toHaveBeenCalled();
  });
});

it.each(["organization", "account"])(
  "invalidates pending microphone access on %s switch",
  async (scope) => {
    let grant: (stream: MediaStream) => void = () => undefined;
    stubMic(
      () =>
        new Promise((resolve) => {
          grant = resolve;
        }),
    );
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    let starting: Promise<void> = Promise.resolve();
    act(() => {
      starting = result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      });
    });
    act(() => {
      if (scope === "organization") useOrgStore.setState({ activeOrgId: "org2" });
      else useAuthStore.setState({ user: null, accessToken: null });
    });
    await act(async () => {
      grant(micStream);
      await starting;
    });
    expect(FakeSocket.instances).toHaveLength(0);
    expect(micTrack.stop).toHaveBeenCalledOnce();
    expect(result.current.call.phase).toBe("idle");
  },
);

it.each(["connecting", "live", "reconnecting"])(
  "closes %s calls on tenant switch and ignores old callbacks",
  async (phase) => {
    vi.useFakeTimers();
    const onConversation = vi.fn(),
      onTurnSaved = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onConversation, onTurnSaved }), {
      wrapper,
    });
    await act(() =>
      result.current.start({
        kind: "console",
        agentId: "a1",
        conversationId: null,
        transport: "webrtc",
      }),
    );
    const socket = FakeSocket.last(),
      peer = FakePc.last();
    if (phase !== "connecting")
      act(() => {
        socket.open();
        socket.receive(READY);
      });
    if (phase === "reconnecting") act(() => socket.drop());
    onConversation.mockClear();
    act(() => useOrgStore.setState({ activeOrgId: "org2" }));
    act(() => {
      socket.open();
      socket.receive(READY);
      socket.receive({
        type: "turn_saved",
        message: { id: "old", role: "user", content: "old", interrupted: false, turn_id: "t" },
      });
      peer.ontrack?.({ streams: [micStream] });
    });
    await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS + RESUME_WINDOW_MS));
    expect(FakeSocket.instances).toHaveLength(1);
    expect(socket.close).toHaveBeenCalled();
    expect(peer.close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
    expect(onConversation).not.toHaveBeenCalled();
    expect(onTurnSaved).not.toHaveBeenCalled();
    expect(result.current.remoteStream).toBeNull();
    expect(result.current.call.phase).toBe("idle");
  },
);

it("keeps public embed ownership separate from console account and tenant changes", async () => {
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  await act(() =>
    result.current.start({
      kind: "embed",
      publicKey: "public",
      visitorKey: "visitor",
      token: null,
      transport: "webrtc",
    }),
  );
  const socket = FakeSocket.last();
  act(() => {
    useOrgStore.setState({ activeOrgId: "org2" });
    useAuthStore.setState({ user: null });
  });
  expect(socket.close).not.toHaveBeenCalled();
  expect(micTrack.stop).not.toHaveBeenCalled();
  expect(result.current.call.phase).toBe("connecting");
});

it("uses the current tenant even when start runs before a React rerender", async () => {
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  let starting: Promise<void> = Promise.resolve();
  act(() => {
    useOrgStore.setState({ activeOrgId: "org2" });
    starting = result.current.start({
      kind: "console",
      agentId: "a1",
      conversationId: null,
      transport: "webrtc",
    });
  });
  await act(() => starting);
  expect(FakeSocket.last().url).toContain("organization_id=org2");
});

it("ignores an old setup failure after a different tenant started a call", async () => {
  let fail: (error: Error) => void = () => undefined;
  const pending = new Promise<{ type: string; sdp: string }>((_resolve, reject) => {
    fail = reject;
  });
  vi.stubGlobal(
    "RTCPeerConnection",
    class extends FakePc {
      override createOffer = vi.fn(() => pending);
    },
  );
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  let starting: Promise<void> = Promise.resolve();
  await act(async () => {
    starting = result.current.start({
      kind: "console",
      agentId: "a1",
      conversationId: null,
      transport: "webrtc",
    });
    await Promise.resolve();
  });
  act(() => useOrgStore.setState({ activeOrgId: "org2" }));
  await act(() =>
    result.current.start({
      kind: "console",
      agentId: "a2",
      conversationId: null,
      transport: "relay",
    }),
  );
  const active = FakeSocket.last();
  await act(async () => {
    fail(new Error("old setup failed"));
    await starting;
  });
  expect(active.close).not.toHaveBeenCalled();
  expect(result.current.call.phase).toBe("connecting");
});

it("ignores a reconnect callback retained from an invalidated tenant", async () => {
  vi.useFakeTimers();
  const listen = vi.spyOn(window, "addEventListener");
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  await act(() =>
    result.current.start({
      kind: "console",
      agentId: "a1",
      conversationId: null,
      transport: "webrtc",
    }),
  );
  act(() => {
    FakeSocket.last().open();
    FakeSocket.last().receive(READY);
    FakeSocket.last().drop();
  });
  const online = listen.mock.calls.find(([event]) => event === "online")?.[1];
  if (typeof online !== "function") throw new Error("No reconnect callback registered");
  act(() => useOrgStore.setState({ activeOrgId: "org2" }));
  await act(async () => {
    online(new Event("online"));
    await Promise.resolve();
  });
  expect(FakeSocket.instances).toHaveLength(1);
  expect(result.current.call.phase).toBe("idle");
  listen.mockRestore();
});

it("a stale reconnect failure cannot end another tenant's new call", async () => {
  vi.useFakeTimers();
  let fail: (error: Error) => void = () => undefined;
  const pending = new Promise<{ type: string; sdp: string }>((_resolve, reject) => {
    fail = reject;
  });
  let offers = 0;
  vi.stubGlobal(
    "RTCPeerConnection",
    class extends FakePc {
      override createOffer = vi.fn(() =>
        ++offers === 1 ? Promise.resolve({ type: "offer", sdp: offerSdp }) : pending,
      );
    },
  );
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  await act(() =>
    result.current.start({
      kind: "console",
      agentId: "a1",
      conversationId: null,
      transport: "webrtc",
    }),
  );
  act(() => {
    FakeSocket.last().open();
    FakeSocket.last().receive(READY);
    FakeSocket.last().drop();
  });
  await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
  act(() => useOrgStore.setState({ activeOrgId: "org2" }));
  await act(() =>
    result.current.start({
      kind: "console",
      agentId: "a2",
      conversationId: null,
      transport: "relay",
    }),
  );
  const active = FakeSocket.last();
  await act(async () => {
    fail(new Error("old reconnect failed"));
    await Promise.resolve();
  });
  expect(active.close).not.toHaveBeenCalled();
  expect(result.current.call.phase).toBe("connecting");
});

it("the old end timer closes only its own socket after a new call starts", async () => {
  vi.useFakeTimers();
  const { result } = renderHook(() => useVoiceSession(), { wrapper });
  const target = {
    kind: "console",
    agentId: "a1",
    conversationId: null,
    transport: "webrtc",
  } as const;
  await act(() => result.current.start(target));
  const old = FakeSocket.last();
  act(() => {
    old.open();
    result.current.end();
  });
  await act(() => result.current.start(target));
  const active = FakeSocket.last();
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(old.close).toHaveBeenCalled();
  expect(active.close).not.toHaveBeenCalled();
  expect(result.current.call.phase).toBe("connecting");
});
