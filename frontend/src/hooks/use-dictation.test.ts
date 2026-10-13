import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UseMicrophoneResult } from "voice-glow";

import { ApiError } from "@/lib/api-error";

import { useDictation, type UseDictationOptions } from "./use-dictation";

/** A Web Audio node: what it was connected to, and whether it was taken down. */
interface FakeNode {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
}

const audio = vi.hoisted(() => ({
  /** What the fake analyser reads: every sample at this amplitude. */
  level: 0,
  /** Whether the page has an AudioContext to measure with. */
  available: true,
  /** Every node the meter and the WAV recorder made, to check they were taken down. */
  nodes: [] as FakeNode[],
  /** The WAV recorder's sample processors, each an event target it listens on. */
  processors: [] as (EventTarget & FakeNode & { args: number[] })[],
  /** The WAV recorder's muting gain nodes. */
  gains: [] as (FakeNode & { gain: { value: number } })[],
  destination: { name: "speakers" },
}));

vi.mock("voice-glow", () => ({
  getAudioContext: () =>
    audio.available
      ? {
          sampleRate: 48_000,
          destination: audio.destination,
          createMediaStreamSource: () => {
            const source = { connect: vi.fn(), disconnect: vi.fn() };
            audio.nodes.push(source);
            return source;
          },
          createScriptProcessor: (...args: number[]) => {
            const processor = Object.assign(new EventTarget(), {
              args,
              connect: vi.fn(),
              disconnect: vi.fn(),
            });
            audio.processors.push(processor);
            audio.nodes.push(processor);
            return processor;
          },
          createGain: () => {
            const gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
            audio.gains.push(gain);
            audio.nodes.push(gain);
            return gain;
          },
          createAnalyser: () => {
            const analyser = {
              fftSize: 0,
              getFloatTimeDomainData: (samples: Float32Array) => samples.fill(audio.level),
              connect: vi.fn(),
              disconnect: vi.fn(),
            };
            audio.nodes.push(analyser);
            return analyser;
          },
        }
      : null,
}));

const api = vi.hoisted(() => ({
  dictate: vi.fn<(agentId: string, recording: Blob, signal: AbortSignal) => Promise<string>>(),
}));
vi.mock("@/lib/dictation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/dictation-api")>()),
  dictate: (agentId: string, recording: Blob, signal: AbortSignal) =>
    api.dictate(agentId, recording, signal),
}));

/** A `MediaRecorder` whose stop hands over one chunk and then says it stopped. */
class FakeRecorder extends EventTarget {
  static supported = new Set(["audio/webm;codecs=opus"]);
  static instances: FakeRecorder[] = [];
  static isTypeSupported(type: string): boolean {
    return FakeRecorder.supported.has(type);
  }

  state: RecordingState = "inactive";
  timeslice: number | undefined;

  constructor(
    readonly stream: MediaStream,
    readonly options: MediaRecorderOptions,
  ) {
    super();
    FakeRecorder.instances.push(this);
  }

  get mimeType(): string {
    return this.options.mimeType ?? "";
  }

  start(timeslice?: number): void {
    this.timeslice = timeslice;
    this.state = "recording";
  }

  /** Whether `stop` is announced a task later, as a browser does, rather than at once. */
  static deferStop = false;
  stopCalls = 0;

  stop(): void {
    this.stopCalls += 1;
    if (this.state === "inactive") throw new Error("stop() on an inactive recorder");
    this.state = "inactive";
    const chunk = new Blob(["audio"], { type: this.mimeType });
    this.dispatchEvent(Object.assign(new Event("dataavailable"), { data: chunk }));
    if (FakeRecorder.deferStop) setTimeout(() => this.dispatchEvent(new Event("stop")), 0);
    else this.dispatchEvent(new Event("stop"));
  }
}

const track = new EventTarget();
const stream = { active: true, getAudioTracks: () => [track] } as unknown as MediaStream;

function fakeMic(overrides: Partial<UseMicrophoneResult> = {}): UseMicrophoneResult {
  return {
    stream: null,
    state: "idle",
    error: null,
    supported: true,
    start: vi.fn(async () => stream),
    stop: vi.fn(),
    ...overrides,
  };
}

function setup(options: Partial<UseDictationOptions> = {}) {
  const mic = options.mic ?? fakeMic();
  const view = renderHook((props: UseDictationOptions) => useDictation(props), {
    initialProps: { mic, agentId: "a1", maxSeconds: 300, provider: null, ...options },
  });
  return { ...view, mic };
}

/** Let time pass, with every timer, frame and promise that falls due. */
async function wait(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Press the mic and let the stream open. */
async function record(view: ReturnType<typeof setup>): Promise<void> {
  await act(async () => {
    await view.result.current.actions.start();
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function refusal(status: number, details: Record<string, unknown> | null = null): ApiError {
  return new ApiError(status, "refused", {
    error: { code: "REFUSED", message: "refused", details },
  });
}

function lastRecorder(): FakeRecorder {
  return FakeRecorder.instances.at(-1)!;
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
      "requestAnimationFrame",
      "cancelAnimationFrame",
    ],
  });
  audio.level = 0;
  audio.available = true;
  audio.nodes = [];
  audio.processors = [];
  audio.gains = [];
  FakeRecorder.supported = new Set(["audio/webm;codecs=opus"]);
  FakeRecorder.instances = [];
  FakeRecorder.deferStop = false;
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  api.dictate.mockReset();
  api.dictate.mockResolvedValue("hello");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useDictation", () => {
  it("asks for the microphone first, and counts only once it is live", async () => {
    const opened = deferred<MediaStream | null>();
    const view = setup({ mic: fakeMic({ start: vi.fn(() => opened.promise) }) });

    let started!: Promise<void>;
    act(() => {
      started = view.result.current.actions.start();
    });
    expect(view.result.current.state.phase).toBe("requesting");
    await wait(3000);
    expect(view.result.current.state.elapsed).toBe(0);

    await act(async () => {
      opened.resolve(stream);
      await started;
    });
    expect(view.result.current.state.phase).toBe("recording");
    await wait(2000);
    expect(view.result.current.state.elapsed).toBe(2);
  });

  it.each([
    [["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"], "audio/webm;codecs=opus"],
    [["audio/ogg;codecs=opus", "audio/mp4"], "audio/ogg;codecs=opus"],
    [["audio/mp4"], "audio/mp4"],
  ])("records the first type the browser supports, of %j: %s", async (supported, expected) => {
    FakeRecorder.supported = new Set(supported);
    const view = setup();

    await record(view);

    expect(lastRecorder().options).toEqual({ mimeType: expected, audioBitsPerSecond: 128_000 });
    expect(lastRecorder().timeslice).toBe(250);
    expect(lastRecorder().stream).toBe(stream);
  });

  it("stops, transcribes once through the agent, and hands the text over", async () => {
    const answered = deferred<string>();
    api.dictate.mockReturnValue(answered.promise);
    const view = setup();
    await record(view);
    await wait(2000);

    act(() => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("transcribing");
    expect(view.mic.stop).toHaveBeenCalled();
    expect(api.dictate).toHaveBeenCalledOnce();
    const [agentId, recording] = api.dictate.mock.calls[0]!;
    expect(agentId).toBe("a1");
    expect(recording.type).toBe("audio/webm;codecs=opus");
    expect(recording.size).toBeGreaterThan(0);

    await act(async () => answered.resolve("hello"));
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
    expect(view.result.current.state.phase).toBe("idle");
  });

  it("sends through the agent chosen when the mic was pressed, not a later one", async () => {
    const view = setup();
    await record(view);
    view.rerender({ mic: view.mic, agentId: "a2", maxSeconds: 300, provider: null });
    await wait(1500);

    await act(async () => view.result.current.actions.stop());

    expect(api.dictate.mock.calls[0]![0]).toBe("a1");
  });

  it("gives each transcript a new id", async () => {
    const view = setup();
    for (const text of ["one", "two"]) {
      api.dictate.mockResolvedValueOnce(text);
      await record(view);
      await wait(1500);
      await act(async () => view.result.current.actions.stop());
    }
    expect(view.result.current.state.transcript).toEqual({ id: 2, text: "two" });
  });

  it("cancelling while transcribing aborts the request and ends idle, not failed", async () => {
    let signal!: AbortSignal;
    api.dictate.mockImplementation(
      (_agent, _blob, given) =>
        new Promise((_resolve, reject) => {
          signal = given;
          given.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const view = setup();
    await record(view);
    await wait(1500);
    act(() => view.result.current.actions.stop());
    vi.mocked(view.mic.stop).mockClear();

    await act(async () => view.result.current.actions.cancel());

    expect(signal.aborted).toBe(true);
    expect(view.result.current.state.phase).toBe("idle");
    expect(view.result.current.state.reason).toBeNull();
    expect(view.result.current.state.transcript).toBeNull();
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it("cancelling while recording discards what was said and closes the microphone", async () => {
    const view = setup();
    await record(view);
    await wait(3000);

    await act(async () => view.result.current.actions.cancel());

    expect(lastRecorder().state).toBe("inactive");
    expect(api.dictate).not.toHaveBeenCalled();
    expect(view.mic.stop).toHaveBeenCalled();
    expect(view.result.current.state.phase).toBe("idle");
  });

  it("a recording under a second is too short, and nothing is uploaded", async () => {
    const view = setup();
    await record(view);
    await wait(500);

    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("too_short");
    expect(api.dictate).not.toHaveBeenCalled();
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it("stops by itself at the limit and transcribes everything up to it", async () => {
    const view = setup({ maxSeconds: 10 });
    await record(view);

    await wait(10_000);

    expect(lastRecorder().state).toBe("inactive");
    expect(api.dictate).toHaveBeenCalledOnce();
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it("transcribes, rather than discards, when the microphone goes away mid-sentence", async () => {
    const view = setup();
    await record(view);
    await wait(4000);

    await act(async () => {
      track.dispatchEvent(new Event("ended"));
    });

    expect(api.dictate).toHaveBeenCalledOnce();
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
  });

  it("counts down only in the last thirty seconds", async () => {
    const view = setup({ maxSeconds: 40 });
    await record(view);

    await wait(9000);
    expect(view.result.current.state.remaining).toBeNull();
    await wait(1000);
    expect(view.result.current.state.remaining).toBe(30);
    await wait(5000);
    expect(view.result.current.state.remaining).toBe(25);
  });

  it("says the room is silent after five quiet seconds, and stops saying it on one sound", async () => {
    const view = setup();
    await record(view);

    await wait(4900);
    expect(view.result.current.state.silent).toBe(false);
    await wait(200);
    expect(view.result.current.state.silent).toBe(true);
    expect(view.result.current.state.level).toBe(0);

    audio.level = 0.2;
    await wait(100);
    expect(view.result.current.state.silent).toBe(false);
    expect(view.result.current.state.level).toBeGreaterThan(0.3);
  });

  it("records without a level where the page cannot analyse audio", async () => {
    audio.available = false;
    audio.level = 0.5;
    const view = setup();
    await record(view);
    await wait(6000);

    expect(view.result.current.state.phase).toBe("recording");
    expect(view.result.current.state.level).toBe(0);
    expect(view.result.current.state.silent).toBe(false);
  });

  it("keeps the recording after a provider error, sends the same one again, and drops it on dismiss", async () => {
    api.dictate.mockRejectedValueOnce(refusal(503, { reason: "provider_error" }));
    const view = setup();
    await record(view);
    await wait(1500);
    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("failed");
    expect(view.result.current.state.reason).toBe("provider_error");
    expect(view.result.current.state.canRetry).toBe(true);

    api.dictate.mockRejectedValueOnce(refusal(503, { reason: "timeout" }));
    await act(async () => view.result.current.actions.retry());
    expect(api.dictate).toHaveBeenCalledTimes(2);
    expect(api.dictate.mock.calls[1]![1]).toBe(api.dictate.mock.calls[0]![1]);
    expect(view.result.current.state.reason).toBe("timeout");

    act(() => view.result.current.actions.dismiss());
    expect(view.result.current.state.phase).toBe("idle");
    expect(view.result.current.state.reason).toBeNull();
    expect(view.result.current.state.canRetry).toBe(false);
    await act(async () => view.result.current.actions.retry());
    expect(api.dictate).toHaveBeenCalledTimes(2);
  });

  it("a retry that succeeds hands the text over", async () => {
    api.dictate.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const view = setup();
    await record(view);
    await wait(1500);
    await act(async () => view.result.current.actions.stop());
    expect(view.result.current.state.reason).toBe("offline");

    await act(async () => view.result.current.actions.retry());

    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
    expect(view.result.current.state.phase).toBe("idle");
  });

  it("reads a 413 from the body-limit middleware as too large, and keeps nothing", async () => {
    api.dictate.mockRejectedValueOnce(refusal(413));
    const view = setup();
    await record(view);
    await wait(1500);

    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.reason).toBe("too_large");
    expect(view.result.current.state.canRetry).toBe(false);
    await act(async () => view.result.current.actions.retry());
    expect(api.dictate).toHaveBeenCalledOnce();
  });

  it("holds a rate-limited retry until the wait has passed", async () => {
    api.dictate.mockRejectedValueOnce(refusal(429, { retry_after_seconds: 40 }));
    const view = setup();
    await record(view);
    await wait(1500);
    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.reason).toBe("rate_limited");
    expect(view.result.current.state.retryAfter).toBe(40);
    await act(async () => view.result.current.actions.retry());
    expect(api.dictate).toHaveBeenCalledOnce();

    await wait(1000);
    expect(view.result.current.state.retryAfter).toBe(39);
    await wait(39_000);
    expect(view.result.current.state.retryAfter).toBeNull();

    await act(async () => view.result.current.actions.retry());
    expect(api.dictate).toHaveBeenCalledTimes(2);
  });

  it("treats a request aborted from elsewhere as no failure", async () => {
    api.dictate.mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    const view = setup();
    await record(view);
    await wait(1500);

    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("idle");
    expect(view.result.current.state.reason).toBeNull();
  });

  it.each<[string, Partial<UseMicrophoneResult>, string]>([
    ["the browser refused", { state: "denied" }, "mic_denied"],
    [
      "the error says not allowed",
      { state: "error", error: Object.assign(new Error("no"), { name: "NotAllowedError" }) },
      "mic_denied",
    ],
    [
      "the system refused",
      { state: "error", error: Object.assign(new Error("no"), { name: "SecurityError" }) },
      "mic_denied",
    ],
    [
      "there is no device",
      { state: "error", error: Object.assign(new Error("no"), { name: "NotFoundError" }) },
      "mic_not_found",
    ],
    [
      "no device meets the constraints",
      { state: "error", error: Object.assign(new Error("no"), { name: "OverconstrainedError" }) },
      "mic_not_found",
    ],
    [
      "another app holds the device",
      { state: "error", error: Object.assign(new Error("no"), { name: "NotReadableError" }) },
      "mic_busy",
    ],
    ["nothing says why", { state: "error" }, "mic_busy"],
  ])("explains a microphone that did not open when %s", async (_label, mic, reason) => {
    const view = setup({ mic: fakeMic({ ...mic, start: vi.fn(async () => null) }) });

    await record(view);

    expect(view.result.current.state.phase).toBe("failed");
    expect(view.result.current.state.reason).toBe(reason);
    expect(view.result.current.state.canRetry).toBe(false);
    expect(FakeRecorder.instances).toHaveLength(0);
  });

  it("logs what the browser said when the microphone did not open", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = Object.assign(new Error("Requested device not found"), { name: "NotFoundError" });
    const view = setup({ mic: fakeMic({ state: "error", error, start: vi.fn(async () => null) }) });

    await record(view);

    expect(warn).toHaveBeenCalledWith("Dictation: the microphone did not open:", error);
    warn.mockRestore();
  });

  it("does not ask for a microphone this browser cannot open", async () => {
    const view = setup({ mic: fakeMic({ supported: false }) });

    await record(view);

    expect(view.mic.start).not.toHaveBeenCalled();
    expect(view.result.current.state.reason).toBe("mic_insecure");
    expect(FakeRecorder.instances).toHaveLength(0);
  });

  it.each([
    ["no MediaRecorder at all", () => vi.stubGlobal("MediaRecorder", undefined)],
    ["no type the server accepts", () => (FakeRecorder.supported = new Set(["audio/wav"]))],
  ])("refuses to record where there is %s, and closes the microphone", async (_label, arrange) => {
    arrange();
    const view = setup();

    await record(view);

    expect(view.result.current.state.reason).toBe("unsupported_type");
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it.each([
    ["opened", stream],
    ["refused", null],
  ])(
    "a cancel while the browser asks wins even when the prompt is then %s",
    async (_label, answer) => {
      const opened = deferred<MediaStream | null>();
      const view = setup({ mic: fakeMic({ start: vi.fn(() => opened.promise) }) });
      let started!: Promise<void>;
      act(() => {
        started = view.result.current.actions.start();
      });

      act(() => view.result.current.actions.cancel());
      vi.mocked(view.mic.stop).mockClear();
      await act(async () => {
        opened.resolve(answer);
        await started;
      });

      expect(view.result.current.state.phase).toBe("idle");
      expect(FakeRecorder.instances).toHaveLength(0);
      expect(view.mic.stop).toHaveBeenCalledTimes(answer === null ? 0 : 1);
    },
  );

  it("ignores a second press while one recording is under way, and a press with no agent", async () => {
    const view = setup();
    await record(view);
    await record(view);
    expect(view.mic.start).toHaveBeenCalledOnce();

    const none = setup({ agentId: null });
    await record(none);
    expect(none.mic.start).not.toHaveBeenCalled();
    expect(none.result.current.state.phase).toBe("idle");
  });

  it("stops the recorder once when the device goes away while it is already stopping", async () => {
    FakeRecorder.deferStop = true;
    const view = setup();
    await record(view);
    await wait(2000);

    act(() => view.result.current.actions.stop());
    act(() => {
      track.dispatchEvent(new Event("ended"));
    });
    act(() => view.result.current.actions.stop());
    await wait(0);

    expect(lastRecorder().stopCalls).toBe(1);
    expect(api.dictate).toHaveBeenCalledOnce();
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
  });

  it("drops a transcript that arrives after a cancel the request did not hear", async () => {
    const answered = deferred<string>();
    api.dictate.mockReturnValue(answered.promise);
    const view = setup();
    await record(view);
    await wait(1500);
    act(() => view.result.current.actions.stop());

    act(() => view.result.current.actions.cancel());
    await act(async () => answered.resolve("too late"));

    expect(view.result.current.state.transcript).toBeNull();
    expect(view.result.current.state.phase).toBe("idle");
  });

  it("stops the rate-limit countdown when the recording is discarded", async () => {
    api.dictate.mockRejectedValueOnce(refusal(429, { retry_after_seconds: 40 }));
    const view = setup();
    await record(view);
    await wait(1500);
    await act(async () => view.result.current.actions.stop());
    expect(view.result.current.state.retryAfter).toBe(40);

    act(() => view.result.current.actions.dismiss());
    await wait(5000);

    expect(view.result.current.state.retryAfter).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["stop", (view: ReturnType<typeof setup>) => act(() => view.result.current.actions.stop())],
    ["cancel", (view: ReturnType<typeof setup>) => act(() => view.result.current.actions.cancel())],
    ["unmount", (view: ReturnType<typeof setup>) => view.unmount()],
  ])("takes the level meter down on %s", async (_label, end) => {
    const view = setup();
    await record(view);
    await wait(1500);
    const cancelFrame = vi.spyOn(globalThis, "cancelAnimationFrame");
    expect(audio.nodes).toHaveLength(2);

    end(view);
    await wait(0);

    for (const node of audio.nodes) expect(node.disconnect).toHaveBeenCalledOnce();
    expect(cancelFrame).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    cancelFrame.mockRestore();
  });

  it.each([
    [
      "refuses to construct it",
      () => {
        vi.stubGlobal(
          "MediaRecorder",
          Object.assign(
            function Refusing() {
              throw new DOMException("no", "NotSupportedError");
            },
            { isTypeSupported: () => true },
          ),
        );
      },
      "unsupported_type",
    ],
    [
      "refuses to start it",
      () => {
        vi.stubGlobal(
          "MediaRecorder",
          class extends FakeRecorder {
            override start(): void {
              throw new DOMException("ended", "InvalidStateError");
            }
          },
        );
      },
      "mic_busy",
    ],
  ])("fails, and closes the microphone, when the browser %s", async (_label, arrange, reason) => {
    arrange();
    const view = setup();

    await record(view);

    expect(view.result.current.state.phase).toBe("failed");
    expect(view.result.current.state.reason).toBe(reason);
    expect(view.mic.stop).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does nothing on stop when nothing is recording", () => {
    const view = setup();

    act(() => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("idle");
  });

  it("stops the recorder and closes the microphone on unmount", async () => {
    const view = setup();
    await record(view);
    await wait(2000);

    view.unmount();

    expect(lastRecorder().state).toBe("inactive");
    expect(view.mic.stop).toHaveBeenCalled();
    expect(api.dictate).not.toHaveBeenCalled();
  });

  it("aborts a request in flight on unmount", async () => {
    let signal!: AbortSignal;
    api.dictate.mockImplementation((_agent, _blob, given) => {
      signal = given;
      return new Promise(() => {});
    });
    const view = setup();
    await record(view);
    await wait(1500);
    act(() => view.result.current.actions.stop());

    view.unmount();

    expect(signal.aborted).toBe(true);
  });
});

/** Hand the WAV recorder one callback's worth of 48 kHz samples, one array per channel. */
function speak(...channels: number[][]): void {
  const inputBuffer = {
    numberOfChannels: channels.length,
    getChannelData: (i: number) => Float32Array.from(channels[i]!),
  };
  act(() => {
    audio.processors
      .at(-1)!
      .dispatchEvent(Object.assign(new Event("audioprocess"), { inputBuffer }));
  });
}

/** 4,800 samples at 48 kHz: 100 ms, which is 1,600 samples at 16 kHz. */
const TENTH = 4800;

describe("useDictation - WAV, for a provider that does not take WebM or Opus", () => {
  const mistral = (options: Partial<UseDictationOptions> = {}) =>
    setup({ provider: "mistral", ...options });

  it("records 16 kHz mono 16-bit WAV from the stream instead of using MediaRecorder", async () => {
    const view = mistral();
    await record(view);
    expect(view.result.current.state.phase).toBe("recording");
    await wait(2000);
    expect(view.result.current.state.elapsed).toBe(2);
    speak(new Array(TENTH).fill(0.5), new Array(TENTH).fill(0.25));
    speak(new Array(TENTH).fill(0.5), new Array(TENTH).fill(0.25));

    await act(async () => view.result.current.actions.stop());

    expect(FakeRecorder.instances).toHaveLength(0);
    const [processor] = audio.processors;
    expect(processor!.args).toEqual([4096, 2, 1]);
    // Source into the processor, through a muted gain, to the destination: the
    // processor only runs connected, and nobody hears their own voice back.
    const source = audio.nodes[audio.nodes.indexOf(processor!) - 1]!;
    expect(source.connect).toHaveBeenCalledWith(processor);
    expect(processor!.connect).toHaveBeenCalledWith(audio.gains[0]);
    expect(audio.gains[0]!.gain.value).toBe(0);
    expect(audio.gains[0]!.connect).toHaveBeenCalledWith(audio.destination);

    const [agentId, recording] = api.dictate.mock.calls[0]!;
    expect(agentId).toBe("a1");
    expect(recording.type).toBe("audio/wav");
    expect(recording.size).toBe(44 + 2 * 1600 * 2);
    const view16 = new DataView(await recording.arrayBuffer());
    expect(view16.getUint32(24, true)).toBe(16_000);
    expect(view16.getUint16(22, true)).toBe(1);
    // Left and right averaged: 0.375 of full scale.
    expect(view16.getInt16(44, true)).toBe(Math.trunc(0.375 * 0x7fff));
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it("keeps MediaRecorder for every other provider", async () => {
    const view = setup({ provider: "openai" });

    await record(view);

    expect(lastRecorder().options.mimeType).toBe("audio/webm;codecs=opus");
    expect(audio.processors).toHaveLength(0);
  });

  it("reads the provider when the mic is pressed, after the organization has loaded", async () => {
    const view = setup();
    view.rerender({ mic: view.mic, agentId: "a1", maxSeconds: 300, provider: "mistral" });

    await record(view);

    expect(audio.processors).toHaveLength(1);
    expect(FakeRecorder.instances).toHaveLength(0);
  });

  it.each<[string, (view: ReturnType<typeof setup>) => Promise<void> | void, boolean]>([
    ["a stop", (view) => act(() => view.result.current.actions.stop()), true],
    ["the limit", () => wait(8000), true],
    ["the track ending", () => act(() => void track.dispatchEvent(new Event("ended"))), true],
    ["a cancel", (view) => act(() => view.result.current.actions.cancel()), false],
    ["an unmount", (view) => view.unmount(), false],
  ])(
    "on %s, takes every node down and closes the microphone, uploading: %s",
    async (_label, end, uploads) => {
      const view = mistral({ maxSeconds: 10 });
      await record(view);
      await wait(2000);
      speak(new Array(TENTH).fill(0.1));

      await end(view);
      await wait(0);

      expect(api.dictate).toHaveBeenCalledTimes(uploads ? 1 : 0);
      // The meter's source and analyser, the recorder's source, processor and gain.
      expect(audio.nodes).toHaveLength(5);
      for (const node of audio.nodes) expect(node.disconnect).toHaveBeenCalledOnce();
      expect(view.mic.stop).toHaveBeenCalled();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("a recording under a second is too short, and nothing is uploaded", async () => {
    const view = mistral();
    await record(view);
    await wait(500);
    speak(new Array(TENTH).fill(0.1));

    await act(async () => view.result.current.actions.stop());

    expect(view.result.current.state.phase).toBe("too_short");
    expect(api.dictate).not.toHaveBeenCalled();
  });

  it("keeps the WAV file after a provider error and sends the same one on retry", async () => {
    api.dictate.mockRejectedValueOnce(refusal(503, { reason: "provider_error" }));
    const view = mistral();
    await record(view);
    await wait(1500);
    await act(async () => view.result.current.actions.stop());
    expect(view.result.current.state.canRetry).toBe(true);

    await act(async () => view.result.current.actions.retry());

    expect(api.dictate.mock.calls[1]![1]).toBe(api.dictate.mock.calls[0]![1]);
    expect(api.dictate.mock.calls[1]![1].type).toBe("audio/wav");
    expect(view.result.current.state.transcript).toEqual({ id: 1, text: "hello" });
  });

  it("meters the level and the silence as it does for any recording", async () => {
    const view = mistral();
    await record(view);

    await wait(5100);
    expect(view.result.current.state.silent).toBe(true);
    audio.level = 0.2;
    await wait(100);

    expect(view.result.current.state.silent).toBe(false);
    expect(view.result.current.state.level).toBeGreaterThan(0.3);
  });

  it("counts down in the last thirty seconds", async () => {
    const view = mistral({ maxSeconds: 40 });
    await record(view);

    await wait(15_000);

    expect(view.result.current.state.remaining).toBe(25);
  });

  it("refuses, and closes the microphone, where the page has no Web Audio", async () => {
    audio.available = false;
    const view = mistral();

    await record(view);

    expect(view.result.current.state.phase).toBe("failed");
    expect(view.result.current.state.reason).toBe("unsupported_type");
    expect(FakeRecorder.instances).toHaveLength(0);
    expect(view.mic.stop).toHaveBeenCalled();
  });

  it("fails as a microphone that would not start when the stream ended before recording", async () => {
    const ended = { active: false, getAudioTracks: () => [track] } as unknown as MediaStream;
    const view = mistral({ mic: fakeMic({ start: vi.fn(async () => ended) }) });

    await record(view);

    expect(view.result.current.state.reason).toBe("mic_busy");
    expect(audio.processors).toHaveLength(0);
    expect(view.mic.stop).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
