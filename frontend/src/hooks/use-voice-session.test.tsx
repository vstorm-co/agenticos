import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { viewState } from "@/lib/voice/call-reducer";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";
import { useAuthStore, useOrgStore, useVoiceCallStore } from "@/stores";
import type { VoiceServerFrame } from "@/types/voice";

import { RECONNECT_DELAY_MS, RESUME_WINDOW_MS, useVoiceSession } from "./use-voice-session";

/** A fake socket: what the hook must get right is which frames it sends, and when. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static last = () => FakeSocket.instances[FakeSocket.instances.length - 1]!;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
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

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(frame: VoiceServerFrame) {
    this.onmessage?.({ data: JSON.stringify(frame) });
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
  minutes_left: 540,
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
  useAuthStore.setState({ accessToken: "jwt" });
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
      result.current.start({ kind: "console", agentId: "a1", conversationId: "conv0" }),
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
      result.current.start({ kind: "console", agentId: "a1", conversationId: "conv1" }),
    );
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
    });
    expect(onConversation).not.toHaveBeenCalled();
  });

  it("plays what the agent says through the remote stream", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    expect(result.current.call.failure).toBe(failure);
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("treats a thrown non-error as a busy microphone", async () => {
    stubMic(() => Promise.reject("nope"));
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    expect(result.current.call.failure).toBe("mic_busy");
  });

  it("says the page cannot ask for a microphone where the browser offers none", async () => {
    vi.stubGlobal("navigator", {});
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    expect(result.current.call.failure).toBe("mic_insecure");
    expect(viewState(result.current.call)).toBe("micblocked");
  });

  it("refuses an offer carrying a data channel before any socket opens", async () => {
    offerSdp = "v=0\r\nm=audio 9 x\r\nm=application 9 x\r\n";
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    expect(FakeSocket.instances).toHaveLength(0);
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("says the call could not connect when the socket closes before it is ready", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => FakeSocket.last().drop());
    expect(viewState(result.current.call)).toBe("connfailed");
    expect(FakeSocket.instances).toHaveLength(1);
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("retries once, resuming the call, when a live socket drops", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    expect(second.sent[0]).toMatchObject({
      type: "start",
      resume_of: "c1",
      conversation_id: "conv1",
    });
    act(() => second.receive({ ...READY, call_id: "c2" }));
    expect(result.current.call.phase).toBe("live");

    // One logical retry: a resumed call that drops again is over.
    act(() => second.drop());
    expect(result.current.call.phase).toBe("ended");
    expect(viewState(result.current.call)).toBe("dropped");
    expect(micTrack.stop).toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(RESUME_WINDOW_MS));
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("keeps trying the resumed socket until the window closes, then says the call dropped", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => {
      FakeSocket.last().open();
      FakeSocket.last().receive(READY);
      FakeSocket.last().drop();
    });
    // Each resumed socket fails before it is set up, as one does while offline.
    for (let tries = 0; tries < 3; tries++) {
      await act(() => vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS));
      expect(FakeSocket.last().protocols).toEqual(["access_token.jwt", "voice"]);
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
      starting = result.current.start({ kind: "console", agentId: "a1", conversationId: null });
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
      starting = result.current.start({ kind: "console", agentId: "a1", conversationId: null });
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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

  it("ends a call still connecting without letting it start", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => FakeSocket.last().open());
    act(() => result.current.setMuted(true));
    act(() => result.current.end());

    micTrack = { enabled: true, stop: vi.fn(), kind: "audio" };
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
      first = result.current.start({ kind: "console", agentId: "a1", conversationId: null });
    });
    act(() => result.current.end());
    act(() => {
      second = result.current.start({ kind: "console", agentId: "a1", conversationId: null });
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
      first = result.current.start({ kind: "console", agentId: "a1", conversationId: null });
    });
    act(() => {
      void result.current.start({ kind: "console", agentId: "a1", conversationId: null });
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    const first = FakeSocket.last();
    act(() => first.open());
    await act(() => result.current.start({ kind: "console", agentId: "a2", conversationId: null }));
    expect(first.sent.at(-1)).toEqual({ type: "end" });
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("lets nothing but the end through once the call was hung up", async () => {
    const onConversation = vi.fn();
    const onTurnSaved = vi.fn();
    const { result } = renderHook(() => useVoiceSession({ onConversation, onTurnSaved }), {
      wrapper,
    });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    expect(onTurnSaved).toHaveBeenCalledOnce();
    expect(viewState(result.current.call)).toBe("ended");
  });

  it("ignores frames from a socket a newer call replaced", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    const old = FakeSocket.last();
    act(() => old.open());
    await act(() => result.current.start({ kind: "console", agentId: "a2", conversationId: null }));
    act(() => old.receive({ type: "ended", reason: "time_limit" }));
    expect(result.current.call.phase).toBe("connecting");
  });

  it("gives up a call whose answer the browser cannot apply", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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

  it("does nothing on end when no call is in progress", () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    act(() => result.current.end());
    expect(result.current.call.phase).toBe("idle");
  });

  it("closes the peer connection and stops the microphone on pagehide", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => FakeSocket.last().open());
    act(() => window.dispatchEvent(new Event("pagehide")));
    expect(FakePc.last().close).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "end" });
  });

  it("ends the call when the page that holds it goes away", async () => {
    const { result, unmount } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => FakeSocket.last().open());
    unmount();
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "end" });
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("holds the microphone closed in push-to-talk until the button is held", async () => {
    useVoiceCallStore.setState({ pushToTalk: true });
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    act(() => FakeSocket.last().open());
    expect(micTrack.enabled).toBe(false);
    act(() => result.current.pressToTalk(true));
    expect(micTrack.enabled).toBe(true);
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "ptt", state: "down" });
    act(() => result.current.pressToTalk(false));
    expect(micTrack.enabled).toBe(false);
    expect(FakeSocket.last().sent.at(-1)).toEqual({ type: "ptt", state: "up" });
    // Switching back to hands-free opens it again.
    act(() => useVoiceCallStore.setState({ pushToTalk: false }));
    expect(micTrack.enabled).toBe(true);
  });

  it("mutes the microphone and tells the server", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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

  it("dismisses an approval the caller cannot give", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
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
    useAuthStore.setState({ accessToken: null });
    useOrgStore.setState({ activeOrgId: null });
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() => result.current.start({ kind: "console", agentId: "a1", conversationId: null }));
    expect(FakeSocket.last().url).toBe("wss://x/api/v1/ws/voice");
    expect(FakeSocket.last().protocols).toBeUndefined();
  });

  it("calls an embed by its public key, naming no agent and no conversation", async () => {
    const { result } = renderHook(() => useVoiceSession(), { wrapper });
    await act(() =>
      result.current.start({ kind: "embed", publicKey: "pk", visitorKey: null, token: "t1" }),
    );
    const socket = FakeSocket.last();
    act(() => socket.open());
    expect(socket.url).toBe("wss://x/api/v1/embed/pk/voice/ws?token=t1");
    expect(socket.protocols).toBeUndefined();
    expect(socket.sent[0]).toEqual({ type: "start", sdp_offer: offerSdp });
  });
});
